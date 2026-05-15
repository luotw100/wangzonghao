import { contextBridge, ipcRenderer } from 'electron'
import type { DaemonState, LogLine, InboxClaim } from '../main/daemon/types'

export type BridgeAPI = typeof api

const api = {
  // Snapshot
  getState: (): Promise<DaemonState> => ipcRenderer.invoke('bridge:get-state'),
  getCreds: (): Promise<{
    studioUrl: string
    username: string
    machineId?: string
    bridgeId?: string
    hasToken: boolean
    hasInboxes: boolean
  }> => ipcRenderer.invoke('bridge:get-creds'),

  // Auth
  handshake: (opts: {
    studioUrl: string
    username: string
    password: string
  }): Promise<{ ok: true; machineId: string; bridgeId: string } | { ok: false; error: string }> =>
    ipcRenderer.invoke('bridge:handshake', opts),
  logout: (): Promise<void> => ipcRenderer.invoke('bridge:logout'),

  // Inbox config
  getInboxes: (): Promise<Array<{ baseUrl: string; username: string }>> =>
    ipcRenderer.invoke('bridge:get-inboxes'),
  saveInboxes: (claims: InboxClaim[]): Promise<{ ok: boolean }> =>
    ipcRenderer.invoke('bridge:save-inboxes', claims),

  // Daemon control
  start: (): Promise<void> => ipcRenderer.invoke('bridge:start'),
  stop: (): Promise<void> => ipcRenderer.invoke('bridge:stop'),

  // Actions
  openStudio: (): Promise<void> => ipcRenderer.invoke('bridge:open-studio'),

  // Event listeners (main → renderer push)
  onStateChange: (cb: (state: DaemonState) => void) => {
    const handler = (_: Electron.IpcRendererEvent, s: DaemonState) => cb(s)
    ipcRenderer.on('bridge:state-change', handler)
    return () => ipcRenderer.off('bridge:state-change', handler)
  },
  onLog: (cb: (line: LogLine) => void) => {
    const handler = (_: Electron.IpcRendererEvent, l: LogLine) => cb(l)
    ipcRenderer.on('bridge:log', handler)
    return () => ipcRenderer.off('bridge:log', handler)
  },
}

contextBridge.exposeInMainWorld('bridge', api)

// Type declaration merged into the renderer window global
declare global {
  interface Window {
    bridge: BridgeAPI
  }
}
