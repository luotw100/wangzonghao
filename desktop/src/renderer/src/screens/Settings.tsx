import { useState } from 'react'
import type { DaemonStatus } from '../../../main/daemon/types'
import { Rail, Toggle, SettingsRow, Field, inputStyle, Btn } from '../components/shared'

interface Props {
  status: DaemonStatus
  studioUrl: string
  username: string
  onNav: (screen: string) => void
  onLogout: () => void
}

type Section = 'general' | 'network' | 'account'

export function Settings({ status, studioUrl, username, onNav, onLogout }: Props) {
  const [section, setSection] = useState<Section>('general')
  const [autoTray, setAutoTray] = useState(true)
  const [closeQuits, setCloseQuits] = useState(false)

  const groups = [
    { kicker: '主进程', items: [
      { id: 'general' as Section, label: '通用', glyph: '◎' },
      { id: 'network' as Section, label: '网络', glyph: '⇄' },
    ]},
    { kicker: '账户', items: [
      { id: 'account' as Section, label: 'Studio 账号', glyph: '○' },
    ]},
  ]

  return (
    <div style={{ display: 'flex', width: '100%', height: '100%', minHeight: 0 }}>
      <Rail active="settings" onChange={id => id !== 'settings' && onNav(id === 'panel' ? 'panel' : id)} status={status} />

      {/* Settings nav */}
      <nav style={{ width: 220, flexShrink: 0, borderRight: '1px solid var(--line-subtle)', padding: '14px 12px', overflow: 'auto' }}>
        {groups.map((g, gi) => (
          <div key={gi} style={{ marginTop: gi === 0 ? 0 : 16 }}>
            <div style={{ font: '500 10px/1 var(--f-mono)', letterSpacing: '0.18em', textTransform: 'uppercase', color: 'var(--ink-3)', padding: '0 10px', marginBottom: 6 }}>{g.kicker}</div>
            {g.items.map(it => {
              const on = it.id === section
              return (
                <div key={it.id} onClick={() => setSection(it.id)}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', borderRadius: 7, background: on ? 'var(--brass-soft)' : 'transparent', color: on ? 'var(--brass)' : 'var(--ink-2)', cursor: 'pointer', fontSize: 12.5, marginBottom: 2 }}>
                  <span style={{ fontFamily: 'var(--f-serif)', fontSize: 13, width: 14, textAlign: 'center' }}>{it.glyph}</span>
                  <span style={{ fontWeight: on ? 500 : 400 }}>{it.label}</span>
                </div>
              )
            })}
          </div>
        ))}
      </nav>

      {/* Content */}
      <main style={{ flex: 1, minWidth: 0, padding: '20px 24px', overflow: 'auto' }}>
        <div style={{ font: '500 10px/1 var(--f-mono)', letterSpacing: '0.18em', textTransform: 'uppercase', color: 'var(--ink-3)' }}>{section.toUpperCase()}</div>
        <h1 style={{ fontFamily: 'var(--f-serif)', fontSize: 24, margin: '4px 0 18px', fontWeight: 400, letterSpacing: '-0.02em' }}>
          {{ general: '通用', network: '网络', account: 'Studio 账号' }[section]}
        </h1>

        {section === 'general' && (
          <div style={{ background: 'var(--bg-base)', border: '1px solid var(--line-subtle)', borderRadius: 'var(--r-lg)', overflow: 'hidden' }}>
            <SettingsRow title="启动时进入托盘" sub="不打开主窗口，安静在后台运行" right={<Toggle on={autoTray} onChange={setAutoTray} />} />
            <SettingsRow title="关闭窗口时退出" sub="默认关闭只是隐藏到托盘" right={<Toggle on={closeQuits} onChange={setCloseQuits} />} last />
          </div>
        )}

        {section === 'network' && (
          <div style={{ background: 'var(--bg-base)', border: '1px solid var(--line-subtle)', borderRadius: 'var(--r-lg)', padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
            <Field label="STUDIO URL" hint="当前值，修改需重新握手">
              <input style={{ ...inputStyle, background: 'var(--bg-sunken)' }} defaultValue={studioUrl} readOnly />
            </Field>
            <p style={{ margin: 0, font: '11px/1.6 var(--f-mono)', color: 'var(--ink-4)' }}>
              修改 Studio URL 请前往「账号」页重新登录。
            </p>
          </div>
        )}

        {section === 'account' && (
          <div style={{ background: 'var(--bg-base)', border: '1px solid var(--line-subtle)', borderRadius: 'var(--r-lg)', overflow: 'hidden' }}>
            <SettingsRow title="当前账号" sub={username || '—'} right={null} />
            <SettingsRow title="Studio URL" sub={studioUrl} right={null} />
            <SettingsRow
              title="重新登录"
              sub="清除 session token，回到登录页重新握手"
              right={<Btn danger sm onClick={onLogout}>退出登录</Btn>}
              last
            />
          </div>
        )}
      </main>
    </div>
  )
}
