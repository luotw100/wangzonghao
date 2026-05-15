import { app, BrowserWindow, ipcMain, shell, Tray, Menu, nativeImage } from 'electron'
import { join } from 'path'
import { CredentialStore } from './state'
import { BridgeRuntime } from './daemon/runtime'
import { StudioClient } from './daemon/studio-client'
import type { DaemonState, LogLine, InboxClaim } from './daemon/types'

const isDev = !app.isPackaged

let win: BrowserWindow | null = null
let tray: Tray | null = null
let creds: CredentialStore
let runtime: BridgeRuntime | null = null
let currentState: DaemonState | null = null

// ── Renderer communication ──────────────────────────────────────────────────

function sendToRenderer(channel: string, payload: unknown): void {
  win?.webContents.send(channel, payload)
}

function emitDaemon(event: 'status' | 'log', payload: DaemonState | LogLine): void {
  if (event === 'status') {
    currentState = payload as DaemonState
    sendToRenderer('bridge:state-change', payload)
    updateTray(payload as DaemonState)
  } else {
    sendToRenderer('bridge:log', payload)
  }
}

// ── Tray ───────────────────────────────────────────────────────────────────

function buildTrayMenu(state: DaemonState | null): Menu {
  const statusLabel = state
    ? { online: '在线', degraded: '降级', error401: '需重新登录', offline: '离线', connecting: '连接中…', idle: '未启动' }[state.status]
    : '未启动'

  return Menu.buildFromTemplate([
    { label: `Laborster Bridge · ${statusLabel}`, enabled: false },
    { type: 'separator' },
    { label: '打开主窗口', click: () => { win?.show(); win?.focus() } },
    { type: 'separator' },
    {
      label: '停止 daemon',
      enabled: !!runtime,
      click: () => stopDaemon(),
    },
    { type: 'separator' },
    { label: '退出', click: () => { app.quit() } },
  ])
}

function updateTray(state: DaemonState | null): void {
  tray?.setContextMenu(buildTrayMenu(state))
  if (state) {
    const tooltip = `Laborster Bridge · ${state.status}`
    tray?.setToolTip(tooltip)
  }
}

// ── Window ─────────────────────────────────────────────────────────────────

