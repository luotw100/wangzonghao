import type { StudioInbox, OutboundItem, MsgType } from './types'

export class StudioClient {
  constructor(
    private baseUrl: string,
    private getToken: () => string | null,
  ) {}

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    timeoutMs = 10_000,
  ): Promise<T> {
    const token = this.getToken()
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), timeoutMs)
    try {
      const res = await fetch(`${this.baseUrl}${path}`, {
        method,
        signal: ctrl.signal,
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: body != null ? JSON.stringify(body) : undefined,
      })
      if (res.status === 401) throw new Error('401')
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(`HTTP ${res.status}: ${text}`)
      }
      return res.json() as Promise<T>
    } finally {
      clearTimeout(timer)
    }
  }

  /** Login: password in, token out. The only password call. */
  async handshake(opts: {
    username: string
    password: string
    machineId?: string
  }): Promise<{ token: string; bridgeId: string; machineId: string; accountId: string }> {
    const r: any = await this.request('POST', '/api/bridge/handshake', {
      username: opts.username,
      password: opts.password,
      machine_id: opts.machineId,
    })
    return { token: r.token, bridgeId: r.bridge_id, machineId: r.machine_id, accountId: r.account_id }
  }

  /** Token-authenticated channel registration. Called on every daemon start. */
  async registerInboxes(
    selfIds: Array<{ platform: string; platformSelfId: string }>,
  ): Promise<{ inboxes: StudioInbox[]; cursor: number; noPersona: boolean }> {
    const r: any = await this.request('POST', '/api/bridge/inboxes', {
      inboxes: selfIds.map(s => ({ platform: s.platform, platform_self_id: s.platformSelfId })),
    })
    return {
      inboxes: (r.inboxes as any[]).map(i => ({
        id: i.id,
        platform: i.platform,
        platformSelfId: i.platform_self_id,
        displayName: i.display_name,
        enabled: i.enabled,
        defaultPersonaId: i.default_persona_id,
      })),
      cursor: r.cursor,
      noPersona: r.no_persona,
    }
  }

  async heartbeat(): Promise<{ inboxes: StudioInbox[] }> {
    const r: any = await this.request('POST', '/api/bridge/heartbeat')
    return {
      inboxes: (r.inboxes as any[]).map(i => ({
        id: i.id,
        platform: i.platform,
        platformSelfId: i.platform_self_id,
        displayName: i.display_name,
        enabled: i.enabled,
        defaultPersonaId: i.default_persona_id,
      })),
    }
  }

  async pushIncoming(messages: Array<{
    inboxId: string
    peerPlatformId: string
    peerDisplayName: string
    platformMsgId: string | null
    senderId: string
    msgType: MsgType
    content: string
    sentAt: string
  }>): Promise<{ accepted: number; deduped: number; rejected: number }> {
    return this.request('POST', '/api/bridge/incoming', {
      messages: messages.map(m => ({
        inbox_id: m.inboxId,
        peer_platform_id: m.peerPlatformId,
        peer_display_name: m.peerDisplayName,
        platform_msg_id: m.platformMsgId,
        sender_id: m.senderId,
        msg_type: m.msgType,
        content: m.content,
        sent_at: m.sentAt,
      })),
    })
  }

  async getOutbound(cursor: number, timeoutSecs: number): Promise<OutboundItem[]> {
    const res: unknown[] = await this.request(
      'GET',
      `/api/bridge/outbound?cursor=${cursor}&timeout=${timeoutSecs}`,
      undefined,
      (timeoutSecs + 5) * 1000,
    )
    return (res as any[]).map(o => ({
      id: o.id,
      inboxId: o.inbox_id,
      contactId: o.contact_id,
      peerPlatformId: o.peer_platform_id,
      msgType: o.msg_type,
      content: o.content,
    }))
  }

  async ackOutbound(id: number, result: 'sent', platformMsgId: string): Promise<void>
  async ackOutbound(id: number, result: 'failed', reason: string): Promise<void>
  async ackOutbound(id: number, result: string, extra: string): Promise<void> {
    await this.request('POST', `/api/bridge/outbound/${id}/ack`, {
      result,
      ...(result === 'sent' ? { platform_msg_id: extra } : { reason: extra }),
    })
  }

  async announcePeers(inboxId: string, peers: Array<{ peerPlatformId: string; displayName: string }>): Promise<void> {
    await this.request('POST', '/api/bridge/peers', {
      inbox_id: inboxId,
      peers: peers.map(p => ({ peer_platform_id: p.peerPlatformId, display_name: p.displayName })),
    })
  }

  async getActivePeers(): Promise<Array<{ inboxId: string; peerPlatformId: string }>> {
    const res: { peers: unknown[] } = await this.request('GET', '/api/bridge/active-peers')
    return (res.peers as any[]).map(p => ({
      inboxId: p.inbox_id,
      peerPlatformId: p.peer_platform_id,
    }))
  }
}
