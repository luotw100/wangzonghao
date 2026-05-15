import type { IncomingMessage, MsgType } from '../types'

interface Thread {
  peerId: string
  peerDisplayName: string
}

export class ChatAdapter {
  private token: string | null = null
  private selfId: string | null = null
  private threads: Map<string, Thread> = new Map()
  private stopped = false

  constructor(
    private baseUrl: string,
    private username: string,
    private password: string,
  ) {}

  private async req<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
      },
      body: body != null ? JSON.stringify(body) : undefined,
    })
    if (!res.ok) throw new Error(`Chat API ${res.status} ${path}`)
    return res.json() as Promise<T>
  }

  async login(): Promise<string> {
    const res: { token: string; account_id: string } = await this.req('POST', '/api/auth/login', {
      username: this.username,
      password: this.password,
    })
    this.token = res.token
    this.selfId = res.account_id
    return res.account_id
  }

  private async refreshThreads(): Promise<void> {
    const convs: Array<{ id: string; peer?: { id: string; username: string } }> =
      await this.req('GET', '/api/conversations')
    for (const c of convs) {
      if (!c.peer) continue
      this.threads.set(c.id, { peerId: c.peer.id, peerDisplayName: c.peer.username })
    }
  }

  async listPeers(): Promise<Array<{ peerPlatformId: string; displayName: string }>> {
    await this.refreshThreads()
    return [...this.threads.values()].map(t => ({
      peerPlatformId: t.peerId,
      displayName: t.peerDisplayName,
    }))
  }

  async *scan(
    cursors: Record<string, string | null>,
  ): AsyncGenerator<IncomingMessage> {
    while (!this.stopped) {
      try {
        await this.refreshThreads()
      } catch (err) {
        await sleep(2000)
        continue
      }

      let yieldedAny = false
      for (const [, thread] of this.threads) {
        const since = cursors[thread.peerId] ?? '0'
        let msgs: Array<{
          id: string
          sender_id: string
          content: string
          msg_type: string
          created_at: string
        }>
        try {
          msgs = await this.req('GET', `/api/conversations/${thread.peerId}/messages?since_id=${since}`)
        } catch {
          continue
        }

        for (const m of msgs) {
          cursors[thread.peerId] = m.id
          yieldedAny = true
          yield {
            peerId: thread.peerId,
            peerDisplayName: thread.peerDisplayName,
            platformMsgId: m.id,
            senderId: m.sender_id,
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
    const res: { id: string } = await this.req('POST', `/api/conversations/${peerId}/messages`, {
      content,
      msg_type: 'text',
    })
    return res.id
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
