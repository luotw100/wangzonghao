import { useEffect, useRef, useState } from 'react'
import type { DaemonState, LogLine, InboxStatus } from '../../../main/daemon/types'
import { Rail, StatusChip, KPIStat, SectionHead, Btn, Dot } from '../components/shared'

interface Props {
  state: DaemonState
  onNav: (screen: string) => void
}

export function Panel({ state, onNav }: Props) {
  const [tab, setTab] = useState<'status' | 'logs'>('status')
  const [logs, setLogs] = useState<LogLine[]>([])
  const logRef = useRef<HTMLDivElement>(null)

  // Subscribe to log stream
  useEffect(() => {
    const off = window.bridge.onLog(line => {
      setLogs(prev => [...prev.slice(-500), line])
    })
    return off
  }, [])

  // Auto-scroll log
  useEffect(() => {
    if (tab === 'logs' && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [logs, tab])

  const kpis = buildKpis(state)
  const is401 = state.status === 'error401'
  const isDegraded = state.status === 'degraded'

  return (
    <div style={{ display: 'flex', width: '100%', height: '100%', minHeight: 0 }}>
      <Rail
        active="panel"
        onChange={id => {
          if (id === 'settings') onNav('settings')
          else if (id === 'inbox') onNav('inbox')
          else if (id === 'logs') setTab('logs')
          else setTab('status')
        }}
        status={state.status}
      />

      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {/* Header */}
        <header style={{ height: 48, flexShrink: 0, borderBottom: '1px solid var(--line-subtle)', display: 'flex', alignItems: 'center', padding: '0 22px', gap: 12 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 600 }}>主状态</div>
            <div style={{ font: '11px/1 var(--f-mono)', color: 'var(--ink-4)', marginTop: 2 }}>
              {state.machineId ? `machine · ${state.machineId}` : 'daemon'}
            </div>
          </div>
          <StatusChip status={state.status} />
          <Btn sm onClick={() => window.bridge.stop()}>停止</Btn>
        </header>

        <main style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', padding: '14px 18px 0' }}>
          {/* Alert banners */}
          {is401 && (
            <Banner kind="danger" title="需要重新登录 · session 已失效" sub="heartbeat 返回 401 · 所有 inbox 已暂停">
              <Btn primary sm onClick={() => onNav('login')}>重新登录 →</Btn>
            </Banner>
          )}
          {isDegraded && (
            <Banner kind="warn" title="降级运行 · 部分 inbox 掉线" sub="其余 inbox 仍正常收发">
              <Btn sm onClick={() => window.bridge.stop()}>停止 daemon</Btn>
            </Banner>
          )}

          {/* KPI grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}>
            {kpis.map((k, i) => <KPIStat key={i} {...k} />)}
          </div>

          {/* Tab bar */}
          <div style={{ display: 'flex', gap: 2, borderBottom: '1px solid var(--line-subtle)', padding: '0 2px', marginTop: 10 }}>
            {(['status', 'logs'] as const).map(t => (
              <button key={t} onClick={() => setTab(t)}
                style={{ padding: '8px 12px', font: '500 12px/1 var(--f-ui)', color: tab === t ? 'var(--ink-1)' : 'var(--ink-3)', background: 'transparent', border: 'none', borderBottom: `2px solid ${tab === t ? 'var(--brass)' : 'transparent'}`, cursor: 'pointer' }}>
                {t === 'status' ? '状态' : '日志'}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div style={{ flex: 1, minHeight: 0, padding: '14px 0', display: 'grid', gridTemplateColumns: tab === 'status' ? '1fr 1fr' : '1fr', gap: 14 }}>
            {tab === 'status' && (
              <>
                {/* Inbox list */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minHeight: 0 }}>
                  <SectionHead eyebrow="INBOXES · LIVE" title="Bridge 挂着的聊天账号"
                    right={<Btn sm onClick={() => onNav('inbox')}>编辑</Btn>} />
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, overflow: 'auto', minHeight: 0 }}>
                    {state.inboxes.length === 0
                      ? <div style={{ color: 'var(--ink-4)', font: '12px/1.6 var(--f-mono)', padding: '12px 0' }}>无 inbox 在线</div>
                      : state.inboxes.map((ib, i) => <InboxRow key={i} ib={ib} />)}
                  </div>
                </div>

                {/* Studio prompt */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <SectionHead eyebrow="STUDIO" title="在 Studio 中配置接管和回复" />
                  <div style={{ background: 'var(--bg-base)', border: '1px solid var(--line-subtle)', borderRadius: 'var(--r-lg)', padding: '18px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <p style={{ margin: 0, fontSize: 12.5, color: 'var(--ink-2)', lineHeight: 1.7 }}>
                      Bridge 已在线，消息正在同步。<br />
                      前往 Studio 打开「接管」Tab，开启联系人接管和自动回复策略。
                    </p>
                    <Btn primary onClick={() => window.bridge.openStudio()}>
                      打开 Studio ↗
                    </Btn>
                  </div>
                </div>
              </>
            )}

            {tab === 'logs' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minHeight: 0 }}>
                <SectionHead eyebrow="LOG · LIVE" title="守护进程日志"
                  right={<Btn sm onClick={() => setLogs([])}>清空</Btn>} />
                <LogViewer logs={logs} ref={logRef} />
              </div>
            )}
          </div>
        </main>

        {/* Status bar */}
        <footer style={{ height: 28, flexShrink: 0, borderTop: '1px solid var(--line-subtle)', display: 'flex', alignItems: 'center', padding: '0 18px' }}>
          <span style={{ font: '10.5px/1 var(--f-mono)', color: 'var(--ink-4)' }}>
            {state.studioUrl} · {state.username}
          </span>
          <span style={{ font: '10.5px/1 var(--f-mono)', color: 'var(--ink-4)', marginLeft: 'auto' }}>
            ⌘, 设置
          </span>
        </footer>
      </div>
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────

function Banner({ kind, title, sub, children }: { kind: 'warn' | 'danger'; title: string; sub: string; children: React.ReactNode }) {
  const colors = kind === 'warn'
    ? { bg: 'oklch(0.78 0.11 70/0.10)', border: 'oklch(0.78 0.11 70/0.40)', icon: '⚠', color: 'var(--warn)' }
    : { bg: 'oklch(0.62 0.15 22/0.10)', border: 'oklch(0.62 0.15 22/0.45)', icon: '✕', color: 'var(--danger)' }
  return (
    <div style={{ marginBottom: 12, padding: '10px 12px', background: colors.bg, border: `1px solid ${colors.border}`, borderRadius: 8, display: 'flex', alignItems: 'center', gap: 10 }}>
      <span style={{ color: colors.color }}>{colors.icon}</span>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 600, fontSize: 12.5, color: colors.color }}>{title}</div>
        <div style={{ font: '11px/1 var(--f-mono)', color: 'var(--ink-2)', marginTop: 3 }}>{sub}</div>
      </div>
      {children}
    </div>
  )
}

function InboxRow({ ib }: { ib: InboxStatus }) {
  return (
    <div style={{ background: 'var(--bg-base)', border: '1px solid var(--line-subtle)', borderRadius: 'var(--r-lg)', padding: '10px 12px', display: 'flex', alignItems: 'center', gap: 10 }}>
      <Dot kind={ib.status === 'online' ? 'live' : ib.status === 'connecting' ? 'on' : 'off'} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500 }}>{ib.handle}</div>
        <div style={{ font: '10.5px/1 var(--f-mono)', color: 'var(--ink-4)', marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {ib.baseUrl} · {ib.peersCount} peers
        </div>
      </div>
    </div>
  )
}

const LogViewer = ({ logs, ref }: { logs: LogLine[]; ref: React.RefObject<HTMLDivElement | null> }) => (
  <div ref={ref} style={{ flex: 1, minHeight: 0, background: 'var(--bg-sunken)', border: '1px solid var(--line-subtle)', borderRadius: 8, font: '11px/1.55 var(--f-mono)', color: 'var(--ink-2)', padding: '10px 12px', overflow: 'auto' }}>
    {logs.length === 0
      ? <span style={{ color: 'var(--ink-4)' }}>等待日志…</span>
      : logs.map((l, i) => (
        <div key={i}>
          <span style={{ color: 'var(--ink-4)' }}>{l.t}</span>{' '}
          <span style={{ color: 'var(--brass)' }}>[{l.src}]</span>{' '}
          <span style={{ color: l.level === 'ok' ? 'var(--ok)' : l.level === 'warn' ? 'var(--warn)' : l.level === 'err' ? 'var(--danger)' : 'var(--ink-2)' }}>{l.msg}</span>
        </div>
      ))}
  </div>
)

function buildKpis(s: DaemonState) {
  const n = s.inboxes.length
  const online = s.inboxes.filter(i => i.status === 'online').length
  const tones = { online: 'ok', degraded: 'warn', error401: 'danger', connecting: 'default', idle: 'default', offline: 'default' } as const
  return [
    { label: 'Studio',   num: s.status === 'error401' ? '401' : s.status === 'online' || s.status === 'degraded' ? '在线' : s.status === 'connecting' ? '握手中' : '离线', tone: tones[s.status], sub: s.studioUrl.replace('https://', '') },
    { label: 'Inboxes',  num: `${online}/${n}`, tone: online === n && n > 0 ? 'ok' : online === 0 ? 'danger' : 'warn', sub: `${n} 个已配置` },
    { label: 'IN · 5m',  num: s.inCount5m > 0 ? String(s.inCount5m) : '—', sub: '最近 5 分钟入站消息' },
    { label: 'Outbox',   num: String(s.outboundPending), sub: '待推送 outbound', tone: s.outboundPending > 10 ? 'warn' : 'default' },
  ] as const
}
