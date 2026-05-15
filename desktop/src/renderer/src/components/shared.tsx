import type { DaemonStatus } from '../../../main/daemon/types'

// ── Dot ────────────────────────────────────────────────────────────────────
const dotStyle: Record<string, React.CSSProperties> = {
  live:   { background: 'var(--live)', boxShadow: '0 0 0 2px var(--live-soft)', animation: 'lampPulse 2.4s ease-in-out infinite' },
  on:     { background: 'var(--brass)' },
  off:    { background: 'var(--ink-4)' },
  ok:     { background: 'var(--ok)', boxShadow: '0 0 0 2px oklch(0.72 0.08 145/0.20)' },
  warn:   { background: 'var(--warn)' },
  danger: { background: 'var(--danger)' },
}

export function Dot({ kind }: { kind: keyof typeof dotStyle }) {
  return (
    <span style={{ width: 6, height: 6, borderRadius: 999, display: 'inline-block', flexShrink: 0, ...dotStyle[kind] }} />
  )
}

// ── StatusChip ─────────────────────────────────────────────────────────────
const chipMap: Record<DaemonStatus, { cls: string; dot: keyof typeof dotStyle; label: string }> = {
  idle:       { cls: 'muted',   dot: 'off',    label: '未启动' },
  connecting: { cls: 'brass',   dot: 'on',     label: '连接中' },
  online:     { cls: 'live',    dot: 'live',   label: '在线' },
  degraded:   { cls: 'warn',    dot: 'warn',   label: '降级' },
  offline:    { cls: 'muted',   dot: 'off',    label: '离线' },
  error401:   { cls: 'danger',  dot: 'danger', label: '401 失效' },
}

const chipBase: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5,
  padding: '2px 7px', borderRadius: 4,
  font: '500 10.5px/1 var(--f-mono)', letterSpacing: '0.06em', textTransform: 'uppercase',
  whiteSpace: 'nowrap',
}
const chipStyles: Record<string, React.CSSProperties> = {
  live:   { color: 'var(--live)',   border: '1px solid oklch(0.66 0.130 30/0.4)',   background: 'var(--live-soft)' },
  brass:  { color: 'var(--brass)',  border: '1px solid var(--brass-line)',           background: 'var(--brass-soft)' },
  warn:   { color: 'var(--warn)',   border: '1px solid oklch(0.78 0.11 70/0.4)',    background: 'oklch(0.78 0.11 70/0.10)' },
  danger: { color: 'var(--danger)', border: '1px solid oklch(0.62 0.15 22/0.45)',  background: 'oklch(0.62 0.15 22/0.12)' },
  muted:  { color: 'var(--ink-3)',  border: '1px solid var(--line)',                background: 'var(--bg-sunken)' },
}

export function StatusChip({ status }: { status: DaemonStatus }) {
  const c = chipMap[status]
  return (
    <span style={{ ...chipBase, ...chipStyles[c.cls] }}>
      <Dot kind={c.dot} />
      {c.label}
    </span>
  )
}

// ── KPIStat ────────────────────────────────────────────────────────────────
export function KPIStat({ label, num, sub, tone = 'default' }: {
  label: string; num: string; sub?: string; tone?: 'default' | 'ok' | 'warn' | 'danger' | 'live'
}) {
  const color = { live: 'var(--live)', ok: 'var(--ok)', warn: 'var(--warn)', danger: 'var(--danger)' }[tone] ?? 'var(--ink-1)'
  return (
    <div style={{ background: 'var(--bg-base)', border: '1px solid var(--line-subtle)', borderRadius: 'var(--r-lg)', padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={{ font: '500 10px/1 var(--f-mono)', letterSpacing: '0.16em', textTransform: 'uppercase', color: 'var(--ink-3)' }}>{label}</span>
      <span style={{ fontFamily: 'var(--f-serif)', fontSize: 28, lineHeight: 1, fontWeight: 400, letterSpacing: '-0.02em', color, fontVariantNumeric: 'tabular-nums' }}>{num}</span>
      {sub && <span style={{ font: '11px/1.4 var(--f-mono)', color: 'var(--ink-4)' }}>{sub}</span>}
    </div>
  )
}

// ── Form field ─────────────────────────────────────────────────────────────
export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <span style={{ font: '500 10.5px/1 var(--f-mono)', letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--ink-3)' }}>{label}</span>
      {children}
      {hint && <span style={{ font: '11px/1.4 var(--f-ui)', color: 'var(--ink-4)' }}>{hint}</span>}
    </label>
  )
}

export const inputStyle: React.CSSProperties = {
  width: '100%', height: 36, padding: '0 12px',
  background: 'var(--bg-sunken)', border: '1px solid var(--line)',
  borderRadius: 'var(--r)', color: 'var(--ink-1)',
  font: '400 13px/1.45 var(--f-ui)', outline: 'none',
}

// ── Buttons ────────────────────────────────────────────────────────────────
export function Btn({ primary, danger, sm, disabled, onClick, children, style }: {
  primary?: boolean; danger?: boolean; sm?: boolean; disabled?: boolean
  onClick?: () => void; children: React.ReactNode; style?: React.CSSProperties
}) {
  const base: React.CSSProperties = {
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6,
    minHeight: sm ? 26 : 30, padding: sm ? '0 10px' : '0 12px',
    borderRadius: 'var(--r)', border: '1px solid var(--line)',
    background: primary ? 'var(--brass)' : danger ? 'oklch(0.62 0.15 22/0.10)' : 'var(--bg-raised)',
    color: primary ? 'oklch(0.18 0.012 60)' : danger ? 'var(--danger)' : 'var(--ink-1)',
    font: `500 ${sm ? 12 : 13}px/1 var(--f-ui)`,
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.4 : 1,
    borderColor: primary ? 'var(--brass)' : danger ? 'oklch(0.62 0.15 22/0.45)' : 'var(--line)',
    ...style,
  }
  return <button style={base} disabled={disabled} onClick={onClick}>{children}</button>
}

// ── Toggle ─────────────────────────────────────────────────────────────────
export function Toggle({ on, onChange }: { on: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!on)}
      style={{ width: 32, height: 18, borderRadius: 999, background: on ? 'var(--brass)' : 'var(--bg-sunken)', border: `1px solid ${on ? 'var(--brass)' : 'var(--line)'}`, position: 'relative', cursor: 'pointer', padding: 0 }}
    >
      <span style={{ position: 'absolute', top: 1, left: on ? 15 : 1, width: 14, height: 14, borderRadius: 999, background: on ? 'oklch(0.18 0.012 60)' : 'var(--ink-2)', transition: 'left 0.15s' }} />
    </button>
  )
}

