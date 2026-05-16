import { join } from 'path'
import { mkdirSync } from 'fs'
import type { Channel, StudioInbox, DaemonState, ChannelStatus, LogLine } from './types'
import { ChatAdapter } from './adapters/chat'
import { LocalStore } from './local-store'
import { StudioClient } from './studio-client'

const HEARTBEAT_MS = 15_000
const ANNOUNCE_MS = 60_000
const ACTIVE_PEERS_MS = 10_000
const CONSUMER_MS = 1_000
const CONSUMER_BATCH = 50
const OUTBOUND_TIMEOUT_SECS = 30

function sleep(ms: number): Promise<void> {
  return new Promise(r => setTimeout(r, ms))
}

function ts(): string {
  return new Date().toTimeString().slice(0, 8)
}

interface AdapterEntry {
  channel: Channel
  adapter: ChatAdapter
  inbox: StudioInbox
  cursors: Record<string, string | null>
}

export class BridgeRuntime {
  private adapters = new Map<string, AdapterEntry>()
  private activePeers = new Set<string>() // "inboxId|peerId"
  private outboundCursor = 0
  private lastError?: string
  private stopped = false
  private timers: ReturnType<typeof setInterval>[] = []
  private store: LocalStore

  constructor(
    private studio: StudioClient,
    private channels: Channel[],
    private stateDir: string,
    private emit: (event: 'status' | 'log', payload: DaemonState | LogLine) => void,
    private getBase: () => Pick<DaemonState, 'studioUrl' | 'username' | 'machineId' | 'bridgeId'>,
  ) {
    mkdirSync(stateDir, { recursive: true })
    this.store = new LocalStore(join(stateDir, 'messages.db'))
  }

  private log(src: string, level: LogLine['level'], msg: string): void {
    this.emit('log', { t: ts(), src, level, msg })
  }

  private pushState(status: DaemonState['status']): void {
    const channels: ChannelStatus[] = [...this.adapters.values()].map(e => ({
      inboxId: e.inbox.id,
      handle: e.channel.username,
      baseUrl: e.channel.baseUrl,
      platformSelfId: e.adapter.platformSelfId,
      online: true,
      peersCount: Object.keys(e.cursors).length,
    }))
    this.emit('status', {
      ...this.getBase(),
      status,
      channels,
      inCount5m: this.store.countRecentIncoming(5 * 60 * 1000),
      outboundPending: this.store.countUnsent(),
      lastError: this.lastError,
    })
  }

  /** Token-only run. The studio client is already bound to a saved token. */
  async run(opts: { onAuthError: () => void }): Promise<void> {
    this.lastError = undefined
    this.pushState('connecting')
    this.log('core', 'info', `starting · channels=${this.channels.length}`)

    // 1. Login all chat adapters
    const loggedIn: Array<{ channel: Channel; adapter: ChatAdapter; selfId: string }> = []
    const loginErrors: string[] = []
    for (const channel of this.channels) {
      const adapter = new ChatAdapter(channel.baseUrl, channel.username, channel.password)
      try {
        const selfId = await adapter.login()
        this.log('adapter', 'ok', `login ok · ${channel.username}@${channel.baseUrl}`)
        loggedIn.push({ channel, adapter, selfId })
      } catch (err) {
        const m = `${channel.username}@${channel.baseUrl}: ${err instanceof Error ? err.message : err}`
        this.log('adapter', 'err', `login failed · ${m}`)
        loginErrors.push(m)
      }
    }

    if (loggedIn.length === 0) {
      this.lastError = `无法登录聊天平台(检查 Chat Base URL 是否可达):${loginErrors.join(' / ')}`
      this.log('core', 'err', 'no channels logged in — stopping')
      this.pushState('offline')
      return
    }

    // 2. Register channels with Studio (token-authenticated, no password)
    let inboxes: StudioInbox[]
    try {
      const r = await this.studio.registerInboxes(
        loggedIn.map(l => ({ platform: 'chat', platformSelfId: l.selfId })),
      )
      inboxes = r.inboxes
      this.outboundCursor = r.cursor
      this.log('studio', 'ok', `inboxes registered · ${inboxes.length} inbox · cursor=${r.cursor}`)
      if (r.noPersona) this.log('studio', 'warn', 'Studio 账号还没有 Persona,自动回复不会触发')
    } catch (err: any) {
      if (String(err).includes('401')) {
        this.lastError = 'Studio session 失效,请重新登录'
        opts.onAuthError()
        this.pushState('error401')
      } else {
        this.lastError = `Studio 注册 channel 失败: ${err instanceof Error ? err.message : err}`
        this.log('studio', 'err', `register inboxes failed: ${err}`)
        this.pushState('offline')
      }
      return
    }

    // 3. Bind adapters to inboxes
    for (const li of loggedIn) {
      const inbox = inboxes.find(ib => ib.platformSelfId === li.selfId)
      if (!inbox) {
        this.log('adapter', 'warn', `no inbox for ${li.channel.username}`)
        continue
      }
      const cursors = this.store.getCursors(inbox.id)
      this.adapters.set(inbox.id, { channel: li.channel, adapter: li.adapter, inbox, cursors })
    }

    this.pushState('online')

    // 4. Start all loops
    for (const [inboxId, entry] of this.adapters) this.startProducer(inboxId, entry)
    this.startConsumer()
    this.startHeartbeat(opts.onAuthError)
    this.startAnnounce()
    this.startActivePeers()
    this.startOutbound(opts.onAuthError)
  }

