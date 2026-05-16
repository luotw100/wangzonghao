import { useEffect, useRef, useState } from 'react'
import type { Channel, DaemonState, LogLine } from '../../../main/daemon/types'
import { Field, inputStyle, Btn, LabMark, StatusChip } from '../components/shared'

interface Props {
  state: DaemonState
  savedChannels: Array<{ baseUrl: string; username: string }>
  onSaved: (c: Array<{ baseUrl: string; username: string }>) => void
  onLogout: () => void
}

interface Row extends Channel { id: number }
let _id = 1

export function Channels({ state, savedChannels, onSaved, onLogout }: Props) {
  const [rows, setRows] = useState<Row[]>(
    savedChannels.length
      ? savedChannels.map(c => ({ id: _id++, baseUrl: c.baseUrl, username: c.username, password: '' }))
      : [{ id: _id++, baseUrl: 'https://chat.laborster.com', username: '', password: '' }],
  )
  const [saving, setSaving] = useState(false)
  const [logs, setLogs] = useState<LogLine[]>([])
  const logEnd = useRef<HTMLDivElement>(null)

  useEffect(() => window.bridge.onLog(l => setLogs(p => [...p.slice(-200), l])), [])
  useEffect(() => { logEnd.current?.scrollIntoView() }, [logs])

  const addRow = () => setRows(r => [...r, { id: _id++, baseUrl: 'https://chat.laborster.com', username: '', password: '' }])
  const removeRow = (id: number) => setRows(r => r.filter(x => x.id !== id))
  const update = (id: number, k: keyof Channel, v: string) =>
    setRows(r => r.map(x => x.id === id ? { ...x, [k]: v } : x))

  const valid = rows.length > 0 && rows.every(r => r.baseUrl && r.username && r.password)

  const save = async () => {
    if (!valid || saving) return
    setSaving(true)
    await window.bridge.saveChannels(rows.map(({ baseUrl, username, password }) => ({ baseUrl, username, password })))
    onSaved(rows.map(r => ({ baseUrl: r.baseUrl, username: r.username })))
    setRows(r => r.map(x => ({ ...x, password: '' })))
    setSaving(false)
  }

  const statusOf = (baseUrl: string, username: string) =>
    state.channels.find(c => c.baseUrl === baseUrl && c.handle === username)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%', minHeight: 0 }}>
      <header style={{ height: 52, flexShrink: 0, borderBottom: '1px solid var(--line-subtle)', display: 'flex', alignItems: 'center', padding: '0 22px', gap: 12 }}>
        <LabMark />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>Inbox · Channels</div>
          <div style={{ font: '11px/1 var(--f-mono)', color: 'var(--ink-4)', marginTop: 3 }}>
            {state.username || '—'} · {state.studioUrl}
          </div>
        </div>
        <StatusChip status={state.status} />
        <Btn sm onClick={() => window.bridge.openStudio()}>打开 Studio ↗</Btn>
        <Btn sm danger onClick={onLogout}>退出登录</Btn>
      </header>

      <main style={{ flex: 1, overflow: 'auto', padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
          <div style={{ font: '500 10px/1 var(--f-mono)', letterSpacing: '0.18em', textTransform: 'uppercase', color: 'var(--ink-3)' }}>
            {rows.length} CHANNEL · 收 {state.inCount5m}/5m · 待发 {state.outboundPending}
          </div>
          <Btn sm onClick={addRow} disabled={rows.length >= 8}>+ 加 channel</Btn>
        </div>

        {rows.map(row => {
          const st = statusOf(row.baseUrl, row.username)
          return (
            <div key={row.id} style={{ background: 'var(--bg-base)', border: '1px solid var(--line-subtle)', borderRadius: 'var(--r-lg)', padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ width: 7, height: 7, borderRadius: 99, background: st?.online ? 'var(--live)' : 'var(--ink-4)' }} />
                <span style={{ font: '11px/1 var(--f-mono)', color: 'var(--ink-3)' }}>
                  chat · {st?.online ? `在线 · ${st.peersCount} 会话` : '未连接'}
                </span>
                <div style={{ flex: 1 }} />
                <Btn danger sm onClick={() => removeRow(row.id)}>移除</Btn>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: 10 }}>
                <Field label="CHAT BASE URL">
                  <input style={inputStyle} value={row.baseUrl} onChange={e => update(row.id, 'baseUrl', e.target.value)} placeholder="https://chat.laborster.com" />
                </Field>
                <Field label="USERNAME">
                  <input style={inputStyle} value={row.username} onChange={e => update(row.id, 'username', e.target.value)} />
                </Field>
                <Field label="PASSWORD">
                  <input style={inputStyle} type="password" value={row.password} onChange={e => update(row.id, 'password', e.target.value)} placeholder="········" />
                </Field>
              </div>
            </div>
          )
        })}

        {state.lastError && (
          <div style={{ color: 'var(--danger)', font: '11px/1.5 var(--f-mono)', padding: '8px 10px', background: 'oklch(0.62 0.15 22/0.10)', border: '1px solid oklch(0.62 0.15 22/0.30)', borderRadius: 8 }}>
            {state.lastError}
          </div>
        )}

        <div style={{ marginTop: 8, background: 'var(--bg-sunken)', border: '1px solid var(--line-subtle)', borderRadius: 8, padding: '10px 12px', height: 160, overflow: 'auto', font: '11px/1.6 var(--f-mono)' }}>
          {logs.length === 0 && <span style={{ color: 'var(--ink-4)' }}>daemon 日志…</span>}
          {logs.map((l, i) => (
            <div key={i} style={{ color: l.level === 'err' ? 'var(--danger)' : l.level === 'warn' ? 'var(--warn)' : l.level === 'ok' ? 'var(--ok)' : 'var(--ink-3)' }}>
              <span style={{ color: 'var(--ink-4)' }}>{l.t}</span> [{l.src}] {l.msg}
            </div>
          ))}
          <div ref={logEnd} />
        </div>
      </main>

      <footer style={{ height: 56, flexShrink: 0, borderTop: '1px solid var(--line-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 22px' }}>
        <span style={{ font: '11px/1 var(--f-mono)', color: 'var(--ink-3)' }}>
          保存后 daemon 重启并向 Studio 注册 channel；接管与回复策略在 Studio 配置
        </span>
        <Btn primary disabled={!valid || saving} onClick={save}>
          {saving ? '保存中…' : '保存并重启 daemon →'}
        </Btn>
      </footer>
    </div>
  )
}