// ── Rail (sidebar icon nav) ────────────────────────────────────────────────
type RailItem = { id: string; glyph: string; label: string }

export function Rail({ active, onChange, status }: {
  active: string; onChange: (id: string) => void; status: DaemonStatus
}) {
  const items: RailItem[] = [
    { id: 'panel',    glyph: '◎', label: 'Status' },
    { id: 'inbox',    glyph: '◇', label: 'Inboxes' },
    { id: 'logs',     glyph: '☰', label: 'Logs' },
    { id: 'settings', glyph: '⚙', label: 'Settings' },
  ]
  const statusDotBg = { online: 'var(--live)', degraded: 'var(--warn)', error401: 'var(--danger)' }[status] ?? 'var(--ink-4)'

  return (
    <aside style={{ width: 64, flexShrink: 0, background: 'var(--bg-base)', borderRight: '1px solid var(--line-subtle)', display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '14px 0' }}>
      <LabMark style={{ marginBottom: 18 }} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {items.map(it => {
          const on = it.id === active
          return (
            <button key={it.id} title={it.label} onClick={() => onChange(it.id)}
              style={{ width: 44, height: 44, borderRadius: 10, border: 'none', background: on ? 'var(--brass-soft)' : 'transparent', color: on ? 'var(--brass)' : 'var(--ink-3)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', fontFamily: 'var(--f-serif)', position: 'relative' }}>
              <span style={{ fontSize: 16 }}>{it.glyph}</span>
              <span style={{ marginTop: 2, font: '9px/1 var(--f-mono)', opacity: 0.85 }}>{it.label}</span>
              {on && <span style={{ position: 'absolute', left: 0, top: 8, bottom: 8, width: 2, background: 'var(--brass)', borderRadius: 2 }} />}
            </button>
          )
        })}
      </div>
      <div style={{ marginTop: 'auto', position: 'relative' }}>
        <div style={{ width: 32, height: 32, borderRadius: 99, background: 'var(--bg-raised)', border: '1px solid var(--line)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'var(--f-serif)', fontSize: 13, color: 'var(--brass)' }}>A</div>
        <span style={{ position: 'absolute', right: -2, bottom: -2, width: 10, height: 10, borderRadius: 99, border: '2px solid var(--bg-base)', background: statusDotBg }} />
      </div>
    </aside>
  )
}

// ── LabMark ────────────────────────────────────────────────────────────────
export function LabMark({ style }: { style?: React.CSSProperties }) {
  return (
    <span style={{ position: 'relative', display: 'inline-block', width: 22, height: 22, fontFamily: 'var(--f-serif)', fontWeight: 500, fontSize: 22, lineHeight: '22px', color: 'var(--ink-1)', ...style }}>
      L
      <span style={{ position: 'absolute', left: -2, right: -2, top: '56%', height: 2, background: 'var(--brass)', transform: 'rotate(-18deg)', borderRadius: 2 }} />
    </span>
  )
}

// ── SectionHead ────────────────────────────────────────────────────────────
export function SectionHead({ eyebrow, title, right }: { eyebrow: string; title: string; right?: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', paddingBottom: 8, borderBottom: '1px solid var(--line-subtle)' }}>
      <div>
        <div style={{ font: '500 10px/1 var(--f-mono)', letterSpacing: '0.18em', textTransform: 'uppercase', color: 'var(--ink-3)' }}>{eyebrow}</div>
        <div style={{ font: '500 12px/1 var(--f-ui)', marginTop: 4 }}>{title}</div>
      </div>
      {right}
    </div>
  )
}

// ── Settings Row ───────────────────────────────────────────────────────────
export function SettingsRow({ title, sub, right, last }: { title: string; sub?: string; right: React.ReactNode; last?: boolean }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 14px', borderBottom: last ? 'none' : '1px solid var(--line-subtle)', gap: 16 }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 500 }}>{title}</div>
        {sub && <div style={{ font: '11px/1.4 var(--f-mono)', color: 'var(--ink-3)', marginTop: 3 }}>{sub}</div>}
      </div>
      <div>{right}</div>
    </div>
  )
}
