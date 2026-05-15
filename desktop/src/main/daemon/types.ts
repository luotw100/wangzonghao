export type MsgType = 'text' | 'image' | 'audio' | 'video' | 'file'

export interface IncomingMessage {
  peerId: string
  peerDisplayName: string
  platformMsgId: string | null
  senderId: string
  msgType: MsgType
  content: string
  sentAt: Date
}

export interface InboxClaim {
  baseUrl: string
  username: string
  password: string
}

export interface StudioInbox {
  id: string
  platform: string
  platformSelfId: string
  displayName: string
  enabled: boolean
  defaultPersonaId: string | null
}

export interface OutboundItem {
  id: number
  inboxId: string
  contactId: string
  peerPlatformId: string
  msgType: MsgType
  content: string
}

// Status emitted to the renderer via IPC
export type DaemonStatus = 'idle' | 'connecting' | 'online' | 'degraded' | 'offline' | 'error401'

export interface InboxStatus {
  inboxId: string | null
  handle: string
  baseUrl: string
  platform: 'chat'
  platformSelfId?: string
  status: 'connecting' | 'online' | 'offline'
  peersCount: number
}

export interface DaemonState {
  status: DaemonStatus
  machineId?: string
  bridgeId?: string
  studioUrl: string
  username?: string
  inboxes: InboxStatus[]
  inCount5m: number
  outboundPending: number
}

export interface LogLine {
  t: string      // HH:MM:SS
  src: string
  level: 'info' | 'ok' | 'warn' | 'err'
  msg: string
}
