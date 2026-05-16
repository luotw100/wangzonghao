import { app, BrowserWindow, ipcMain, shell, Tray, Menu, nativeImage } from 'electron'
import { join } from 'path'
import { Store } from './state'
import { BridgeRuntime } from './daemon/runtime'
import { StudioClient } from './daemon/studio-client'
import type { DaemonState, LogLine, Channel } from './daemon/types'

const isDev = !app.isPackaged

let win: BrowserWindow | null = null
let tray: Tray | null = null
let store: Store
let runtime: BridgeRuntime | null = null
let currentState: DaemonState | null = null
let isQuitting = false

// ── Renderer push ────────────────────────────────────────────────────────────

function send(channel: string, payload: unknown): void {
  win?.webContents.send(channel, payload)
}

function emitDaemon(event: 'status' | 'log', payload: DaemonState | LogLine): void {
  if (event === 'status') {
    currentState = payload as DaemonState
    send('bridge:state', payload)
    updateTray()
  } else {
    send('bridge:log', payload)
  }
}

function idleState(status: DaemonState['status']): DaemonState {
  return {
    status,
    studioUrl: store.studioUrl,
    username: store.username,
    machineId: store.machineId,
    bridgeId: store.bridgeId,
    channels: [],
    inCount5m: 0,
    outboundPending: 0,
  }
}

// ── Tray ─────────────────────────────────────────────────────────────────────

function updateTray(): void {
  const label = currentState
    ? { online: '在线', connecting: '连接中…', offline: '离线', error401: '需重新登录', idle: '未启动' }[currentState.status]
    : '未启动'
  tray?.setToolTip(`Laborster Bridge · ${label}`)
  tray?.setContextMenu(Menu.buildFromTemplate([
    { label: `Laborster Bridge · ${label}`, enabled: false },
    { type: 'separator' },
    { label: '打开主窗口', click: () => { win?.show(); win?.focus() } },
    { label: '停止 daemon', enabled: !!runtime, click: () => stopDaemon() },
    { type: 'separator' },
    { label: '退出', click: () => app.quit() },
  ]))
}

// ── Window ───────────────────────────────────────────────────────────────────

function createWindow(): void {
  win = new BrowserWindow({
    width: 920, height: 620, minWidth: 760, minHeight: 520,
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    backgroundColor: '#29241a',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  win.on('close', (e) => {
    if (!isQuitting) { e.preventDefault(); win?.hide() }
  })
  if (isDev) win.loadURL('http://localhost:5173')
  else win.loadFile(join(__dirname, '../renderer/index.html'))
}

// ── Daemon lifecycle ──────────────────────────────────────────────────────────

async function startDaemon(): Promise<void> {
  if (runtime) return
  if (!store.hasToken() || !store.hasChannels()) return

  const studio = new StudioClient(store.studioUrl, () => store.token)
  runtime = new BridgeRuntime(
    studio,
    store.getChannels(),
    join(app.getPath('userData'), 'data'),
    emitDaemon,
    () => ({
      studioUrl: store.studioUrl,
      username: store.username,
      machineId: store.machineId,
      bridgeId: store.bridgeId,
    }),
  )
  await runtime.run({
    onAuthError: () => {
      store.clearToken()
      emitDaemon('status', idleState('error401'))
    },
  })
}

function stopDaemon(): void {
  runtime?.stop()
  runtime = null
  emitDaemon('status', idleState('idle'))
}

async function restartDaemon(): Promise<void> {
  if (runtime) { runtime.stop(); runtime = null }
  await startDaemon()
}

// ── IPC ───────────────────────────────────────────────────────────────────────

function registerIpc(): void {
  ipcMain.handle('bridge:bootstrap', () => ({
    studioUrl: store.studioUrl,
    username: store.username,
    hasToken: store.hasToken(),
    channels: store.getChannelViews(),
    state: currentState ?? idleState(store.hasToken() ? 'idle' : 'idle'),
  }))

  ipcMain.handle('bridge:login', async (_e, opts: { studioUrl: string; username: string; password: string }) => {
    const studio = new StudioClient(opts.studioUrl, () => null)
    try {
      const hs = await studio.handshake({
        username: opts.username,
        password: opts.password,
        machineId: store.machineId,
      })
      store.setSession({
        studioUrl: opts.studioUrl,
        username: opts.username,
        token: hs.token,
        machineId: hs.machineId,
        bridgeId: hs.bridgeId,
      })
      if (store.hasChannels()) await startDaemon()
      return { ok: true }
    } catch (err: any) {
      const msg = String(err).includes('401') ? '账号或密码错误' : String(err?.message ?? err)
      return { ok: false, error: msg }
    }
  })

  ipcMain.handle('bridge:logout', () => {
    stopDaemon()
    store.clearToken()
    emitDaemon('status', idleState('idle'))
  })

  ipcMain.handle('bridge:get-channels', () => store.getChannelViews())

  ipcMain.handle('bridge:save-channels', async (_e, channels: Channel[]) => {
    store.saveChannels(channels)
    await restartDaemon()
    return { ok: true }
  })

  ipcMain.handle('bridge:stop', () => stopDaemon())
  ipcMain.handle('bridge:open-studio', () => shell.openExternal(store.studioUrl))
}

// ── App lifecycle ─────────────────────────────────────────────────────────────

app.whenReady().then(async () => {
  store = new Store(app.getPath('userData'))
  Menu.setApplicationMenu(null)
  createWindow()
  registerIpc()

  try {
    tray = new Tray(nativeImage.createFromPath(join(__dirname, '../../resources/tray-icon.png')))
  } catch {
    tray = new Tray(nativeImage.createEmpty())
  }
  updateTray()
  tray.on('double-click', () => { win?.show(); win?.focus() })

  // Token is reused across restarts — cold start needs no password.
  if (store.hasToken() && store.hasChannels()) await startDaemon()
})

app.on('before-quit', () => { isQuitting = true; stopDaemon() })
app.on('window-all-closed', () => {})
app.on('activate', () => win?.show())
