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

/** A channel = one chat-platform account this machine logs into. */
export interface Channel {
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
export type DaemonStatus = 'idle' | 'connecting' | 'online' | 'offline' | 'error401'

export interface ChannelStatus {
  inboxId: string | null
  handle: string
  baseUrl: string
  platformSelfId?: string
  online: boolean
  peersCount: number
}

export interface DaemonState {
  status: DaemonStatus
  studioUrl: string
  username?: string
  machineId?: string
  bridgeId?: string
  channels: ChannelStatus[]
  inCount5m: number
  outboundPending: number
  lastError?: string
}

export interface LogLine {
  t: string      // HH:MM:SS
  src: string
  level: 'info' | 'ok' | 'warn' | 'err'
  msg: string
}