function createWindow(): void {
  win = new BrowserWindow({
    width: 960,
    height: 640,
    minWidth: 960,
    minHeight: 640,
    maxWidth: 960,
    maxHeight: 640,
    resizable: false,
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    backgroundColor: '#29241a',  // close to --bg-deep
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  // Close → hide to tray instead of quit
  win.on('close', (e) => {
    if (!app.isQuitting) {
      e.preventDefault()
      win?.hide()
    }
  })

  if (isDev) {
    win.loadURL('http://localhost:5173')
  } else {
    win.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

// ── Daemon lifecycle ────────────────────────────────────────────────────────

async function startDaemon(): Promise<void> {
  if (runtime) return
  if (!creds.hasToken() || !creds.hasInboxes()) return

  const studio = new StudioClient(creds.studioUrl, () => creds.token)
  const claims = creds.getInboxClaims()

  runtime = new BridgeRuntime(
    studio,
    claims,
    join(app.getPath('userData'), 'data'),
    emitDaemon,
    () => ({
      status: 'online',
      machineId: creds.machineId,
      bridgeId: creds.bridgeId,
      studioUrl: creds.studioUrl,
      username: creds.username,
    }),
  )

  await runtime.run({
    handshakeToken: creds.token,
    machineId: creds.machineId,
    onAuthError: () => {
      creds.clearToken()
      sendToRenderer('bridge:state-change', buildIdleState('error401'))
    },
    onCursorInit: (_cursor) => {},
  })
}

function stopDaemon(): void {
  runtime?.stop()
  runtime = null
  sendToRenderer('bridge:state-change', buildIdleState('idle'))
}

function buildIdleState(status: DaemonState['status']): DaemonState {
  return {
    status,
    studioUrl: creds.studioUrl,
    username: creds.username,
    machineId: creds.machineId,
    bridgeId: creds.bridgeId,
    inboxes: [],
    inCount5m: 0,
    outboundPending: 0,
  }
}

// ── IPC handlers ───────────────────────────────────────────────────────────

function registerIpc(): void {
  // Renderer requests current state snapshot
  ipcMain.handle('bridge:get-state', () => currentState ?? buildIdleState(creds.hasToken() ? 'idle' : 'idle'))

  // Handshake (login)
  ipcMain.handle('bridge:handshake', async (_e, opts: {
    studioUrl: string
    username: string
    password: string
  }) => {
    const studio = new StudioClient(opts.studioUrl, () => opts.password)
    try {
      // We need all currently-configured inboxes for handshake
      // If none yet, handshake with empty list to get token
      const claims = creds.getInboxClaims()
      const tempAdapters: Array<{ platform: string; platformSelfId: string }> = []
      // Attempt login per claim to get selfIds
      for (const claim of claims) {
        try {
          const res = await fetch(`${claim.baseUrl}/api/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: claim.username, password: claim.password }),
          })
          if (res.ok) {
            const data: { account_id: string } = await res.json()
            tempAdapters.push({ platform: 'chat', platformSelfId: data.account_id })
          }
        } catch {}
      }

      const hs = await studio.handshake({
        username: opts.username,
        password: opts.password,
        machineId: creds.machineId,
        inboxes: tempAdapters,
      })
      creds.setHandshakeResult({
        studioUrl: opts.studioUrl,
        username: opts.username,
        token: hs.token,
        machineId: hs.machineId,
        bridgeId: hs.bridgeId,
      })
      return { ok: true, machineId: hs.machineId, bridgeId: hs.bridgeId }
    } catch (err: any) {
      return { ok: false, error: String(err) }
    }
  })

  // Save inbox config
  ipcMain.handle('bridge:save-inboxes', async (_e, claims: InboxClaim[]) => {
    creds.saveInboxes(claims)
    return { ok: true }
  })

  // Get saved inboxes (display, no passwords)
  ipcMain.handle('bridge:get-inboxes', () => {
    return creds.getInboxClaims().map(c => ({ baseUrl: c.baseUrl, username: c.username }))
  })

  // Start daemon
  ipcMain.handle('bridge:start', async () => {
    await startDaemon()
  })

  // Stop daemon
  ipcMain.handle('bridge:stop', () => {
    stopDaemon()
  })

  // Open Studio in browser
  ipcMain.handle('bridge:open-studio', () => {
    shell.openExternal(creds.studioUrl)
  })

  // Clear auth (logout)
  ipcMain.handle('bridge:logout', () => {
    stopDaemon()
    creds.clearToken()
    sendToRenderer('bridge:state-change', buildIdleState('idle'))
  })

  // Get credential info for UI (no sensitive data)
  ipcMain.handle('bridge:get-creds', () => ({
    studioUrl: creds.studioUrl,
    username: creds.username,
    machineId: creds.machineId,
    bridgeId: creds.bridgeId,
    hasToken: creds.hasToken(),
    hasInboxes: creds.hasInboxes(),
  }))
}

// ── App lifecycle ──────────────────────────────────────────────────────────

app.whenReady().then(() => {
  creds = new CredentialStore(app.getPath('userData'))

  createWindow()
  registerIpc()

  // Tray
  const iconPath = join(__dirname, '../../resources/tray-icon.png')
  try {
    tray = new Tray(nativeImage.createFromPath(iconPath))
  } catch {
    // Fallback: empty 16x16 icon if asset missing during dev
    tray = new Tray(nativeImage.createEmpty())
  }
  tray.setToolTip('Laborster Bridge')
  tray.setContextMenu(buildTrayMenu(null))
  tray.on('double-click', () => { win?.show(); win?.focus() })

  // Auto-start daemon if credentials ready
  if (creds.hasToken() && creds.hasInboxes()) {
    startDaemon()
  }
})

app.on('before-quit', () => {
  ;(app as any).isQuitting = true
  stopDaemon()
})

app.on('window-all-closed', () => {
  // Keep app running in tray on all platforms
})

app.on('activate', () => {
  win?.show()
})
