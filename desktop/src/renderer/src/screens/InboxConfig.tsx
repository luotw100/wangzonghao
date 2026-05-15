import { useState } from 'react'
import type { InboxClaim } from '../../../main/daemon/types'
import { Field, inputStyle, Btn, LabMark } from '../components/shared'

interface Props {
  initial: Array<{ baseUrl: string; username: string }>
  onLaunch: (claims: InboxClaim[]) => void
}

interface FormRow extends InboxClaim {
  id: number
}

let _nextId = 1

export function InboxConfig({ initial, onLaunch }: Props) {
  const [rows, setRows] = useState<FormRow[]>(
    initial.length > 0
      ? initial.map(i => ({ id: _nextId++, baseUrl: i.baseUrl, username: i.username, password: '' }))
      : [{ id: _nextId++, baseUrl: 'https://chat.laborster.com', username: '', password: '' }],
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const addRow = () => setRows(r => [...r, { id: _nextId++, baseUrl: 'https://chat.laborster.com', username: '', password: '' }])
  const removeRow = (id: number) => setRows(r => r.filter(row => row.id !== id))
  const update = (id: number, key: keyof InboxClaim, val: string) =>
    setRows(r => r.map(row => row.id === id ? { ...row, [key]: val } : row))

  const valid = rows.every(r => r.baseUrl && r.username && r.password) && rows.length > 0

  const launch = async () => {
    if (!valid || saving) return
    setSaving(true)
    setError(null)
    const claims: InboxClaim[] = rows.map(({ baseUrl, username, password }) => ({ baseUrl, username, password }))
    const res = await window.bridge.saveInboxes(claims)
    if (res.ok) {
      onLaunch(claims)
    } else {
      setError('保存失败')
      setSaving(false)
    }
  }

  return (
    <div style={{ display: 'flex', width: '100%', height: '100%', minHeight: 0 }}>
      {/* Slim rail placeholder */}
      <aside style={{ width: 64, flexShrink: 0, background: 'var(--bg-base)', borderRight: '1px solid var(--line-subtle)', display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '14px 0' }}>
        <LabMark style={{ marginBottom: 18 }} />
        <div style={{ width: 44, height: 44, borderRadius: 10, background: 'var(--brass-soft)', color: 'var(--brass)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'var(--f-serif)', fontSize: 16 }}>◇</div>
      </aside>

      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <header style={{ height: 48, flexShrink: 0, borderBottom: '1px solid var(--line-subtle)', display: 'flex', alignItems: 'center', padding: '0 22px', gap: 12 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>Inbox 配置</div>
            <div style={{ font: '11px/1 var(--f-mono)', color: 'var(--ink-4)', marginTop: 2 }}>这台机器要登录的聊天平台账号</div>
          </div>
          <Btn sm onClick={addRow} disabled={rows.length >= 8}>+ 加 inbox</Btn>
        </header>

        <main style={{ flex: 1, overflow: 'auto', padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ font: '500 10px/1 var(--f-mono)', letterSpacing: '0.18em', textTransform: 'uppercase', color: 'var(--ink-3)', marginBottom: 4 }}>
            {rows.length}/8 inbox · 填写登录凭据后点「启动」
          </div>
          {rows.length === 0 && (
            <div style={{ padding: '40px 0', textAlign: 'center', color: 'var(--ink-4)', fontFamily: 'var(--f-serif)', fontSize: 15 }}>
              还没有 inbox，点右上角「+ 加 inbox」
            </div>
          )}
          {rows.map(row => (
            <div key={row.id} style={{ background: 'var(--bg-base)', border: '1px solid var(--line-subtle)', borderRadius: 'var(--r-lg)', padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr auto', gap: 10, alignItems: 'end' }}>
                <Field label="CHAT BASE URL">
                  <input style={inputStyle} value={row.baseUrl} onChange={e => update(row.id, 'baseUrl', e.target.value)} placeholder="https://chat.laborster.com" />
                </Field>
                <Field label="USERNAME">
                  <input style={inputStyle} value={row.username} onChange={e => update(row.id, 'username', e.target.value)} />
                </Field>
                <Field label="PASSWORD">
                  <input style={inputStyle} type="password" value={row.password} onChange={e => update(row.id, 'password', e.target.value)} placeholder="········" />
                </Field>
                <Btn danger sm onClick={() => removeRow(row.id)} style={{ marginBottom: 0 }}>×</Btn>
              </div>
            </div>
          ))}
          {error && <div style={{ color: 'var(--danger)', font: '12px/1 var(--f-mono)' }}>{error}</div>}
        </main>

        <footer style={{ height: 56, flexShrink: 0, borderTop: '1px solid var(--line-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 22px' }}>
          <span style={{ font: '11px/1 var(--f-mono)', color: 'var(--ink-3)' }}>
            配置完成后可前往 Studio 管理接管与回复策略
          </span>
          <div style={{ display: 'flex', gap: 8 }}>
            <Btn sm onClick={() => window.bridge.openStudio()}>打开 Studio ↗</Btn>
            <Btn primary disabled={!valid || saving} onClick={launch}>
              {saving ? '保存中…' : '保存并启动 daemon →'}
            </Btn>
          </div>
        </footer>
      </div>
    </div>
  )
}
