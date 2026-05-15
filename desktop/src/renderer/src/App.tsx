import { useEffect, useState } from 'react'
import type { DaemonState } from '../../main/daemon/types'
import { Login } from './screens/Login'
import { InboxConfig } from './screens/InboxConfig'
import { Panel } from './screens/Panel'
import { Settings } from './screens/Settings'

type Screen = 'login' | 'inbox' | 'panel' | 'settings'

const IDLE_STATE: DaemonState = {
  status: 'idle',
  studioUrl: 'https://studio.laborster.com',
  username: '',
  inboxes: [],
  inCount5m: 0,
  outboundPending: 0,
}

export function App() {
  const [screen, setScreen] = useState<Screen>('login')
  const [daemonState, setDaemonState] = useState<DaemonState>(IDLE_STATE)
  const [savedInboxes, setSavedInboxes] = useState<Array<{ baseUrl: string; username: string }>>([])
  const [loading, setLoading] = useState(true)

  // Boot: load persisted state and decide starting screen
  useEffect(() => {
    const boot = async () => {
      const [creds, inboxes, state] = await Promise.all([
        window.bridge.getCreds(),
        window.bridge.getInboxes(),
        window.bridge.getState(),
      ])
      setSavedInboxes(inboxes)
      setDaemonState(s => ({
        ...s,
        studioUrl: creds.studioUrl,
        username: creds.username,
        machineId: creds.machineId,
        bridgeId: creds.bridgeId,
      }))

      if (!creds.hasToken) {
        setScreen('login')
      } else if (!creds.hasInboxes) {
        setScreen('inbox')
      } else {
        setScreen('panel')
        // Daemon auto-started by main process; sync displayed state
        if (state.status !== 'idle') setDaemonState(state)
      }
      setLoading(false)
    }
    boot()
  }, [])

  // Live state updates from main process
  useEffect(() => {
    const off = window.bridge.onStateChange(s => {
      setDaemonState(s)
      if (s.status === 'error401') setScreen('login')
    })
    return off
  }, [])

  const handleLoginSuccess = async () => {
    const inboxes = await window.bridge.getInboxes()
    setSavedInboxes(inboxes)
    if (inboxes.length === 0) {
      setScreen('inbox')
    } else {
      setScreen('panel')
      await window.bridge.start()
    }
  }

  const handleLaunch = async () => {
    setScreen('panel')
    await window.bridge.start()
  }

  const handleLogout = async () => {
    await window.bridge.logout()
    setDaemonState(IDLE_STATE)
    setScreen('login')
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--ink-4)', fontFamily: 'var(--f-mono)', fontSize: 11 }}>
        loading…
      </div>
    )
  }

  const is401 = daemonState.status === 'error401'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100vw', height: '100vh', overflow: 'hidden', background: 'var(--bg-deep)' }}>
      {/* macOS traffic-light spacer when titleBarStyle=hiddenInset */}
      {window.bridge.platform === 'darwin' && (
        <div style={{ height: 28, flexShrink: 0, WebkitAppRegion: 'drag' } as React.CSSProperties} />
      )}

      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        {screen === 'login' && (
          <Login
            initialUrl={daemonState.studioUrl}
            initialUsername={daemonState.username ?? ''}
            is401={is401}
            onSuccess={handleLoginSuccess}
          />
        )}
        {screen === 'inbox' && (
          <InboxConfig
            initial={savedInboxes}
            onLaunch={handleLaunch}
          />
        )}
        {screen === 'panel' && (
          <Panel
            state={daemonState}
            onNav={s => setScreen(s as Screen)}
          />
        )}
        {screen === 'settings' && (
          <Settings
            status={daemonState.status}
            studioUrl={daemonState.studioUrl}
            username={daemonState.username ?? ''}
            onNav={s => setScreen(s as Screen)}
            onLogout={handleLogout}
          />
        )}
      </div>
    </div>
  )
}
