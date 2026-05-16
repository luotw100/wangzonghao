import { contextBridge, ipcRenderer } from 'electron'
import type { DaemonState, LogLine, Channel } from '../main/daemon/types'

export type BridgeAPI = typeof api

const api = {
  platform: process.platform,

  bootstrap: (): Promise<{
    studioUrl: string
    username: string
    hasToken: boolean
    channels: Array<{ baseUrl: string; username: string }>
    state: DaemonState
  }> => ipcRenderer.invoke('bridge:bootstrap'),

  login: (opts: { studioUrl: string; username: string; password: string }):
    Promise<{ ok: true } | { ok: false; error: string }> =>
    ipcRenderer.invoke('bridge:login', opts),

  logout: (): Promise<void> => ipcRenderer.invoke('bridge:logout'),

  getChannels: (): Promise<Array<{ baseUrl: string; username: string }>> =>
    ipcRenderer.invoke('bridge:get-channels'),

  saveChannels: (channels: Channel[]): Promise<{ ok: boolean }> =>
    ipcRenderer.invoke('bridge:save-channels', channels),

  stop: (): Promise<void> => ipcRenderer.invoke('bridge:stop'),
  openStudio: (): Promise<void> => ipcRenderer.invoke('bridge:open-studio'),

  onState: (cb: (s: DaemonState) => void) => {
    const h = (_: Electron.IpcRendererEvent, s: DaemonState) => cb(s)
    ipcRenderer.on('bridge:state', h)
    return () => ipcRenderer.off('bridge:state', h)
  },
  onLog: (cb: (l: LogLine) => void) => {
    const h = (_: Electron.IpcRendererEvent, l: LogLine) => cb(l)
    ipcRenderer.on('bridge:log', h)
    return () => ipcRenderer.off('bridge:log', h)
  },
}

contextBridge.exposeInMainWorld('bridge', api)

declare global {
  interface Window {
    bridge: BridgeAPI
  }
}
