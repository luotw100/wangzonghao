import { useState } from 'react'
import { Field, inputStyle, Btn, LabMark } from '../components/shared'

interface Props {
  initialUrl: string
  initialUsername: string
  sessionExpired: boolean
  onSuccess: () => void
}

export function Login({ initialUrl, initialUsername, sessionExpired, onSuccess }: Props) {
  const [studioUrl, setStudioUrl] = useState(initialUrl)
  const [username, setUsername] = useState(initialUsername)
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!studioUrl || !username || !password || busy) return
    setBusy(true)
    setError(null)
    const res = await window.bridge.login({ studioUrl, username, password })
    setBusy(false)
    if (res.ok) onSuccess()
    else setError(res.error)
  }

  return (
    <div style={{ display: 'flex', width: '100%', height: '100%', minHeight: 0 }}>
      <div style={{ width: 360, flexShrink: 0, padding: '36px 36px', borderRight: '1px solid var(--line-subtle)', background: 'linear-gradient(135deg,var(--bg-deep) 0%,var(--bg-base) 100%)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <LabMark />
          <span style={{ fontFamily: 'var(--f-serif)', fontSize: 15, fontWeight: 500 }}>Laborster</span>
          <span style={{ padding: '2px 7px', borderRadius: 4, font: '500 10.5px/1 var(--f-mono)', letterSpacing: '0.06em', textTransform: 'uppercase', border: '1px solid var(--line)', color: 'var(--ink-2)', background: 'var(--bg-sunken)' }}>Bridge</span>
        </div>
        <div style={{ marginTop: 'auto' }}>
          <h1 style={{ fontFamily: 'var(--f-serif)', fontSize: 28, lineHeight: 1.15, margin: '0 0 14px', letterSpacing: '-0.025em', fontWeight: 400 }}>
            登录 <span style={{ color: 'var(--brass)' }}>Studio</span><br />唤醒本机 daemon。
          </h1>
          <p style={{ color: 'var(--ink-3)', fontSize: 12.5, lineHeight: 1.7, margin: 0 }}>
            登录一次换取 session token，之后长期复用，重启不用再登。密码不写磁盘。
          </p>
        </div>
      </div>

      <div style={{ flex: 1, padding: '40px 44px', display: 'flex', flexDirection: 'column' }}>
        {sessionExpired && !error && (
          <div style={{ padding: '10px 12px', background: 'oklch(0.62 0.15 22/0.10)', border: '1px solid oklch(0.62 0.15 22/0.35)', borderRadius: 8, marginBottom: 18, fontSize: 12 }}>
            <div style={{ fontWeight: 600, color: 'var(--danger)', marginBottom: 2 }}>session 已失效</div>
            <div style={{ font: '11px/1.5 var(--f-mono)', color: 'var(--ink-2)' }}>token 被撤销或过期，请重新登录。</div>
          </div>
        )}
        {error && (
          <div style={{ padding: '10px 12px', background: 'oklch(0.62 0.15 22/0.10)', border: '1px solid oklch(0.62 0.15 22/0.35)', borderRadius: 8, marginBottom: 18, fontSize: 12, color: 'var(--danger)' }}>
            {error}
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 380 }}>
          <Field label="STUDIO URL" hint="本地联调用 http://localhost:23457">
            <input style={inputStyle} value={studioUrl} onChange={e => setStudioUrl(e.target.value)} disabled={busy} />
          </Field>
          <Field label="USERNAME">
            <input style={inputStyle} value={username} onChange={e => setUsername(e.target.value)} disabled={busy} autoFocus />
          </Field>
          <Field label="PASSWORD">
            <input style={inputStyle} type="password" value={password} disabled={busy}
              onChange={e => setPassword(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') submit() }} placeholder="········" />
          </Field>
        </div>

        <div style={{ marginTop: 'auto', paddingTop: 28, display: 'flex', justifyContent: 'flex-end', gap: 8, maxWidth: 380 }}>
          <Btn primary disabled={busy || !username || !password} onClick={submit}>
            {busy ? '登录中…' : '登录 →'}
          </Btn>
        </div>
      </div>
    </div>
  )
}
