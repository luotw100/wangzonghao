import { useState } from 'react'
import { Field, inputStyle, Btn, LabMark } from '../components/shared'

interface Props {
  initialUrl: string
  initialUsername: string
  is401: boolean
  onSuccess: () => void
}

export function Login({ initialUrl, initialUsername, is401, onSuccess }: Props) {
  const [studioUrl, setStudioUrl] = useState(initialUrl)
  const [username, setUsername] = useState(initialUsername)
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!username || !password || submitting) return
    setSubmitting(true)
    setError(null)
    const res = await window.bridge.handshake({ studioUrl, username, password })
    setSubmitting(false)
    if (res.ok) {
      onSuccess()
    } else {
      setError(res.error.includes('401') ? '账号或密码错误' : res.error)
    }
  }

  return (
    <div style={{ display: 'flex', width: '100%', height: '100%', minHeight: 0 }}>
      {/* Left panel */}
      <div style={{ width: 400, flexShrink: 0, padding: '32px 36px', borderRight: '1px solid var(--line-subtle)', background: 'linear-gradient(135deg,var(--bg-deep) 0%,var(--bg-base) 100%)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <LabMark />
          <span style={{ fontFamily: 'var(--f-serif)', fontSize: 15, fontWeight: 500 }}>Laborster</span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '2px 7px', borderRadius: 4, font: '500 10.5px/1 var(--f-mono)', letterSpacing: '0.06em', textTransform: 'uppercase', border: '1px solid var(--line)', color: 'var(--ink-2)', background: 'var(--bg-sunken)' }}>Bridge</span>
        </div>
        <div style={{ marginTop: 'auto' }}>
          <div style={{ font: '500 10px/1 var(--f-mono)', letterSpacing: '0.18em', textTransform: 'uppercase', color: 'var(--ink-3)', marginBottom: 10 }}>
            {is401 ? 'SESSION 失效 · RE-AUTH' : 'FIRST RUN · 本机首次启动'}
          </div>
          <h1 style={{ fontFamily: 'var(--f-serif)', fontSize: 30, lineHeight: 1.1, margin: '0 0 14px', letterSpacing: '-0.025em', fontWeight: 400 }}>
            守住主播 PC，<br />一台机器一个 <span style={{ color: 'var(--brass)' }}>daemon</span>。
          </h1>
          <p style={{ color: 'var(--ink-3)', fontSize: 12.5, lineHeight: 1.7, margin: 0 }}>
            Bridge 没有长期凭据。每次握手用 Studio 账号换取 session token，按 (account, machine) 自动注册。密码不落磁盘。
          </p>
        </div>
      </div>

      {/* Right panel */}
      <div style={{ flex: 1, padding: '36px 40px', display: 'flex', flexDirection: 'column' }}>
        <div style={{ font: '500 10px/1 var(--f-mono)', letterSpacing: '0.18em', textTransform: 'uppercase', color: 'var(--ink-3)' }}>
          {submitting ? 'STEP 2 · 握手中' : is401 ? 'RE-AUTH · 重新握手' : 'STEP 1 · 登录 STUDIO'}
        </div>
        <h2 style={{ fontFamily: 'var(--f-serif)', fontSize: 22, margin: '6px 0 22px', fontWeight: 400, letterSpacing: '-0.02em' }}>
          {submitting ? 'POST /api/bridge/handshake' : is401 ? 'session 已失效，请重新登录' : '用 Studio 账号唤醒本机 daemon'}
        </h2>

        {is401 && !error && (
          <div style={{ padding: '10px 12px', background: 'oklch(0.62 0.15 22/0.10)', border: '1px solid oklch(0.62 0.15 22/0.35)', borderRadius: 8, marginBottom: 16, fontSize: 12, display: 'flex', gap: 10 }}>
            <span style={{ color: 'var(--danger)' }}>✕</span>
            <div>
              <div style={{ fontWeight: 600, color: 'var(--danger)', marginBottom: 2 }}>401 · session token revoked</div>
              <div style={{ font: '11px/1.5 var(--f-mono)', color: 'var(--ink-2)' }}>此 Bridge 被 admin 撤销，或被同名 machine 顶掉。</div>
            </div>
          </div>
        )}

        {error && (
          <div style={{ padding: '10px 12px', background: 'oklch(0.62 0.15 22/0.10)', border: '1px solid oklch(0.62 0.15 22/0.35)', borderRadius: 8, marginBottom: 16, fontSize: 12, color: 'var(--danger)' }}>
            {error}
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <Field label="STUDIO URL" hint="本地联调用 http://localhost:23457">
            <input style={inputStyle} value={studioUrl} onChange={e => setStudioUrl(e.target.value)} disabled={submitting} />
          </Field>
          <Field label="USERNAME">
            <input style={inputStyle} value={username} onChange={e => setUsername(e.target.value)} disabled={submitting} autoFocus />
          </Field>
          <Field label="PASSWORD">
            <input style={inputStyle} type="password" value={password} onChange={e => setPassword(e.target.value)} disabled={submitting} placeholder="········"
              onKeyDown={e => { if (e.key === 'Enter') submit() }} />
          </Field>
        </div>

        {submitting && (
          <div style={{ marginTop: 14, font: '11px/1 var(--f-mono)', color: 'var(--ink-3)', display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ width: 6, height: 6, borderRadius: 99, background: 'var(--live)', animation: 'lampPulse 2.4s ease-in-out infinite' }} />
            正在握手…
          </div>
        )}

        <div style={{ marginTop: 'auto', paddingTop: 24, display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <Btn sm onClick={() => window.bridge.openStudio()}>打开 Studio ↗</Btn>
          <Btn primary disabled={submitting || !username || !password} onClick={submit}>
            {submitting ? '握手中…' : '握手并启动 →'}
          </Btn>
        </div>
      </div>
    </div>
  )
}