  private startProducer(inboxId: string, entry: AdapterEntry): void {
    const run = async () => {
      try {
        for await (const msg of entry.adapter.scan(entry.cursors)) {
          if (this.stopped) break
          const sentAt = msg.sentAt.toISOString()
          const localHash = LocalStore.localHash(
            inboxId, msg.peerId, msg.senderId, sentAt, msg.msgType, msg.content,
          )
          this.store.insertMessage({
            inboxId,
            peerId: msg.peerId,
            peerDisplayName: msg.peerDisplayName,
            platformMsgId: msg.platformMsgId,
            senderId: msg.senderId,
            sentAt,
            msgType: msg.msgType,
            content: msg.content,
            mimeType: null,
            localHash,
          })
        }
      } catch (err) {
        if (!this.stopped) this.log('producer', 'err', `inbox=${inboxId}: ${err}`)
      }
    }
    run()
  }

  private startConsumer(): void {
    const tick = async () => {
      if (this.stopped) return
      const rows = this.store.getUnsent(CONSUMER_BATCH, this.activePeers.size > 0 ? this.activePeers : null)
      for (const row of rows) {
        const entry = this.adapters.get(row.inboxId)
        if (!entry) { this.store.markSent(row.id); continue }
        try {
          await this.studio.pushIncoming([{
            inboxId: row.inboxId,
            peerPlatformId: row.peerId,
            peerDisplayName: row.peerDisplayName,
            platformMsgId: row.platformMsgId,
            senderId: row.senderId,
            msgType: row.msgType,
            content: row.content,
            sentAt: row.sentAt,
          }])
          this.store.markSent(row.id)
        } catch (err: any) {
          if (String(err).includes('401')) return // heartbeat handles 401
          this.log('consumer', 'warn', `push failed: ${err}`)
        }
      }
    }
    this.timers.push(setInterval(() => { tick() }, CONSUMER_MS))
  }

  private startHeartbeat(onAuthError: () => void): void {
    const beat = async () => {
      if (this.stopped) return
      try {
        const res = await this.studio.heartbeat()
        const activeIds = new Set(res.inboxes.map(i => i.id))
        for (const [id] of this.adapters) {
          if (!activeIds.has(id)) {
            this.log('heart', 'warn', `inbox ${id} removed by Studio`)
            this.adapters.get(id)?.adapter.stop()
            this.adapters.delete(id)
          }
        }
        this.pushState('online')
      } catch (err: any) {
        if (String(err).includes('401')) {
          this.log('heart', 'err', '401 · session revoked')
          onAuthError()
          this.pushState('error401')
          this.stop()
        } else {
          this.log('heart', 'warn', `heartbeat failed: ${err}`)
        }
      }
    }
    this.timers.push(setInterval(() => { beat() }, HEARTBEAT_MS))
    beat()
  }

  private startAnnounce(): void {
    const announce = async () => {
      if (this.stopped) return
      for (const [inboxId, entry] of this.adapters) {
        try {
          const peers = await entry.adapter.listPeers()
          await this.studio.announcePeers(inboxId, peers)
        } catch {}
      }
    }
    this.timers.push(setInterval(() => { announce() }, ANNOUNCE_MS))
    announce()
  }

  private startActivePeers(): void {
    const fetchActive = async () => {
      if (this.stopped) return
      try {
        const peers = await this.studio.getActivePeers()
        this.activePeers = new Set(peers.map(p => `${p.inboxId}|${p.peerPlatformId}`))
      } catch {}
    }
    this.timers.push(setInterval(() => { fetchActive() }, ACTIVE_PEERS_MS))
    fetchActive()
  }

  private startOutbound(onAuthError: () => void): void {
    const poll = async () => {
      while (!this.stopped) {
        try {
          const items = await this.studio.getOutbound(this.outboundCursor, OUTBOUND_TIMEOUT_SECS)
          for (const item of items) {
            if (this.stopped) break
            this.outboundCursor = Math.max(this.outboundCursor, item.id)
            await this.dispatchOutbound(item)
          }
        } catch (err: any) {
          if (String(err).includes('401')) { onAuthError(); this.pushState('error401'); this.stop(); break }
          this.log('outbound', 'warn', `poll error: ${err}`)
          await sleep(2000)
        }
      }
    }
    poll()
  }

  private async dispatchOutbound(item: { id: number; inboxId: string; peerPlatformId: string; msgType: string; content: string }): Promise<void> {
    const entry = this.adapters.get(item.inboxId)
    if (!entry) { await this.studio.ackOutbound(item.id, 'failed', 'inbox not found'); return }
    try {
      if (item.msgType === 'text') {
        const platformMsgId = await entry.adapter.send(item.peerPlatformId, item.content)
        await this.studio.ackOutbound(item.id, 'sent', platformMsgId)
        this.log('outbound', 'ok', `sent text to ${item.peerPlatformId}`)
      } else {
        this.log('outbound', 'warn', 'media outbound not supported for chat adapter')
        await this.studio.ackOutbound(item.id, 'failed', 'media not supported')
      }
    } catch (err) {
      this.log('outbound', 'err', `dispatch failed: ${err}`)
      await this.studio.ackOutbound(item.id, 'failed', String(err))
    }
  }

  stop(): void {
    if (this.stopped) return
    this.stopped = true
    for (const t of this.timers) clearInterval(t)
    for (const entry of this.adapters.values()) entry.adapter.stop()
    this.store.close()
    this.log('core', 'info', 'daemon stopped')
  }
}
