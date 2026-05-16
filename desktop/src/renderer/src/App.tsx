import { useEffect, useState } from 'react'
import type { DaemonState } from '../../main/daemon/types'
import { Login } from './screens/Login'
import { Channels } from './screens/Channels'

const IDLE: DaemonState = {
  status: 'idle',
  studioUrl: 'https://studio.laborster.com',
  username: '',
  channels: [],
  inCount5m: 0,
  outboundPending: 0,
}

export function App() {
  const [booted, setBooted] = useState(false)
  const [hasToken, setHasToken] = useState(false)
  const [state, setState] = useState<DaemonState>(IDLE)
  const [channels, setChannels] = useState<Array<{ baseUrl: string; username: string }>>([])

  useEffect(() => {
    window.bridge.bootstrap().then(b => {
      setHasToken(b.hasToken)
      setChannels(b.channels)
      setState(s => ({ ...s, studioUrl: b.studioUrl, username: b.username, ...b.state }))
      setBooted(true)
    })
  }, [])

  useEffect(() => {
    return window.bridge.onState(s => {
      setState(s)
      if (s.status === 'error401') setHasToken(false)
    })
  }, [])

  const onLoggedIn = async () => {
    const c = await window.bridge.getChannels()
    setChannels(c)
    setHasToken(true)
  }

  const onLogout = async () => {
    await window.bridge.logout()
    setState(IDLE)
    setHasToken(false)
  }

  if (!booted) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', color: 'var(--ink-4)', font: '11px var(--f-mono)' }}>
        loading…
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100vw', height: '100vh', overflow: 'hidden', background: 'var(--bg-deep)' }}>
      {window.bridge.platform === 'darwin' && (
        <div style={{ height: 28, flexShrink: 0, WebkitAppRegion: 'drag' } as React.CSSProperties} />
      )}
      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        {!hasToken ? (
          <Login
            initialUrl={state.studioUrl}
            initialUsername={state.username ?? ''}
            sessionExpired={state.status === 'error401'}
            onSuccess={onLoggedIn}
          />
        ) : (
          <Channels
            state={state}
            savedChannels={channels}
            onSaved={setChannels}
            onLogout={onLogout}
          />
        )}
      </div>
    </div>
  )
}
