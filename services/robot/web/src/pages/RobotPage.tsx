import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import * as api from '../lib/api';
import type {
  ChatArchive,
  Character,
  Contact,
  DistillJob,
  ProviderConfig,
} from '../lib/api';
import { useAuth } from '../lib/auth';
import { IconArrowLeft, IconClose, IconPlus } from '../components/Icons';
import { Modal } from '../components/Modal';
import { formatDate } from '../lib/utils';

type DrawerKey = 'persona' | 'archives' | 'distill' | 'providers' | null;
type PersonaMode = 'preview' | 'edit';
type ContactFilter = 'all' | 'distilled' | 'empty' | 'active';
type FocusTab = 'card' | 'timeline';

const CONTACT_FILTERS: { key: ContactFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'distilled', label: '已蒸馏' },
  { key: 'empty', label: '未蒸馏' },
  { key: 'active', label: 'Active' },
];

function escapeHtml(s: string) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function inlineMarkdown(s: string) {
  return escapeHtml(s)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>');
}

function renderMarkdown(md?: string | null) {
  if (!md?.trim()) return '<p class="ink-3">（空——上传聊天记录并蒸馏后会自动填充，也可以直接手写。）</p>';
  const lines = md.split('\n');
  let html = '';
  let inList = false;
  const closeList = () => {
    if (inList) {
      html += '</ul>';
      inList = false;
    }
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (line.startsWith('# ')) { closeList(); html += `<h1>${inlineMarkdown(line.slice(2))}</h1>`; continue; }
    if (line.startsWith('## ')) { closeList(); html += `<h2>${inlineMarkdown(line.slice(3))}</h2>`; continue; }
    if (line.startsWith('### ')) { closeList(); html += `<h3>${inlineMarkdown(line.slice(4))}</h3>`; continue; }
    if (line.startsWith('> ')) { closeList(); html += `<blockquote>${inlineMarkdown(line.slice(2))}</blockquote>`; continue; }
    if (line === '---') { closeList(); html += '<hr/>'; continue; }
    if (/^\s*[-*]\s/.test(line)) {
      if (!inList) { html += '<ul>'; inList = true; }
      html += `<li>${inlineMarkdown(line.replace(/^\s*[-*]\s/, ''))}</li>`;
      continue;
    }
    if (!line.trim()) { closeList(); continue; }
    closeList();
    html += `<p>${inlineMarkdown(line)}</p>`;
  }
  closeList();
  return html;
}

