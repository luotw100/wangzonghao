import type { IncomingMessage, MsgType } from '../types'

interface Thread {
  convId: string
  peerId: string          // chat contact id — used as peer_platform_id toward Studio
  peerDisplayName: string
}

/**
 * Chat sandbox HTTP adapter.
 *
 * Peer identity = the conversation's contact. `peerId` is the chat
 * contact id (reported to Studio as peer_platform_id); messages are
 * fetched/sent via the conversation id, so we keep contactId → convId.
 */
export class ChatAdapter {
  private token: string | null = null
  private selfId: string | null = null
  private threads = new Map<string, Thread>()   // keyed by peerId (contact id)
  private stopped = false

  constructor(
    private baseUrl: string,
    private username: string,
    private password: string,
  ) {}

  private async req<T>(method: string, path: string, body?: unknown): Promise<T> {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 15_000)
    try {
      const res = await fetch(`${this.baseUrl}${path}`, {
        method,
        signal: ctrl.signal,
        headers: {
          'Content-Type': 'application/json',
          ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
        },
        body: body != null ? JSON.stringify(body) : undefined,
      })
      if (!res.ok) throw new Error(`Chat API ${res.status} ${path}`)
      return res.json() as Promise<T>
    } catch (err: any) {
      if (err?.name === 'AbortError') throw new Error(`Chat API 超时 ${path}（检查 Chat Base URL 是否可达）`)
      throw err
    } finally {
      clearTimeout(timer)
    }
  }

  async login(): Promise<string> {
    const res: { token: string; account: { id: string } } =
      await this.req('POST', '/api/auth/login', { username: this.username, password: this.password })
    this.token = res.token
    this.selfId = res.account.id
    return this.selfId
  }

  private async refreshThreads(): Promise<void> {
    const convs: Array<{ id: string; contact: { id: string; nickname: string; username: string } }> =
      await this.req('GET', '/api/conversations')
    for (const c of convs) {
      this.threads.set(c.contact.id, {
        convId: c.id,
        peerId: c.contact.id,
        peerDisplayName: c.contact.nickname || c.contact.username,
      })
    }
  }

  async listPeers(): Promise<Array<{ peerPlatformId: string; displayName: string }>> {
    await this.refreshThreads()
    return [...this.threads.values()].map(t => ({
      peerPlatformId: t.peerId,
      displayName: t.peerDisplayName,
    }))
  }

  async *scan(cursors: Record<string, string | null>): AsyncGenerator<IncomingMessage> {
    while (!this.stopped) {
      try {
        await this.refreshThreads()
      } catch {
        await sleep(2000)
        continue
      }

      let yieldedAny = false
      for (const thread of this.threads.values()) {
        if (this.stopped) break
        const since = Number(cursors[thread.peerId] ?? '0') || 0
        let payload: { messages: Array<{ id: number; sender_type: string; sender_contact_id: string | null; msg_type: string; content: string; created_at: string }> }
        try {
          payload = await this.req(
            'GET',
            `/api/conversations/${thread.convId}/messages?last_id=${since}&limit=200`,
          )
        } catch {
          continue
        }

        for (const m of payload.messages) {
          cursors[thread.peerId] = String(m.id)
          yieldedAny = true
          yield {
            peerId: thread.peerId,
            peerDisplayName: thread.peerDisplayName,
            platformMsgId: String(m.id),
            senderId: m.sender_type === 'self' ? this.platformSelfId : thread.peerId,
            msgType: (m.msg_type as MsgType) || 'text',
            content: m.content,
            sentAt: new Date(m.created_at),
          }
        }
      }

      if (!yieldedAny) await sleep(2000)
    }
  }

  async send(peerId: string, content: string): Promise<string> {
    const thread = this.threads.get(peerId)
    if (!thread) throw new Error(`unknown peer ${peerId}`)
    const res: { id: number | null } = await this.req(
      'POST',
      `/api/conversations/${thread.convId}/messages`,
      { sender_type: 'self', msg_type: 'text', content },
    )
    return res.id != null ? String(res.id) : ''
  }

  stop(): void {
    this.stopped = true
  }

  get platformSelfId(): string {
    if (!this.selfId) throw new Error('not logged in')
    return this.selfId
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise(r => setTimeout(r, ms))
}
