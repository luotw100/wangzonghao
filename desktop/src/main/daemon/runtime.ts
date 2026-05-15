import { createHash } from 'crypto'
import { join } from 'path'
import { mkdirSync } from 'fs'
import type { InboxClaim, StudioInbox, DaemonState, InboxStatus, LogLine } from './types'
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
  claim: InboxClaim
  adapter: ChatAdapter
  inbox: StudioInbox
  cursors: Record<string, string | null>
  scanAbort: AbortController
}

export class BridgeRuntime {
  private adapters = new Map<string, AdapterEntry>()
  private activePeers = new Set<string>() // "inboxId|peerId"
  private outboundCursor = 0
  private stopped = false
  private timers: ReturnType<typeof setInterval>[] = []
  private store: LocalStore

  constructor(
    private studio: StudioClient,
    private claims: InboxClaim[],
    private stateDir: string,
    private emit: (event: 'status' | 'log', payload: DaemonState | LogLine) => void,
    private getState: () => Omit<DaemonState, 'inboxes' | 'inCount5m' | 'outboundPending'>,
  ) {
    mkdirSync(stateDir, { recursive: true })
    this.store = new LocalStore(join(stateDir, 'messages.db'))
  }

  private log(src: string, level: LogLine['level'], msg: string): void {
    this.emit('log', { t: ts(), src, level, msg })
  }

  private pushState(status: DaemonState['status']): void {
    const base = this.getState()
    const inboxes: InboxStatus[] = [...this.adapters.values()].map(e => ({
      inboxId: e.inbox.id,
      handle: e.claim.username,
      baseUrl: e.claim.baseUrl,
      platform: 'chat' as const,
      platformSelfId: e.adapter.platformSelfId,
      status: 'online',
      peersCount: Object.keys(e.cursors).length,
    }))
    this.emit('status', {
      ...base,
      status,
      inboxes,
      inCount5m: this.store.countRecentIncoming(5 * 60 * 1000),
      outboundPending: this.store.countUnsent(),
    })
  }

  async run(opts: {
    handshakeToken: string | null
    machineId: string | undefined
    onAuthError: () => void
    onCursorInit: (cursor: number) => void
  }): Promise<void> {
    this.pushState('connecting')
    this.log('core', 'info', `starting · claims=${this.claims.length}`)

    // 1. Login all adapters
    const loggedIn: Array<{ claim: InboxClaim; adapter: ChatAdapter; selfId: string }> = []
    for (const claim of this.claims) {
      const adapter = new ChatAdapter(claim.baseUrl, claim.username, claim.password)
      try {
        const selfId = await adapter.login()
        this.log('adapter', 'ok', `login ok · ${claim.username}@${claim.baseUrl} selfId=${selfId}`)
        loggedIn.push({ claim, adapter, selfId })
      } catch (err) {
        this.log('adapter', 'err', `login failed · ${claim.username}: ${err}`)
      }
    }

    if (loggedIn.length === 0) {
      this.log('core', 'err', 'no adapters logged in — stopping')
      this.pushState('offline')
      return
    }

    // 2. Handshake with Studio
    let token = opts.handshakeToken
    let machineId = opts.machineId
    let inboxes: StudioInbox[]
    let cursor: number

    try {
      const hs = await this.studio.handshake({
        username: this.getState().username!,
        password: '',  // token reuse path handled by studio-client bearer header
        machineId,
        inboxes: loggedIn.map(l => ({ platform: 'chat', platformSelfId: l.selfId })),
      })
      token = hs.token
      machineId = hs.machineId
      inboxes = hs.inboxes
      cursor = hs.cursor
      this.outboundCursor = cursor
      opts.onCursorInit(cursor)
      this.log('studio', 'ok', `handshake ok · bridge_id=${hs.bridgeId} machine_id=${machineId}`)
    } catch (err: any) {
      if (String(err).includes('401')) {
        opts.onAuthError()
        this.pushState('error401')
      } else {
        this.log('studio', 'err', `handshake failed: ${err}`)
        this.pushState('offline')
      }
      return
    }

    // 3. Bind adapters to inboxes
    for (const li of loggedIn) {
      const inbox = inboxes.find(ib => ib.platformSelfId === li.selfId)
      if (!inbox) {
        this.log('adapter', 'warn', `no inbox for selfId=${li.selfId}`)
        continue
      }
      const cursors = this.store.getCursors(inbox.id)
      const scanAbort = new AbortController()
      this.adapters.set(inbox.id, { claim: li.claim, adapter: li.adapter, inbox, cursors, scanAbort })
    }

    this.pushState('online')

    // 4. Start all loops
    for (const [inboxId, entry] of this.adapters) {
      this.startProducer(inboxId, entry)
    }
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
          const content = msg.content
          const localHash = LocalStore.localHash(
            inboxId, msg.peerId, msg.senderId, sentAt, msg.msgType, content,
          )
          this.store.insertMessage({
            inboxId,
            peerId: msg.peerId,
            peerDisplayName: msg.peerDisplayName,
            platformMsgId: msg.platformMsgId,
            senderId: msg.senderId,
            sentAt,
            msgType: msg.msgType,
            content,
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
        const role = row.senderId === entry.adapter.platformSelfId ? 'self' : 'counterpart'
        try {
          await this.studio.pushIncoming([{
            inboxId: row.inboxId,
            peerPlatformId: row.peerId,
            peerDisplayName: row.peerDisplayName,
            platformMsgId: row.platformMsgId,
            role,
            msgType: row.msgType,
            content: row.content,
            sentAt: row.sentAt,
          }])
          this.store.markSent(row.id)
        } catch (err: any) {
          if (String(err).includes('401')) return // heartbeat will handle 401
          this.log('consumer', 'warn', `push failed: ${err}`)
        }
      }
    }

    const id = setInterval(() => { tick() }, CONSUMER_MS)
    this.timers.push(id)
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
        this.log('heart', 'info', `♥ ok · ${this.adapters.size} inbox online`)
        this.pushState('online')
      } catch (err: any) {
        if (String(err).includes('401')) {
          this.log('heart', 'err', `401 · session revoked`)
          onAuthError()
          this.pushState('error401')
          this.stop()
        } else {
          this.log('heart', 'warn', `heartbeat failed: ${err}`)
        }
      }
    }
    const id = setInterval(() => { beat() }, HEARTBEAT_MS)
    this.timers.push(id)
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
    const id = setInterval(() => { announce() }, ANNOUNCE_MS)
    this.timers.push(id)
    announce()
  }

  private startActivePeers(): void {
    const fetch = async () => {
      if (this.stopped) return
      try {
        const peers = await this.studio.getActivePeers()
        this.activePeers = new Set(peers.map(p => `${p.inboxId}|${p.peerPlatformId}`))
      } catch {}
    }
    const id = setInterval(() => { fetch() }, ACTIVE_PEERS_MS)
    this.timers.push(id)
    fetch()
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
        // Media: download from Studio S3, send via adapter (not implemented for chat sandbox)
        this.log('outbound', 'warn', `media outbound not supported for chat adapter`)
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