function relativeTime(iso?: string | null) {
  if (!iso) return '—';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '—';
  const diff = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (diff < 60) return `${diff}s 前`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m 前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h 前`;
  if (diff < 86400 * 7) return `${Math.floor(diff / 86400)}d 前`;
  return new Date(iso).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
}

function previewText(value?: string | null, length = 74) {
  const text = (value || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  return text.length > length ? `${text.slice(0, length)}…` : text;
}

function contactInitial(contact?: Pick<Contact, 'display_name'> | null) {
  return contact?.display_name?.trim()?.[0]?.toUpperCase() || '·';
}

function Icon({ children, size = 16 }: { children: React.ReactNode; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

const IconHome = ({ size = 16 }: { size?: number }) => <Icon size={size}><path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z" /></Icon>;
const IconSearch = ({ size = 16 }: { size?: number }) => <Icon size={size}><circle cx="11" cy="11" r="6.5" /><path d="M16 16l5 5" /></Icon>;
const IconArchive = ({ size = 16 }: { size?: number }) => <Icon size={size}><path d="M3 5h18v3H3z" /><path d="M5 8v11h14V8" /><path d="M10 12h4" /></Icon>;
const IconBeaker = ({ size = 16 }: { size?: number }) => <Icon size={size}><path d="M9 3h6v5l4 9a3 3 0 0 1-3 4H8a3 3 0 0 1-3-4l4-9z" /></Icon>;
const IconKey = ({ size = 16 }: { size?: number }) => <Icon size={size}><circle cx="8" cy="15" r="3" /><path d="M10.5 13L20 3.5M16 7l3 3M14 9l3 3" /></Icon>;
const IconLamp = ({ size = 16 }: { size?: number }) => <Icon size={size}><path d="M9 4h6l3 7H6z" /><path d="M12 11v7" /><path d="M9 21h6" /></Icon>;
const IconEye = ({ size = 16 }: { size?: number }) => <Icon size={size}><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" /></Icon>;
const IconEdit = ({ size = 16 }: { size?: number }) => <Icon size={size}><path d="M4 20h4l11-11-4-4L4 16zM14 5l4 4" /></Icon>;
const IconUpload = ({ size = 16 }: { size?: number }) => <Icon size={size}><path d="M12 16V4M6 10l6-6 6 6M4 20h16" /></Icon>;
const IconCheck = ({ size = 16 }: { size?: number }) => <Icon size={size}><path d="M5 12l5 5L20 7" /></Icon>;

function Wordmark({ withText = true }: { withText?: boolean }) {
  return <span className="wordmark"><span className="glyph" />{withText && <span>Laborster</span>}</span>;
}

function Avatar({ contact, name, size = 32, tone = 'muted' }: { contact?: Contact; name?: string; size?: number; tone?: 'brass' | 'muted' }) {
  const label = contact ? contactInitial(contact) : (name?.trim()?.[0]?.toUpperCase() || '·');
  return (
    <span style={{ position: 'relative', width: size, height: size, borderRadius: 999, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-raised)', border: '1px solid var(--line)', boxShadow: tone === 'brass' ? 'inset 0 0 0 1px var(--brass-line)' : 'none', color: 'var(--ink-1)', fontFamily: 'var(--f-serif)', fontSize: size * 0.42, fontWeight: 500, flex: 'none' }}>
      {label}
    </span>
  );
}

function Chip({ children, tone = 'muted', dot = false }: { children: React.ReactNode; tone?: 'brass' | 'live' | 'ok' | 'warn' | 'danger' | 'muted'; dot?: boolean }) {
  return <span className={`chip ${tone}`}>{dot && <span style={{ width: 5, height: 5, borderRadius: 99, background: 'currentColor', display: 'inline-block' }} />}{children}</span>;
}

export function RobotPage() {
  const navigate = useNavigate();
  const { account: me, logout } = useAuth();
  const [characters, setCharacters] = useState<Character[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [providers, setProviders] = useState<ProviderConfig[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [archives, setArchives] = useState<ChatArchive[]>([]);
  const [jobs, setJobs] = useState<DistillJob[]>([]);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [filter, setFilter] = useState<ContactFilter>('all');
  const [search, setSearch] = useState('');
  const [drawer, setDrawer] = useState<DrawerKey>(null);
  const [personaMode, setPersonaMode] = useState<PersonaMode>('preview');
  const [error, setError] = useState('');
  const [showCreate, setShowCreate] = useState(false);

  const active = characters.find(o => o.id === activeId) || null;

  const loadCharacters = useCallback(async () => {
    try { setCharacters(await api.getCharacters()); } catch (e) { setError(String(e)); }
  }, []);

  const loadProviders = useCallback(async () => {
    try { setProviders(await api.getProviderConfigs()); } catch (e) { setError(String(e)); }
  }, []);

  useEffect(() => { loadCharacters(); loadProviders(); }, [loadCharacters, loadProviders]);

  useEffect(() => {
    if (!activeId && characters.length > 0) setActiveId(characters[0].id);
  }, [characters, activeId]);

  const refreshActive = useCallback(async () => {
    if (!activeId) return;
    try {
      const fresh = await api.getCharacter(activeId);
      setCharacters(prev => prev.map(o => (o.id === fresh.id ? fresh : o)));
    } catch (e) { setError(String(e)); }
  }, [activeId]);

  const loadRobotContext = useCallback(async () => {
    if (!activeId) {
      setContacts([]); setArchives([]); setJobs([]);
      return;
    }
    try {
      const [cs, as, js] = await Promise.all([
        api.getContacts(activeId),
        api.getArchives(activeId),
        api.getDistillJobs(activeId),
      ]);
      setContacts(cs);
      setArchives(as);
      setJobs(js);
      setFocusId(prev => (prev && cs.some(c => c.id === prev) ? prev : cs[0]?.id || null));
    } catch (e) { setError(String(e)); }
  }, [activeId]);

  useEffect(() => { loadRobotContext(); }, [loadRobotContext]);

  useEffect(() => {
    const hasActive = jobs.some(j => j.status === 'pending' || j.status === 'running');
    if (!hasActive || !activeId) return;
    const t = window.setInterval(async () => {
      try { setJobs(await api.getDistillJobs(activeId)); } catch (e) { setError(String(e)); }
    }, 2000);
    return () => window.clearInterval(t);
  }, [jobs, activeId]);

  const handleLogout = async () => {
    await logout();
    navigate('/login', { replace: true });
  };

  const filteredContacts = useMemo(() => {
    const q = search.trim().toLowerCase();
    return contacts.filter(c => {
      const matchesFilter =
        filter === 'all' ||
        (filter === 'distilled' && !!c.card_md) ||
        (filter === 'empty' && !c.card_md) ||
        (filter === 'active' && c.status === 'active');
      const matchesSearch = !q || c.display_name.toLowerCase().includes(q) || (c.wechat_wxid || '').toLowerCase().includes(q);
      return matchesFilter && matchesSearch;
    });
  }, [contacts, filter, search]);

  const focused = contacts.find(c => c.id === focusId) || null;

  if (!me) return null;

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '56px 1fr', height: '100dvh', background: 'var(--bg-deep)', color: 'var(--ink-1)' }}>
      <LeftRail />
      <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0, borderLeft: '1px solid var(--line-subtle)' }}>
        <CockpitHeader
          active={active}
          characters={characters}
          activeId={activeId}
          setActiveId={setActiveId}
          openCreate={() => setShowCreate(true)}
          providers={providers}
          contactsCount={contacts.length}
          archivesCount={archives.length}
          latestJob={jobs[0] || null}
          openDrawer={setDrawer}
          username={me.username}
          logout={handleLogout}
        />

        {error && (
          <div style={{ margin: '10px 14px 0', padding: '10px 12px', background: 'oklch(0.62 0.150 22 / 0.12)', border: '1px solid oklch(0.62 0.150 22 / 0.35)', borderRadius: 8, color: 'var(--danger)', display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 12 }}>
            <span style={{ wordBreak: 'break-all' }}>{error}</span>
            <button onClick={() => setError('')} className="btn btn-ghost btn-sm" style={{ minHeight: 20, padding: '0 6px', color: 'var(--danger)' }}>×</button>
          </div>
        )}

        {!active ? (
          <EmptyCharacter onCreate={() => setShowCreate(true)} />
        ) : (
          <main style={{ display: 'grid', gridTemplateColumns: '340px minmax(420px, 1fr) 380px', flex: 1, minHeight: 0 }}>
            <ContactsColumn
              contacts={filteredContacts}
              allContacts={contacts}
              focusId={focusId}
              onFocus={setFocusId}
              filter={filter}
              setFilter={setFilter}
              search={search}
              setSearch={setSearch}
            />
            <FocusColumn
              contact={focused}
              onSaved={loadRobotContext}
              setError={setError}
            />
            <OpsColumn
              character={active}
              contacts={contacts}
              archives={archives}
              jobs={jobs}
              openDrawer={setDrawer}
            />
          </main>
        )}
      </div>

      {active && drawer === 'persona' && <PersonaDrawer character={active} mode={personaMode} setMode={setPersonaMode} onClose={() => setDrawer(null)} onSaved={refreshActive} setError={setError} />}
      {active && drawer === 'archives' && <ArchivesDrawer character={active} archives={archives} onClose={() => setDrawer(null)} onUploaded={loadRobotContext} setError={setError} />}
      {active && drawer === 'distill' && <DistillDrawer character={active} jobs={jobs} onClose={() => setDrawer(null)} onChanged={loadRobotContext} setError={setError} />}
      {active && drawer === 'providers' && <ProvidersDrawer character={active} providers={providers} onClose={() => setDrawer(null)} onChange={async () => { await loadProviders(); await refreshActive(); }} setError={setError} />}

      <CreateCharacterModal
        open={showCreate}
        providers={providers}
        onClose={() => setShowCreate(false)}
        onCreated={async (c) => {
          setShowCreate(false);
          await loadCharacters();
          setActiveId(c.id);
        }}
        setError={setError}
      />
    </div>
  );
}

function LeftRail() {
  const items = [
    { label: 'Home', href: '/', icon: <IconHome size={18} />, active: false },
    { label: 'Robot', href: '/robot', icon: <IconLamp size={18} />, active: true },
  ];
  return (
    <nav style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '14px 0', gap: 4, background: 'var(--bg-deep)' }}>
      <Link to="/" style={{ marginBottom: 12, color: 'inherit', textDecoration: 'none' }} title="Laborster"><Wordmark withText={false} /></Link>
      <div style={{ width: 24, height: 1, background: 'var(--line-subtle)', margin: '4px 0 8px' }} />
      {items.map(it => (
        <Link key={it.label} to={it.href} title={it.label} style={{ position: 'relative', width: 36, height: 36, borderRadius: 8, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: it.active ? 'var(--brass)' : 'var(--ink-3)', background: it.active ? 'var(--brass-soft)' : 'transparent', textDecoration: 'none', border: `1px solid ${it.active ? 'var(--brass-line)' : 'transparent'}` }}>
          {it.icon}
        </Link>
      ))}
    </nav>
  );
}

function CockpitHeader({
  active, characters, activeId, setActiveId, openCreate, providers, contactsCount, archivesCount, latestJob, openDrawer, username, logout,
}: {
  active: Character | null;
  characters: Character[];
  activeId: string | null;
  setActiveId: (id: string | null) => void;
  openCreate: () => void;
  providers: ProviderConfig[];
  contactsCount: number;
  archivesCount: number;
  latestJob: DistillJob | null;
  openDrawer: (drawer: DrawerKey) => void;
  username: string;
  logout: () => void;
}) {
  const runningJobs = latestJob && (latestJob.status === 'pending' || latestJob.status === 'running');
  return (
    <header style={{ display: 'grid', gridTemplateColumns: 'minmax(250px, auto) 1fr auto', gap: 18, alignItems: 'center', padding: '10px 18px', borderBottom: '1px solid var(--line-subtle)', background: 'var(--bg-base)', flex: 'none' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
        <Link to="/" className="btn btn-ghost btn-sm" title="返回 Home"><IconArrowLeft size={14} /></Link>
        <Avatar name={active?.name || 'Robot'} size={36} tone="brass" />
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <select value={activeId ?? ''} onChange={e => setActiveId(e.target.value || null)} className="select" style={{ height: 30, padding: '4px 28px 4px 8px', minWidth: 170 }}>
              {characters.length === 0 && <option value="">还没有 Character</option>}
              {characters.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
            </select>
            <button onClick={openCreate} className="btn btn-sm btn-ghost"><IconPlus size={13} /> 新建</button>
          </div>
          <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 2 }}>{active?.wechat_wxid_self || '未绑定 wxid'}</div>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'stretch', justifyContent: 'center', minWidth: 0 }}>
        <Kpi label="联系人" value={contactsCount} sub={`Provider ${providers.length}`} />
        <KpiDivider />
        <Kpi label="档案" value={archivesCount} sub="WeFlow JSON" />
        <KpiDivider />
        <Kpi label="蒸馏" value={latestJob ? latestJob.status : '—'} sub={latestJob ? relativeTime(latestJob.created_at) : '尚未触发'} tone={runningJobs ? 'live' : undefined} />
        <KpiDivider />
        <Kpi label="人设新鲜度" value={active ? relativeTime(active.updated_at).replace(' 前', '') : '—'} sub={active?.persona_md ? '已生成' : '空'} />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <HeaderChip onClick={() => openDrawer('persona')} icon={<IconLamp size={14} />} label="人设" sub={active?.persona_md ? 'preview' : '空'} tone="brass" />
        <HeaderChip onClick={() => openDrawer('archives')} icon={<IconArchive size={14} />} label="档案" sub={`${archivesCount} 份`} />
        <HeaderChip onClick={() => openDrawer('distill')} icon={<IconBeaker size={14} />} label="蒸馏" sub={latestJob?.status || 'idle'} />
        <HeaderChip onClick={() => openDrawer('providers')} icon={<IconKey size={14} />} label="模型" sub={active?.provider_config?.name || '未绑定'} />
        <div style={{ width: 1, height: 24, background: 'var(--line-subtle)' }} />
        <div className="mono ink-3" style={{ fontSize: 11 }}>@{username}</div>
        <button onClick={logout} className="btn btn-sm btn-ghost">退出</button>
      </div>
    </header>
  );
}

function Kpi({ label, value, sub, tone }: { label: string; value: string | number; sub: string; tone?: 'brass' | 'live' }) {
  return (
    <div style={{ padding: '0 18px', minWidth: 116 }}>
      <div className="eyebrow">{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 2 }}>
        <span className="tnum" style={{ fontFamily: 'var(--f-serif)', fontSize: 26, fontWeight: 400, letterSpacing: '-0.02em', color: tone === 'brass' ? 'var(--brass)' : tone === 'live' ? 'var(--live)' : 'var(--ink-1)' }}>{value}</span>
        <span className="mono" style={{ fontSize: 10.5, color: 'var(--ink-3)' }}>{sub}</span>
      </div>
    </div>
  );
}

const KpiDivider = () => <div style={{ width: 1, alignSelf: 'stretch', margin: '6px 0', background: 'var(--line-subtle)' }} />;

function HeaderChip({ icon, label, sub, tone, onClick }: { icon: React.ReactNode; label: string; sub: string; tone?: 'brass'; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{ display: 'inline-flex', alignItems: 'center', gap: 8, height: 34, padding: '0 12px', background: 'var(--bg-raised)', border: '1px solid var(--line)', borderRadius: 8, cursor: 'pointer', color: 'var(--ink-1)' }}>
      <span style={{ color: tone === 'brass' ? 'var(--brass)' : 'var(--ink-2)' }}>{icon}</span>
      <span style={{ display: 'flex', flexDirection: 'column', lineHeight: 1.1, alignItems: 'flex-start' }}>
        <span style={{ fontSize: 12, fontWeight: 500 }}>{label}</span>
        <span className="mono" style={{ fontSize: 9.5, color: 'var(--ink-3)', letterSpacing: 0.4 }}>{sub}</span>
      </span>
    </button>
  );
}

function EmptyCharacter({ onCreate }: { onCreate: () => void }) {
  return (
    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }} className="paper-grain">
      <div className="card" style={{ width: 440, padding: 28, textAlign: 'center' }}>
        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 18 }}><Wordmark /></div>
        <h2 className="serif" style={{ fontSize: 24, margin: '0 0 8px' }}>还没有 Character</h2>
        <p className="ink-3" style={{ margin: '0 0 20px' }}>创建主播身份，然后上传聊天记录开始蒸馏。</p>
        <button onClick={onCreate} className="btn btn-primary"><IconPlus size={14} /> 新建 Character</button>
      </div>
    </div>
  );
}

function ContactsColumn({ contacts, allContacts, focusId, onFocus, filter, setFilter, search, setSearch }: {
  contacts: Contact[];
  allContacts: Contact[];
  focusId: string | null;
  onFocus: (id: string) => void;
  filter: ContactFilter;
  setFilter: (f: ContactFilter) => void;
  search: string;
  setSearch: (s: string) => void;
}) {
  const counts: Record<ContactFilter, number> = {
    all: allContacts.length,
    distilled: allContacts.filter(c => !!c.card_md).length,
    empty: allContacts.filter(c => !c.card_md).length,
    active: allContacts.filter(c => c.status === 'active').length,
  };
  return (
    <aside style={{ borderRight: '1px solid var(--line-subtle)', display: 'flex', flexDirection: 'column', minHeight: 0, background: 'var(--bg-base)' }}>
      <div style={{ padding: '12px 14px 10px', borderBottom: '1px solid var(--line-subtle)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <div className="eyebrow">联系人 · Contacts</div>
          <span className="mono ink-4" style={{ fontSize: 10 }}>{allContacts.length} total</span>
        </div>
        <label style={{ position: 'relative', display: 'block' }}>
          <span style={{ position: 'absolute', left: 9, top: 8, color: 'var(--ink-3)' }}><IconSearch size={14} /></span>
          <input value={search} onChange={e => setSearch(e.target.value)} className="input" style={{ paddingLeft: 30 }} placeholder="按昵称 / wxid 检索" />
        </label>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 10 }}>
          {CONTACT_FILTERS.map(f => (
            <button key={f.key} onClick={() => setFilter(f.key)} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, height: 22, padding: '0 8px', borderRadius: 4, fontSize: 11, fontWeight: 500, background: filter === f.key ? 'var(--brass-soft)' : 'transparent', color: filter === f.key ? 'var(--brass)' : 'var(--ink-2)', border: `1px solid ${filter === f.key ? 'var(--brass-line)' : 'var(--line-subtle)'}`, cursor: 'pointer' }}>
              {f.label}<span className="mono tnum" style={{ fontSize: 9.5, opacity: .7 }}>{counts[f.key]}</span>
            </button>
          ))}
        </div>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
        {contacts.length === 0 ? <div className="ink-3" style={{ padding: 18, fontSize: 13 }}>暂无匹配联系人。上传聊天记录后会自动识别。</div> : contacts.map(c => {
          const active = c.id === focusId;
          return (
            <button key={c.id} onClick={() => onFocus(c.id)} style={{ position: 'relative', display: 'grid', gridTemplateColumns: 'auto 1fr', gap: 10, width: '100%', textAlign: 'left', padding: '10px 14px', background: active ? 'var(--bg-raised)' : 'transparent', border: 0, borderBottom: '1px solid var(--line-subtle)', cursor: 'pointer', color: 'inherit' }}>
              {active && <span className="marker" />}
              <Avatar contact={c} tone={c.card_md ? 'brass' : 'muted'} />
              <div style={{ minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                  <span style={{ fontWeight: 500, fontSize: 13.5, color: c.status === 'active' ? 'var(--ink-1)' : 'var(--ink-3)' }}>{c.display_name}</span>
                  <span className="mono tnum" style={{ fontSize: 10, color: 'var(--ink-3)' }}>{relativeTime(c.updated_at)}</span>
                </div>
                <div style={{ display: 'flex', gap: 6, marginTop: 6, alignItems: 'center' }}>
                  <Chip tone={c.card_md ? 'brass' : 'muted'}>{c.card_md ? '已蒸馏' : '未蒸馏'}</Chip>
                  <span className="mono ink-4" style={{ fontSize: 10 }}>{c.wechat_wxid || 'no wxid'}</span>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

function FocusColumn({ contact, onSaved, setError }: {
  contact: Contact | null;
  onSaved: () => void;
  setError: (s: string) => void;
}) {
  const [tab, setTab] = useState<FocusTab>('card');
  useEffect(() => { setTab('card'); }, [contact?.id]);
  if (!contact) {
    return <section className="paper-grain" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-3)' }}>选择一个联系人。</section>;
  }
  return (
    <section style={{ display: 'flex', flexDirection: 'column', minHeight: 0, background: 'var(--bg-deep)' }} className="paper-grain">
      <div style={{ padding: '12px 22px', borderBottom: '1px solid var(--line-subtle)', background: 'var(--bg-base)', display: 'flex', alignItems: 'center', gap: 16 }}>
        <Avatar contact={contact} size={40} tone={contact.card_md ? 'brass' : 'muted'} />
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontFamily: 'var(--f-serif)', fontSize: 18, fontWeight: 500 }}>{contact.display_name}</span>
            <Chip tone={contact.card_md ? 'brass' : 'muted'}>{contact.card_md ? '关系卡已生成' : '待蒸馏'}</Chip>
          </div>
          <div className="mono" style={{ fontSize: 11, color: 'var(--ink-3)', marginTop: 2 }}>wxid: {contact.wechat_wxid || '—'} · status: {contact.status}</div>
        </div>
      </div>
      <div style={{ display: 'flex', padding: '0 22px', borderBottom: '1px solid var(--line-subtle)', background: 'var(--bg-base)' }}>
        {[
          { key: 'card' as const, label: '关系卡片' },
          { key: 'timeline' as const, label: '时间轴' },
        ].map(t => <button key={t.key} onClick={() => setTab(t.key)} style={{ padding: '10px 14px', background: 'transparent', border: 0, borderBottom: `2px solid ${tab === t.key ? 'var(--brass)' : 'transparent'}`, color: tab === t.key ? 'var(--ink-1)' : 'var(--ink-3)', fontSize: 12.5, fontWeight: 500, cursor: 'pointer', marginBottom: -1 }}>{t.label}</button>)}
      </div>
      <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }} className="fade-up" key={`${contact.id}-${tab}`}>
        {tab === 'card' && <CardView contact={contact} onSaved={onSaved} setError={setError} />}
        {tab === 'timeline' && <TimelineView contact={contact} />}
      </div>
    </section>
  );
}

function CardView({ contact, onSaved, setError }: { contact: Contact; onSaved: () => void; setError: (s: string) => void }) {
  const [edit, setEdit] = useState(false);
  const [draft, setDraft] = useState(contact.card_md ?? '');
  const [name, setName] = useState(contact.display_name);
  const [saving, setSaving] = useState(false);
  useEffect(() => { setDraft(contact.card_md ?? ''); setName(contact.display_name); setEdit(false); }, [contact.id, contact.card_md, contact.display_name]);
  const dirty = draft !== (contact.card_md ?? '') || name !== contact.display_name;
  const save = async () => {
    setSaving(true);
    try { await api.updateContact(contact.id, { card_md: draft, display_name: name }); onSaved(); setEdit(false); } catch (e) { setError(String(e)); } finally { setSaving(false); }
  };
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 240px', gap: 0, height: '100%', minHeight: 0 }}>
      <div style={{ padding: '26px 32px', overflow: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
          <div className="eyebrow">关系卡片 · 由蒸馏生成 · 你可以校对</div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="btn btn-sm" onClick={() => setEdit(!edit)}>{edit ? <><IconEye size={12} /> 预览</> : <><IconEdit size={12} /> 编辑</>}</button>
            {edit && <button className="btn btn-sm btn-primary" disabled={!dirty || saving} onClick={save}><IconCheck size={12} /> {saving ? '保存中' : '保存'}</button>}
          </div>
        </div>
        {edit ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <input className="input" value={name} onChange={e => setName(e.target.value)} placeholder="备注名" />
            <textarea className="textarea mono" style={{ fontSize: 13, lineHeight: 1.6, minHeight: 460 }} value={draft} onChange={e => setDraft(e.target.value)} placeholder="（空——蒸馏后会填充结构化卡片）" />
          </div>
        ) : <div className="prose-doc" dangerouslySetInnerHTML={{ __html: renderMarkdown(draft) }} />}
      </div>
      <aside style={{ borderLeft: '1px solid var(--line-subtle)', padding: '26px 18px', background: 'var(--bg-base)', overflowY: 'auto' }}>
        <div className="eyebrow" style={{ marginBottom: 10 }}>互动信号</div>
        <Stat label="卡片状态" value={contact.card_md ? '已蒸馏' : '待蒸馏'} tone={contact.card_md ? 'brass' : undefined} />
        <Stat label="联系人状态" value={contact.status} />
        <Stat label="微信 wxid" value={contact.wechat_wxid || '—'} />
        <div className="rule" style={{ margin: '18px 0' }} />
        <div className="eyebrow" style={{ marginBottom: 10 }}>建议动作</div>
        <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Suggestion>校对称呼、禁忌和共同记忆。</Suggestion>
          <Suggestion>如果卡片为空，先上传记录并触发蒸馏。</Suggestion>
          <Suggestion tone="warn">不要在卡片里写未经验证的事实。</Suggestion>
        </ul>
      </aside>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: 'brass' }) {
  return <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 10, padding: '6px 0', borderBottom: '1px dashed var(--line-subtle)' }}><span className="mono ink-3" style={{ fontSize: 11 }}>{label}</span><span className="tnum" style={{ fontSize: 13, fontWeight: 500, color: tone === 'brass' ? 'var(--brass)' : 'var(--ink-1)', textAlign: 'right', wordBreak: 'break-all' }}>{value}</span></div>;
}

function Suggestion({ children, tone }: { children: React.ReactNode; tone?: 'warn' }) {
  return <li style={{ padding: '8px 10px', borderRadius: 6, fontSize: 12, lineHeight: 1.45, background: tone === 'warn' ? 'oklch(0.78 0.11 70 / 0.10)' : 'var(--bg-sunken)', border: `1px solid ${tone === 'warn' ? 'oklch(0.78 0.11 70 / 0.35)' : 'var(--line-subtle)'}`, color: tone === 'warn' ? 'var(--warn)' : 'var(--ink-2)' }}>{children}</li>;
}

function TimelineView({ contact }: { contact: Contact }) {
  const events = [
    { at: contact.updated_at, text: '关系卡片 / 联系人信息更新', tone: 'brass' as const },
    { at: contact.created_at, text: `${contact.display_name} 加入 Robot 档案`, tone: 'muted' as const },
  ];
  return (
    <div style={{ padding: '26px 32px', maxWidth: 720, margin: '0 auto' }}>
      <div className="eyebrow" style={{ marginBottom: 18 }}>时间轴 · 与 {contact.display_name} 的所有可见事件</div>
      <ol style={{ listStyle: 'none', padding: 0, margin: 0, position: 'relative' }}>
        <span style={{ position: 'absolute', left: 7, top: 6, bottom: 6, width: 1, background: 'var(--line)' }} />
        {events.map((e, i) => <li key={`${e.at}-${i}`} style={{ position: 'relative', paddingLeft: 28, paddingBottom: 18 }}><span style={{ position: 'absolute', left: 2, top: 4, width: 11, height: 11, borderRadius: 99, background: 'var(--bg-deep)', border: `1.5px solid ${e.tone === 'brass' ? 'var(--brass)' : 'var(--ink-3)'}` }} /><div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}><span className="mono tnum ink-3" style={{ fontSize: 11, minWidth: 42 }}>{relativeTime(e.at)}</span><span style={{ fontSize: 13.5 }}>{e.text}</span></div></li>)}
      </ol>
    </div>
  );
}

function OpsColumn({ character, contacts, archives, jobs, openDrawer }: {
  character: Character;
  contacts: Contact[];
  archives: ChatArchive[];
  jobs: DistillJob[];
  openDrawer: (drawer: DrawerKey) => void;
}) {
  const latestJob = jobs[0] || null;
  return (
    <aside style={{ borderLeft: '1px solid var(--line-subtle)', display: 'flex', flexDirection: 'column', minHeight: 0, background: 'var(--bg-base)' }}>
      <div style={{ padding: '16px 18px', borderBottom: '1px solid var(--line-subtle)', background: 'var(--bg-deep)' }} className="paper-grain">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}><div className="eyebrow">人设 · Persona</div><button className="btn btn-sm btn-ghost" onClick={() => openDrawer('persona')}>查看 / 编辑</button></div>
        <p style={{ margin: 0, fontFamily: 'var(--f-serif)', fontStyle: 'italic', color: 'var(--ink-2)', fontSize: 13.5, lineHeight: 1.55 }}>{previewText(character.persona_md, 155) || '（空）'}</p>
        <div style={{ display: 'flex', gap: 6, marginTop: 10, flexWrap: 'wrap' }}><Chip>{character.status}</Chip><Chip tone="brass" dot>{contacts.filter(c => c.card_md).length} Cards</Chip><Chip>{archives.length} Archives</Chip></div>
      </div>
      <div style={{ padding: '14px 18px', flex: 1, overflowY: 'auto' }}>
        <div className="eyebrow" style={{ marginBottom: 10 }}>最近档案</div>
        {archives.length === 0 ? <div className="ink-3" style={{ fontSize: 12 }}>还没有上传档案。</div> : archives.slice(0, 5).map(a => (
          <div key={a.id} style={{ padding: '8px 0', borderBottom: '1px dashed var(--line-subtle)' }}>
            <div className="mono" style={{ fontSize: 12 }}>{a.filename}</div>
            <div className="mono ink-3" style={{ fontSize: 10, marginTop: 2 }}>{a.message_count.toLocaleString()} 条 · {relativeTime(a.uploaded_at)}</div>
          </div>
        ))}
        <div className="rule" style={{ margin: '18px 0' }} />
        <div className="eyebrow" style={{ marginBottom: 10 }}>最近蒸馏</div>
        {jobs.length === 0 ? <div className="ink-3" style={{ fontSize: 12 }}>还没有蒸馏任务。</div> : jobs.slice(0, 5).map(j => (
          <div key={j.id} style={{ padding: '8px 0', borderBottom: '1px dashed var(--line-subtle)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
              <span className="mono" style={{ fontSize: 12 }}>{j.id}</span>
              <Chip tone={j.status === 'done' ? 'ok' : j.status === 'failed' ? 'danger' : j.status === 'running' ? 'live' : 'muted'}>{j.status}</Chip>
            </div>
            <div className="mono ink-3" style={{ fontSize: 10, marginTop: 2 }}>{relativeTime(j.created_at)}{j.error_message ? ` · ${j.error_message.slice(0, 40)}` : ''}</div>
          </div>
        ))}
      </div>
      <div style={{ padding: '12px 18px', borderTop: '1px solid var(--line-subtle)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <IconBeaker size={14} />
        <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontSize: 12, fontWeight: 500 }}>上次蒸馏 · {latestJob?.status || '无任务'}</div><div className="mono ink-4" style={{ fontSize: 10 }}>{latestJob ? `${relativeTime(latestJob.created_at)} · ${latestJob.id}` : '先上传档案，再开始蒸馏'}</div></div>
        <button className="btn btn-sm btn-primary" onClick={() => openDrawer('distill')}>开始蒸馏</button>
      </div>
    </aside>
  );
}

function Drawer({ title, sub, children, onClose, width = 720 }: { title: string; sub: string; children: React.ReactNode; onClose: () => void; width?: number }) {
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 50 }}>
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'oklch(0.06 0.005 60 / 0.6)', backdropFilter: 'blur(2px)' }} />
      <div className="fade-up" style={{ position: 'absolute', top: 0, right: 0, bottom: 0, width, maxWidth: 'calc(100vw - 56px)', background: 'var(--bg-base)', borderLeft: '1px solid var(--line)', boxShadow: 'var(--shadow-lg)', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={{ padding: '16px 22px', borderBottom: '1px solid var(--line-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}><div><div style={{ fontFamily: 'var(--f-serif)', fontSize: 18, fontWeight: 500 }}>{title}</div><div className="mono ink-3" style={{ fontSize: 11, marginTop: 2 }}>{sub}</div></div><button className="btn btn-ghost btn-sm" onClick={onClose}><IconClose size={14} /></button></div>
        <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>{children}</div>
      </div>
    </div>
  );
}

function PersonaDrawer({ character, mode, setMode, onClose, onSaved, setError }: { character: Character; mode: PersonaMode; setMode: (m: PersonaMode) => void; onClose: () => void; onSaved: () => void; setError: (s: string) => void }) {
  const [draft, setDraft] = useState(character.persona_md ?? '');
  const [saving, setSaving] = useState(false);
  useEffect(() => setDraft(character.persona_md ?? ''), [character.id, character.persona_md]);
  const dirty = draft !== (character.persona_md ?? '');
  const save = async () => { setSaving(true); try { await api.updateCharacter(character.id, { persona_md: draft }); onSaved(); } catch (e) { setError(String(e)); } finally { setSaving(false); } };
  return (
    <Drawer title="人设档案 · Persona" sub={`运行时直接注入 system prompt · 更新于 ${formatDate(character.updated_at)}`} onClose={onClose} width={820}>
      <div style={{ padding: '16px 22px', borderBottom: '1px solid var(--line-subtle)', display: 'flex', alignItems: 'center', gap: 8 }}><button onClick={() => setMode('preview')} className="btn btn-sm" style={{ background: mode === 'preview' ? 'var(--brass-soft)' : 'var(--bg-raised)', color: mode === 'preview' ? 'var(--brass)' : 'var(--ink-2)', borderColor: mode === 'preview' ? 'var(--brass-line)' : 'var(--line)' }}><IconEye size={12} /> 预览</button><button onClick={() => setMode('edit')} className="btn btn-sm" style={{ background: mode === 'edit' ? 'var(--brass-soft)' : 'var(--bg-raised)', color: mode === 'edit' ? 'var(--brass)' : 'var(--ink-2)', borderColor: mode === 'edit' ? 'var(--brass-line)' : 'var(--line)' }}><IconEdit size={12} /> 编辑</button><span style={{ flex: 1 }} /><button className="btn btn-sm btn-ghost" disabled={!dirty || saving} onClick={() => setDraft(character.persona_md ?? '')}>还原</button><button className="btn btn-sm btn-primary" disabled={!dirty || saving} onClick={save}><IconCheck size={12} /> {saving ? '保存中' : '保存'}</button></div>
      <div style={{ padding: '28px 38px' }}>{mode === 'preview' ? <div className="prose-doc" dangerouslySetInnerHTML={{ __html: renderMarkdown(draft) }} /> : <textarea className="textarea mono" style={{ fontSize: 13.5, lineHeight: 1.65, minHeight: '70vh' }} value={draft} onChange={e => setDraft(e.target.value)} />}</div>
    </Drawer>
  );
}

function ArchivesDrawer({ character, archives, onClose, onUploaded, setError }: { character: Character; archives: ChatArchive[]; onClose: () => void; onUploaded: () => void; setError: (s: string) => void }) {
  const [selfWxid, setSelfWxid] = useState(character.wechat_wxid_self ?? '');
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const upload = async () => { if (!file || !selfWxid.trim()) return; setUploading(true); try { await api.uploadArchive(character.id, file, selfWxid.trim()); setFile(null); if (fileInputRef.current) fileInputRef.current.value = ''; onUploaded(); } catch (e) { setError(String(e)); } finally { setUploading(false); } };
  return (
    <Drawer title="聊天档案 · Archives" sub="上传 WeFlow JSON 导出 · 一次性蒸馏来源" onClose={onClose}>
      <div style={{ padding: 22 }}><div className="card" style={{ padding: 18, marginBottom: 18 }}><div className="eyebrow" style={{ marginBottom: 12 }}>上传新档案</div><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}><label><div className="mono ink-3" style={{ fontSize: 11, marginBottom: 4 }}>主播 wxid</div><input className="input mono" value={selfWxid} onChange={e => setSelfWxid(e.target.value)} placeholder="wxid_xxxxx" /></label><label><div className="mono ink-3" style={{ fontSize: 11, marginBottom: 4 }}>WeFlow JSON</div><input ref={fileInputRef} type="file" accept="application/json,.json" onChange={e => setFile(e.target.files?.[0] ?? null)} className="input" /></label></div><div style={{ marginTop: 12, display: 'flex', justifyContent: 'flex-end' }}><button className="btn btn-sm btn-primary" onClick={upload} disabled={!file || !selfWxid.trim() || uploading}><IconUpload size={12} /> {uploading ? '上传中' : '上传并解析'}</button></div></div><div className="eyebrow" style={{ marginBottom: 8 }}>已有档案 · {archives.length} 份</div><div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>{archives.length === 0 ? <div className="card ink-3" style={{ padding: 18 }}>还没有上传任何聊天记录。</div> : archives.map(a => <div key={a.id} className="card" style={{ padding: '12px 16px' }}><div className="mono" style={{ fontSize: 13 }}>{a.filename}</div><div className="mono ink-3" style={{ fontSize: 11, marginTop: 2 }}>self: {a.self_wxid} · {a.message_count.toLocaleString()} 条 · {a.contact_count} 联系人 · {formatDate(a.uploaded_at)}</div></div>)}</div></div>
    </Drawer>
  );
}

function DistillDrawer({ character, jobs, onClose, onChanged, setError }: { character: Character; jobs: DistillJob[]; onClose: () => void; onChanged: () => void; setError: (s: string) => void }) {
  const [creating, setCreating] = useState(false);
  const create = async () => { setCreating(true); try { await api.createDistillJob(character.id); onChanged(); } catch (e) { setError(String(e)); } finally { setCreating(false); } };
  return (
    <Drawer title="蒸馏 · Distill" sub="从历史对话中折叠出 Persona + Cards" onClose={onClose}>
      <div style={{ padding: 22 }}><div className="card" style={{ padding: '16px 18px', marginBottom: 18, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}><div><div style={{ fontWeight: 500 }}>下一次蒸馏</div><div className="mono ink-3" style={{ fontSize: 11, marginTop: 2 }}>会更新 Persona + 全部 Contact Cards</div></div><button className="btn btn-primary" onClick={create} disabled={creating || !character.provider_config_id} title={!character.provider_config_id ? '请先在模型抽屉选择 Provider' : ''}><IconBeaker size={14} /> {creating ? '创建中' : '开始蒸馏'}</button></div><div className="eyebrow" style={{ marginBottom: 8 }}>历史任务</div><div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>{jobs.length === 0 ? <div className="card ink-3" style={{ padding: 18 }}>还没有蒸馏任务。</div> : jobs.map(j => <DistillJobRow key={j.id} job={j} />)}</div></div>
    </Drawer>
  );
}

function DistillJobRow({ job }: { job: DistillJob }) {
  const wt = job.progress.windows_total ?? 0;
  const wd = job.progress.windows_done ?? 0;
  const ct = job.progress.contacts_total ?? 0;
  const cd = job.progress.contacts_done ?? 0;
  const pct = wt > 0 ? Math.round((wd / wt) * 100) : 0;
  const tone = job.status === 'done' ? 'ok' : job.status === 'failed' ? 'danger' : job.status === 'running' ? 'live' : 'muted';
  return <div className="card" style={{ padding: '14px 16px' }}><div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}><div className="mono" style={{ fontSize: 13 }}>{job.id}</div><Chip tone={tone}>{job.status}</Chip></div><div className="mono ink-3" style={{ fontSize: 11, marginBottom: 6 }}>{wt > 0 ? `${wd}/${wt} 窗口 · ${cd}/${ct} 联系人` : '尚未开始'} · {formatDate(job.created_at)}</div>{wt > 0 && <div style={{ height: 3, background: 'var(--bg-sunken)', borderRadius: 99, overflow: 'hidden' }}><div style={{ height: '100%', width: `${pct}%`, background: tone === 'danger' ? 'var(--danger)' : tone === 'ok' ? 'var(--ok)' : 'var(--brass)' }} /></div>}{job.error_message && <div className="mono" style={{ color: 'var(--danger)', fontSize: 12, marginTop: 6 }}>! {job.error_message}</div>}</div>;
}

function ProvidersDrawer({ character, providers, onClose, onChange, setError }: { character: Character; providers: ProviderConfig[]; onClose: () => void; onChange: () => Promise<void>; setError: (s: string) => void }) {
  const [showCreate, setShowCreate] = useState(false);
  const setCharacterProvider = async (pid: string | null) => { try { await api.updateCharacter(character.id, { provider_config_id: pid }); await onChange(); } catch (e) { setError(String(e)); } };
  const handleDelete = async (id: string) => { if (!confirm('确认删除此 Provider Config？')) return; try { await api.deleteProviderConfig(id); await onChange(); } catch (e) { setError(String(e)); } };
  return (
    <Drawer title="模型 · Providers" sub="同时支持多个 OpenAI 兼容后端" onClose={onClose}>
      <div style={{ padding: 22 }}><div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}><div className="eyebrow">已配置 · {providers.length}</div><button className="btn btn-sm btn-primary" onClick={() => setShowCreate(true)}><IconPlus size={12} /> 新建</button></div><div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>{providers.length === 0 ? <div className="card ink-3" style={{ padding: 18 }}>还没有 Provider Config。</div> : providers.map(p => { const bound = character.provider_config_id === p.id; return <div key={p.id} className="card" style={{ padding: '14px 16px', borderColor: bound ? 'var(--brass-line)' : 'var(--line-subtle)', background: bound ? 'var(--brass-soft)' : 'var(--bg-base)' }}><div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, marginBottom: 4 }}><div style={{ fontWeight: 500 }}>{p.name} {bound && <Chip tone="brass" dot>已绑定</Chip>}</div><div style={{ display: 'flex', gap: 8 }}><button className="btn btn-sm btn-ghost" onClick={() => setCharacterProvider(bound ? null : p.id)}>{bound ? '解绑' : '绑定'}</button><button className="btn btn-sm btn-ghost" onClick={() => handleDelete(p.id)} style={{ color: 'var(--danger)' }}><IconClose size={12} /></button></div></div><div className="mono ink-3" style={{ fontSize: 11 }}>{p.base_url}</div><div className="mono ink-3" style={{ fontSize: 11, marginTop: 2 }}>model: {p.default_model} · key: {p.api_key_preview || '未设置'}</div></div>; })}</div></div><CreateProviderModal open={showCreate} onClose={() => setShowCreate(false)} onCreated={async () => { setShowCreate(false); await onChange(); }} setError={setError} />
    </Drawer>
  );
}

function CreateCharacterModal({ open, providers, onClose, onCreated, setError }: { open: boolean; providers: ProviderConfig[]; onClose: () => void; onCreated: (c: Character) => void; setError: (s: string) => void }) {
  const [name, setName] = useState('');
  const [wxid, setWxid] = useState('');
  const [providerId, setProviderId] = useState<string>('');
  const [creating, setCreating] = useState(false);
  useEffect(() => { if (!open) { setName(''); setWxid(''); return; } if (providers.length > 0 && !providerId) setProviderId(providers[0].id); }, [open, providers, providerId]);
  const handle = async () => { if (!name.trim()) return; setCreating(true); try { const c = await api.createCharacter({ name: name.trim(), wechat_wxid_self: wxid.trim() || null, provider_config_id: providerId || null }); onCreated(c); } catch (e) { setError(String(e)); } finally { setCreating(false); } };
  return <Modal open={open} onClose={onClose}><h3 className="serif" style={{ fontSize: 20, margin: '0 0 16px' }}>新建 Character</h3><div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 16 }}><label><div className="mono ink-3" style={{ fontSize: 11, marginBottom: 4 }}>姓名</div><input value={name} onChange={e => setName(e.target.value)} placeholder="Character 显示名" autoFocus className="input" /></label><label><div className="mono ink-3" style={{ fontSize: 11, marginBottom: 4 }}>主播本人 wxid（可空，蒸馏时识别 self/counterpart 用）</div><input value={wxid} onChange={e => setWxid(e.target.value)} placeholder="wxid_xxxxx" className="input mono" /></label><label><div className="mono ink-3" style={{ fontSize: 11, marginBottom: 4 }}>Provider Config</div><select value={providerId} onChange={e => setProviderId(e.target.value)} className="select"><option value="">（不绑定，稍后再选）</option>{providers.map(p => <option key={p.id} value={p.id}>{p.name} ({p.default_model})</option>)}</select></label></div><div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}><button onClick={onClose} className="btn btn-ghost">取消</button><button onClick={handle} disabled={!name.trim() || creating} className="btn btn-primary">{creating ? '创建中' : '创建'}</button></div></Modal>;
}

function CreateProviderModal({ open, onClose, onCreated, setError }: { open: boolean; onClose: () => void; onCreated: () => void; setError: (s: string) => void }) {
  const [name, setName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('');
  const [creating, setCreating] = useState(false);
  useEffect(() => { if (!open) { setName(''); setBaseUrl(''); setApiKey(''); setModel(''); } }, [open]);
  const handle = async () => { if (!name.trim() || !baseUrl.trim() || !model.trim()) return; setCreating(true); try { await api.createProviderConfig({ name: name.trim(), base_url: baseUrl.trim(), api_key: apiKey || null, default_model: model.trim() }); onCreated(); } catch (e) { setError(String(e)); } finally { setCreating(false); } };
  return <Modal open={open} onClose={onClose}><h3 className="serif" style={{ fontSize: 20, margin: '0 0 16px' }}>新建 Provider Config</h3><div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 16 }}><input value={name} onChange={e => setName(e.target.value)} placeholder="名称（如 Deepseek）" className="input" /><input value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="base_url（如 https://api.deepseek.com/v1）" className="input mono" /><input value={apiKey} onChange={e => setApiKey(e.target.value)} type="password" placeholder="api_key" className="input mono" /><input value={model} onChange={e => setModel(e.target.value)} placeholder="default_model（如 deepseek-chat）" className="input mono" /></div><div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}><button onClick={onClose} className="btn btn-ghost">取消</button><button onClick={handle} disabled={!name.trim() || !baseUrl.trim() || !model.trim() || creating} className="btn btn-primary">{creating ? '创建中' : '创建'}</button></div></Modal>;
}
