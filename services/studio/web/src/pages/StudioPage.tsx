import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import * as api from '../lib/api';
import type {
  Archive,
  Bridge,
  BridgeWithToken,
  Contact,
  ConversationSummary,
  DistillJob,
  Inbox,
  Message,
  Persona,
  ProviderConfig,
} from '../lib/api';
import { useAuth } from '../lib/auth';

type Tab = 'bridges' | 'inboxes' | 'conversations' | 'personas' | 'providers' | 'archives' | 'distill';

export function StudioPage() {
  const navigate = useNavigate();
  const { account: me, logout } = useAuth();
  const [tab, setTab] = useState<Tab>('bridges');
  const [bridges, setBridges] = useState<Bridge[]>([]);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [inboxes, setInboxes] = useState<Inbox[]>([]);
  const [providers, setProviders] = useState<ProviderConfig[]>([]);
  const [archives, setArchives] = useState<Archive[]>([]);
  const [jobs, setJobs] = useState<DistillJob[]>([]);
  const [error, setError] = useState('');
  const [tokenJustIssued, setTokenJustIssued] = useState<{ bridge: BridgeWithToken } | null>(null);

  const loadAll = useCallback(async () => {
    try {
      const [bs, ps, ibs, pcs, ars, djs] = await Promise.all([
        api.getBridges(),
        api.getPersonas(),
        api.getInboxes(),
        api.getProviderConfigs(),
        api.getArchives(),
        api.getDistillJobs(),
      ]);
      setBridges(bs);
      setPersonas(ps);
      setInboxes(ibs);
      setProviders(pcs);
      setArchives(ars);
      setJobs(djs);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const handleLogout = async () => {
    await logout();
    navigate('/login', { replace: true });
  };

  if (!me) return null;

  return (
    <div style={{ height: '100dvh', display: 'flex', flexDirection: 'column', background: 'var(--bg-deep)', color: 'var(--ink-1)' }}>
      <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 22px', borderBottom: '1px solid var(--line-subtle)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span className="font-brand" style={{ fontSize: 18, color: 'var(--accent)' }}>Laborster Studio</span>
          <nav style={{ display: 'flex', gap: 8 }}>
            {(['bridges', 'inboxes', 'conversations', 'personas', 'providers', 'archives', 'distill'] as Tab[]).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className="btn btn-sm"
                style={{
                  background: tab === t ? 'var(--brass-soft)' : 'transparent',
                  color: tab === t ? 'var(--brass)' : 'var(--ink-2)',
                  borderColor: tab === t ? 'var(--brass-line)' : 'var(--line-subtle)',
                }}
              >
                {tabLabel(t)}
              </button>
            ))}
          </nav>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span className="mono ink-3" style={{ fontSize: 12 }}>@{me.username}</span>
          <button onClick={handleLogout} className="btn btn-sm btn-ghost">退出</button>
        </div>
      </header>

      {error && (
        <div style={{ margin: '10px 22px', padding: '10px 12px', background: 'oklch(0.62 0.150 22 / 0.12)', border: '1px solid oklch(0.62 0.150 22 / 0.35)', borderRadius: 8, color: 'var(--danger)', display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 12 }}>
          <span style={{ wordBreak: 'break-all' }}>{error}</span>
          <button onClick={() => setError('')} className="btn btn-ghost btn-sm" style={{ minHeight: 20, padding: '0 6px', color: 'var(--danger)' }}>×</button>
        </div>
      )}

      <main style={{ flex: 1, overflow: 'auto', padding: '20px 22px' }}>
        {tab === 'bridges' && (
          <BridgesView
            bridges={bridges} inboxes={inboxes}
            onChanged={loadAll} setError={setError}
            onTokenIssued={(br) => setTokenJustIssued({ bridge: br })}
          />
        )}
        {tab === 'inboxes' && (
          <InboxesView
            inboxes={inboxes} bridges={bridges} personas={personas} providers={providers}
            onChanged={loadAll} setError={setError}
          />
        )}
        {tab === 'conversations' && (
          <ConversationsView
            personas={personas} providers={providers}
            onChanged={loadAll} setError={setError}
          />
        )}
        {tab === 'personas' && <PersonasView personas={personas} onChanged={loadAll} setError={setError} />}
        {tab === 'providers' && <ProvidersView providers={providers} onChanged={loadAll} setError={setError} />}
        {tab === 'archives' && <ArchivesView archives={archives} inboxes={inboxes} onChanged={loadAll} setError={setError} />}
        {tab === 'distill' && <DistillView jobs={jobs} inboxes={inboxes} personas={personas} providers={providers} onChanged={loadAll} setError={setError} />}
      </main>

      {tokenJustIssued && (
        <BridgeCommandModal
          bridge={tokenJustIssued.bridge}
          token={tokenJustIssued.bridge.token}
          onClose={() => setTokenJustIssued(null)}
        />
      )}
    </div>
  );
}

function tabLabel(t: Tab): string {
  return ({
    bridges: 'Bridges', inboxes: '接管号', conversations: '会话', personas: '人设',
    providers: 'Provider', archives: '聊天档案', distill: '蒸馏',
  } as const)[t];
}

// ---------------------------------------------------------------------------
// Bridges
// ---------------------------------------------------------------------------

function BridgesView({ bridges, inboxes, onChanged, setError, onTokenIssued }: {
  bridges: Bridge[];
  inboxes: Inbox[];
  onChanged: () => void;
  setError: (s: string) => void;
  onTokenIssued: (br: BridgeWithToken) => void;
}) {
  const [showCreate, setShowCreate] = useState(false);
  const [showCommandFor, setShowCommandFor] = useState<Bridge | null>(null);
  const inboxesByBridge = useMemo(() => {
    const m: Record<string, Inbox[]> = {};
    for (const ib of inboxes) {
      if (ib.bridge_id) {
        if (!m[ib.bridge_id]) m[ib.bridge_id] = [];
        m[ib.bridge_id].push(ib);
      }
    }
    return m;
  }, [inboxes]);
  return (
    <div>
      <SectionHeader title="Bridges" hint="一台主播的 PC 跑一个 Bridge。新建后这里会给一条启动命令，复制走就能跑。">
        <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}>+ 新建 Bridge</button>
      </SectionHeader>
      {bridges.length === 0 ? <Empty>还没有 Bridge。建一个，会给你一条直接跑的启动命令。</Empty> : (
        <div style={{ display: 'grid', gap: 10 }}>
          {bridges.map(br => (
            <div key={br.id} className="card" style={{ padding: '14px 16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
                <div>
                  <div style={{ fontWeight: 500, display: 'flex', alignItems: 'center', gap: 8 }}>
                    <StatusDot status={br.status} />
                    {br.display_name}
                  </div>
                  <div className="mono ink-3" style={{ fontSize: 11, marginTop: 4 }}>
                    {br.status === 'online' ? `在线 · 主机 ${br.hostname || '—'}` : br.status === 'paired_pending' ? '等待首次连接' : br.status}
                    {' · '}最后心跳 {br.last_seen_at ?? '—'}
                    {' · '}承载 {(inboxesByBridge[br.id] || []).length} 个接管号
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button className="btn btn-sm btn-ghost" onClick={() => setShowCommandFor(br)}>启动命令</button>
                  <button className="btn btn-sm btn-ghost" onClick={async () => {
                    if (!confirm('重新生成 token 会让旧 token 失效（已运行的 bridge 心跳会失败），确认？')) return;
                    try {
                      const fresh = await api.regenerateBridgeToken(br.id);
                      onTokenIssued(fresh);
                      onChanged();
                    } catch (e) { setError(String(e)); }
                  }}>重发 token</button>
                  <button className="btn btn-sm btn-ghost" style={{ color: 'var(--danger)' }} onClick={async () => {
                    if (!confirm('确认 revoke 这个 Bridge？所有 inbox 会从它身上脱钩。')) return;
                    try { await api.deleteBridge(br.id); onChanged(); } catch (e) { setError(String(e)); }
                  }}>revoke</button>
                </div>
              </div>
              {(inboxesByBridge[br.id] || []).length > 0 && (
                <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--line-subtle)' }}>
                  {(inboxesByBridge[br.id] || []).map(ib => (
                    <div key={ib.id} className="mono" style={{ fontSize: 11, color: 'var(--ink-2)' }}>
                      ↳ {ib.platform} · {ib.platform_self_id || '—'} · {ib.display_name} · {ib.enabled ? 'enabled' : 'disabled'}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {showCreate && (
        <CreateBridgeModal
          onClose={() => setShowCreate(false)}
          onCreated={(br) => { setShowCreate(false); onTokenIssued(br); onChanged(); }}
          setError={setError}
        />
      )}
      {showCommandFor && (
        <BridgeCommandModal
          bridge={showCommandFor}
          token={null}
          onClose={() => setShowCommandFor(null)}
        />
      )}
    </div>
  );
}

function StatusDot({ status }: { status: Bridge['status'] }) {
  const color =
    status === 'online' ? 'var(--accent)' :
    status === 'paired_pending' ? 'var(--warn)' :
    status === 'revoked' ? 'var(--danger)' : 'var(--ink-3)';
  return <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 99, background: color }} />;
}

function CreateBridgeModal({ onClose, onCreated, setError }: {
  onClose: () => void;
  onCreated: (br: BridgeWithToken) => void;
  setError: (s: string) => void;
}) {
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const handle = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try { onCreated(await api.createBridge({ display_name: name.trim() })); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  return (
    <ModalShell onClose={onClose} title="新建 Bridge">
      <FormField label="显示名 (主播自己的标记，e.g. alice-mbp)">
        <input className="input" value={name} onChange={e => setName(e.target.value)} placeholder="alice-mbp" autoFocus />
      </FormField>
      <p className="ink-3" style={{ fontSize: 12, margin: '0 0 12px' }}>
        创建后会给你一条 <b>包含 token 的启动命令</b>。命令在你机器上跑，密码不传 Studio。
        关闭命令窗口后 token 就只能重发，命令本身随时能再生成（密码部分要重填）。
      </p>
      <ModalActions onCancel={onClose} onConfirm={handle} confirmLabel={busy ? '创建中...' : '创建 Bridge'} disabled={busy || !name.trim()} />
    </ModalShell>
  );
}

interface ChatInboxDraft {
  base_url: string;
  username: string;
  password: string;
}

function BridgeCommandModal({ bridge, token, onClose }: {
  bridge: Bridge;
  token: string | null;     // present only right after creation/regenerate
  onClose: () => void;
}) {
  const [drafts, setDrafts] = useState<ChatInboxDraft[]>([
    { base_url: 'https://chat.laborster.com', username: '', password: '' },
  ]);
  const [copied, setCopied] = useState(false);

  const tokenSlot = token ?? '<你保存的 token>';
  const lines: string[] = [
    'docker compose run --rm bridge \\',
    `  --token=${tokenSlot} \\`,
    ...drafts.flatMap((d, i) => {
      const url = d.base_url || '<base_url>';
      const u = d.username || '<username>';
      const p = d.password || '<password>';
      const isLast = i === drafts.length - 1;
      const seg = `  --chat-inbox 'base_url=${url},username=${u},password=${p}'${isLast ? '' : ' \\'}`;
      return [seg];
    }),
  ];
  const command = lines.join('\n');

  const update = (idx: number, patch: Partial<ChatInboxDraft>) => {
    setDrafts(prev => prev.map((d, i) => i === idx ? { ...d, ...patch } : d));
  };

  return (
    <ModalShell onClose={onClose} title={`Bridge 启动命令 · ${bridge.display_name}`}>
      <p className="ink-2" style={{ fontSize: 13, marginBottom: 12 }}>
        勾选要让这台 Bridge 登录的 chat 账号，命令会在下方实时拼好。<b>密码不会上传到 Studio</b> ——
        全部留在你浏览器里，复制走的命令也只会跑在你自己的机器上。
        {token && <span style={{ color: 'var(--warn)' }}> Token 只在本次窗口里完整显示，关掉就只能再重发。</span>}
      </p>

      <div style={{ display: 'grid', gap: 10, marginBottom: 12 }}>
        {drafts.map((d, i) => (
          <div key={i} className="card" style={{ padding: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <span className="mono ink-3" style={{ fontSize: 12 }}>chat 登录 #{i + 1}</span>
              {drafts.length > 1 && (
                <button className="btn btn-sm btn-ghost" style={{ color: 'var(--danger)' }}
                        onClick={() => setDrafts(prev => prev.filter((_, j) => j !== i))}>移除</button>
              )}
            </div>
            <div style={{ display: 'grid', gap: 6 }}>
              <input className="input" value={d.base_url} onChange={e => update(i, { base_url: e.target.value })}
                     placeholder="base_url" />
              <input className="input" value={d.username} onChange={e => update(i, { username: e.target.value })}
                     placeholder="username" />
              <input className="input" value={d.password} onChange={e => update(i, { password: e.target.value })}
                     placeholder="password (留空 → 命令里给占位符自己填)" type="text" />
            </div>
          </div>
        ))}
        <button className="btn btn-sm btn-ghost"
                onClick={() => setDrafts(prev => [...prev, { base_url: 'https://chat.laborster.com', username: '', password: '' }])}>
          + 再加一个 chat 账号
        </button>
      </div>

      <pre className="card mono" style={{ padding: 14, fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-all', marginBottom: 12 }}>{command}</pre>

      <ModalActions
        onCancel={onClose}
        onConfirm={async () => {
          try { await navigator.clipboard.writeText(command); setCopied(true); setTimeout(() => setCopied(false), 1200); }
          catch { /* user can still select & copy manually */ }
        }}
        confirmLabel={copied ? '已复制' : '复制命令'}
      />
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// Inboxes
// ---------------------------------------------------------------------------

function InboxesView({ inboxes, bridges, personas, providers, onChanged, setError }: {
  inboxes: Inbox[];
  bridges: Bridge[];
  personas: Persona[];
  providers: ProviderConfig[];
  onChanged: () => void;
  setError: (s: string) => void;
}) {
  return (
    <div>
      <SectionHeader title="接管号" hint="启动 Bridge 时登录的每个 chat 账号会自动出现在这里。点开看粉丝、给粉丝开自动回复。" />
      {inboxes.length === 0 ? (
        <Empty>
          还没有接管号。先去「Bridges」建一个 Bridge、复制启动命令，跑起来后这里会自动出现你登录进去的 chat 账号。
        </Empty>
      ) : (
        <div style={{ display: 'grid', gap: 10 }}>
          {inboxes.map(ib => (
            <InboxCard
              key={ib.id} inbox={ib} bridges={bridges} personas={personas} providers={providers}
              onChanged={onChanged} setError={setError}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function InboxCard({ inbox: ib, bridges, personas, providers, onChanged, setError }: {
  inbox: Inbox;
  bridges: Bridge[];
  personas: Persona[];
  providers: ProviderConfig[];
  onChanged: () => void;
  setError: (s: string) => void;
}) {
  const bridge = bridges.find(b => b.id === ib.bridge_id) || null;
  const online = bridge?.status === 'online';
  return (
    <div className="card" style={{ padding: '14px 16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 280 }}>
          <div style={{ fontWeight: 500, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 99, background: online ? 'var(--accent)' : 'var(--ink-3)' }} />
            {ib.display_name}
            <span className="chip muted">{ib.platform}</span>
            {bridge && <span className="chip muted">运行于 {bridge.display_name}</span>}
            {!ib.enabled && <span className="chip warn">已停用</span>}
          </div>
          <div className="mono ink-3" style={{ fontSize: 11, marginTop: 4 }}>
            平台 ID：{ib.platform_self_id || '—'}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <label style={{ fontSize: 11, color: 'var(--ink-3)' }}>默认人设
            <select value={ib.default_persona_id ?? ''} className="select" style={{ marginLeft: 6 }}
                    onChange={async e => {
                      if (!e.target.value) return;
                      try { await api.updateInbox(ib.id, { default_persona_id: e.target.value }); onChanged(); } catch (err) { setError(String(err)); }
                    }}>
              <option value="">（未选 → 新粉丝默认无人设）</option>
              {personas.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <label style={{ fontSize: 11, color: 'var(--ink-3)' }}>回复 Provider
            <select value={ib.reply_provider_config_id ?? ''} className="select" style={{ marginLeft: 6 }}
                    onChange={async e => {
                      try {
                        if (e.target.value) await api.updateInbox(ib.id, { reply_provider_config_id: e.target.value });
                        else await api.updateInbox(ib.id, { clear_reply_provider: true });
                        onChanged();
                      } catch (err) { setError(String(err)); }
                    }}>
              <option value="">（未选 → 不会自动回复）</option>
              {providers.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <button className="btn btn-sm btn-ghost" onClick={async () => {
            try { await api.updateInbox(ib.id, { enabled: !ib.enabled }); onChanged(); }
            catch (e) { setError(String(e)); }
          }}>{ib.enabled ? '停用' : '启用'}</button>
          <button className="btn btn-sm btn-ghost" style={{ color: 'var(--danger)' }} onClick={async () => {
            if (!confirm('确认删除这个接管号？所有 pending outbound 会被取消。下次 Bridge 重连还会自动重建。')) return;
            try { await api.deleteInbox(ib.id); onChanged(); } catch (e) { setError(String(e)); }
          }}>删除</button>
        </div>
      </div>
      {!ib.reply_provider_config_id && (
        <div className="mono" style={{ fontSize: 11, marginTop: 8, color: 'var(--warn)' }}>
          未选回复 Provider — 自动回复永远不会触发。
        </div>
      )}
      <InboxContacts inbox={ib} personas={personas} setError={setError} onChanged={onChanged} />
    </div>
  );
}

function InboxContacts({ inbox, personas, setError, onChanged }: { inbox: Inbox; personas: Persona[]; setError: (s: string) => void; onChanged: () => void }) {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const reload = useCallback(() => {
    api.getInboxContacts(inbox.id).then(setContacts).catch(e => setError(String(e)));
  }, [inbox.id, setError]);
  useEffect(() => { reload(); }, [reload]);

  if (contacts.length === 0) {
    return <div className="ink-3" style={{ fontSize: 12, marginTop: 12 }}>暂无粉丝 — 第一条消息进来时这里会自动出现联系人卡。</div>;
  }
  return (
    <div style={{ marginTop: 12, borderTop: '1px solid var(--line-subtle)', paddingTop: 12, display: 'grid', gap: 4 }}>
      <div className="ink-3" style={{ fontSize: 11, marginBottom: 4 }}>粉丝 · {contacts.length}</div>
      {contacts.map(c => (
        <ContactRow
          key={c.id}
          contact={c}
          personas={personas}
          inboxReady={inbox.enabled && Boolean(inbox.reply_provider_config_id)}
          expanded={expandedId === c.id}
          onToggle={() => setExpandedId(prev => prev === c.id ? null : c.id)}
          onChanged={() => { reload(); onChanged(); }}
          setError={setError}
        />
      ))}
    </div>
  );
}

function ContactRow({ contact: c, personas, inboxReady, expanded, onToggle, onChanged, setError }: {
  contact: Contact;
  personas: Persona[];
  inboxReady: boolean;
  expanded: boolean;
  onToggle: () => void;
  onChanged: () => void;
  setError: (s: string) => void;
}) {
  const [draftCard, setDraftCard] = useState(c.card_md ?? '');
  const [savingCard, setSavingCard] = useState(false);
  useEffect(() => { setDraftCard(c.card_md ?? ''); }, [c.card_md]);

  const cardPreview = (c.card_md ?? '').replace(/\s+/g, ' ').slice(0, 60);

  return (
    <div style={{ borderBottom: '1px dashed var(--line-subtle)', paddingBottom: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0' }}>
        <button className="btn btn-sm btn-ghost" onClick={onToggle} style={{ minWidth: 18, padding: '0 4px' }}>
          {expanded ? '▾' : '▸'}
        </button>
        <span style={{ fontSize: 13, flex: 1, minWidth: 0 }}>
          <span style={{ fontWeight: 500 }}>{c.display_name}</span>
          {cardPreview && <span className="ink-3" style={{ fontSize: 11, marginLeft: 8 }}>· {cardPreview}{(c.card_md ?? '').length > 60 ? '…' : ''}</span>}
        </span>
        <label style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
          人设
          <select value={c.persona_id ?? ''} className="select" style={{ minWidth: 110 }}
                  onChange={async e => {
                    if (!e.target.value) return;
                    try { await api.updateContact(c.id, { persona_id: e.target.value }); onChanged(); } catch (err) { setError(String(err)); }
                  }}>
            <option value="">（未选）</option>
            {personas.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <label className="mono" style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
          <input type="checkbox" checked={c.autoreply_enabled}
                 onChange={async e => {
                   if (e.target.checked && (!inboxReady || !c.persona_id)) {
                     setError('需要先给接管号选择 Provider，并给这个粉丝选择人设，才能开启自动回复。');
                     return;
                   }
                   try { await api.updateContact(c.id, { autoreply_enabled: e.target.checked }); onChanged(); } catch (err) { setError(String(err)); }
                 }} />
          自动回复
        </label>
      </div>
      {expanded && (
        <div style={{ paddingLeft: 26, paddingRight: 4, paddingBottom: 8, display: 'grid', gap: 6 }}>
          <div className="ink-3" style={{ fontSize: 11 }}>
            平台 ID：<span className="mono">{c.peer_platform_id}</span>
          </div>
          {(!inboxReady || !c.persona_id) && (
            <div className="mono" style={{ fontSize: 11, color: 'var(--warn)' }}>
              需要先给接管号选择 Provider，并给这个粉丝选择人设，才能开启自动回复。
            </div>
          )}
          <label className="ink-3" style={{ fontSize: 11 }}>关系卡（card_md）— 简单写下你跟这个人的关系，AI 回复时会读到</label>
          <textarea
            className="input mono"
            style={{ minHeight: 90, fontSize: 12 }}
            value={draftCard}
            onChange={e => setDraftCard(e.target.value)}
            placeholder="例如：北京大学生，喜欢户外，去年送过我一袋茶叶，叫我「alice 姐」"
          />
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6 }}>
            {draftCard !== (c.card_md ?? '') && (
              <button className="btn btn-sm btn-ghost"
                      onClick={() => setDraftCard(c.card_md ?? '')}>放弃修改</button>
            )}
            <button className="btn btn-sm btn-primary" disabled={savingCard || draftCard === (c.card_md ?? '')}
                    onClick={async () => {
                      setSavingCard(true);
                      try { await api.updateContact(c.id, { card_md: draftCard }); onChanged(); }
                      catch (err) { setError(String(err)); }
                      finally { setSavingCard(false); }
                    }}>{savingCard ? '保存中…' : '保存'}</button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Conversations
// ---------------------------------------------------------------------------

function ConversationsView({ personas, providers, onChanged, setError }: {
  personas: Persona[];
  providers: ProviderConfig[];
  onChanged: () => void;
  setError: (s: string) => void;
}) {
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const next = await api.getConversations();
      setItems(next);
      setSelectedId(prev => prev ?? next[0]?.contact.id ?? null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [setError]);

  useEffect(() => { reload(); }, [reload]);

  const selected = items.find(item => item.contact.id === selectedId) ?? null;
  const inboxReady = Boolean(selected?.inbox.enabled && selected.inbox.reply_provider_config_id);

  const reloadMessages = useCallback(async () => {
    if (!selectedId) {
      setMessages([]);
      return;
    }
    try { setMessages(await api.getContactMessages(selectedId)); }
    catch (e) { setError(String(e)); }
  }, [selectedId, setError]);

  useEffect(() => { reloadMessages(); }, [reloadMessages]);

  const patchContact = async (contactId: string, patch: Parameters<typeof api.updateContact>[1]) => {
    try {
      await api.updateContact(contactId, patch);
      await reload();
      await reloadMessages();
      onChanged();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div>
      <SectionHeader title="会话" hint="按接管号聚合所有粉丝会话。这里用于观察 channel 会话，并给单个粉丝开启/关闭接管。">
        <button className="btn btn-sm btn-ghost" onClick={reload}>{loading ? '刷新中…' : '刷新'}</button>
      </SectionHeader>
      {items.length === 0 ? (
        <Empty>还没有会话。Bridge 发现 chat 会话并推送第一批消息后，这里会自动出现。</Empty>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 360px) minmax(0, 1fr)', gap: 12, alignItems: 'start' }}>
          <div style={{ display: 'grid', gap: 8 }}>
            {items.map(item => (
              <button
                key={item.contact.id}
                className="card"
                onClick={() => setSelectedId(item.contact.id)}
                style={{
                  padding: 12,
                  textAlign: 'left',
                  borderColor: selectedId === item.contact.id ? 'var(--brass-line)' : 'var(--line-subtle)',
                  background: selectedId === item.contact.id ? 'var(--brass-soft)' : 'var(--panel)',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                  <strong style={{ fontSize: 13 }}>{item.contact.display_name}</strong>
                  <span className="chip muted">{item.message_count} 条</span>
                </div>
                <div className="mono ink-3" style={{ fontSize: 11, marginTop: 4 }}>
                  {item.inbox.platform} · {item.inbox.platform_self_id || '—'}
                </div>
                <div className="ink-2" style={{ fontSize: 12, marginTop: 6, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {item.latest_message ? `${item.latest_message.role === 'self' ? '我' : '对方'}：${item.latest_message.content}` : '暂无消息'}
                </div>
                <div className="mono ink-3" style={{ fontSize: 10, marginTop: 4 }}>
                  {item.latest_message ? formatDateTime(item.latest_message.timestamp) : formatDateTime(item.contact.updated_at)}
                </div>
              </button>
            ))}
          </div>

          <div className="card" style={{ padding: 16, minHeight: 420 }}>
            {!selected ? <Empty>请选择一个会话。</Empty> : (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap', borderBottom: '1px solid var(--line-subtle)', paddingBottom: 12, marginBottom: 12 }}>
                  <div>
                    <div style={{ fontWeight: 600 }}>{selected.contact.display_name}</div>
                    <div className="mono ink-3" style={{ fontSize: 11, marginTop: 4 }}>
                      {selected.inbox.display_name} · {selected.inbox.platform} · 粉丝 ID {selected.contact.peer_platform_id}
                    </div>
                    {!inboxReady && (
                      <div className="mono" style={{ fontSize: 11, color: 'var(--warn)', marginTop: 6 }}>
                        接管号未选择 Provider 或已停用；不会自动回复。
                      </div>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                    <label style={{ fontSize: 11, color: 'var(--ink-3)' }}>人设
                      <select value={selected.contact.persona_id ?? ''} className="select" style={{ marginLeft: 6 }}
                              onChange={e => { if (e.target.value) patchContact(selected.contact.id, { persona_id: e.target.value }); }}>
                        <option value="">（未选）</option>
                        {personas.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                    </label>
                    <label className="mono" style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
                      <input type="checkbox" checked={selected.contact.autoreply_enabled}
                             onChange={e => {
                               if (e.target.checked && (!inboxReady || !selected.contact.persona_id)) {
                                 setError('需要先给接管号选择 Provider，并给这个粉丝选择人设，才能开启自动回复。');
                                 return;
                               }
                               patchContact(selected.contact.id, { autoreply_enabled: e.target.checked });
                             }} />
                      自动回复
                    </label>
                    <span className="chip muted">Provider {providers.find(p => p.id === selected.inbox.reply_provider_config_id)?.name ?? '未选'}</span>
                  </div>
                </div>

                {messages.length === 0 ? <Empty>暂无消息。</Empty> : (
                  <div style={{ display: 'grid', gap: 8, maxHeight: '62dvh', overflow: 'auto', paddingRight: 4 }}>
                    {messages.map(m => (
                      <div key={m.id} style={{ display: 'flex', justifyContent: m.role === 'self' ? 'flex-end' : 'flex-start' }}>
                        <div style={{ maxWidth: '76%' }}>
                          <div className="mono ink-3" style={{ fontSize: 10, textAlign: m.role === 'self' ? 'right' : 'left', marginBottom: 3 }}>
                            {m.role === 'self' ? '我' : selected.contact.display_name} · {formatDateTime(m.timestamp)} · {m.source}
                          </div>
                          <div style={{
                            padding: '8px 10px',
                            borderRadius: 12,
                            background: m.role === 'self' ? 'var(--brass-soft)' : 'var(--panel-2)',
                            border: '1px solid var(--line-subtle)',
                            whiteSpace: 'pre-wrap',
                            fontSize: 13,
                            lineHeight: 1.5,
                          }}>
                            {m.content}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString();
}

// ---------------------------------------------------------------------------
// Personas
// ---------------------------------------------------------------------------

function PersonasView({ personas, onChanged, setError }: { personas: Persona[]; onChanged: () => void; setError: (s: string) => void }) {
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<Persona | null>(null);
  return (
    <div>
      <SectionHeader title="人设 · Personas" hint="人设是内容资产，可被任意接管号引用">
        <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}>+ 新建人设</button>
      </SectionHeader>
      {personas.length === 0 ? <Empty>还没有人设。</Empty> : (
        <div style={{ display: 'grid', gap: 10 }}>
          {personas.map(p => (
            <div key={p.id} className="card" style={{ padding: '14px 16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontWeight: 500 }}>{p.name} <span className="chip muted">{p.status}</span></div>
                  <div className="mono ink-3" style={{ fontSize: 11, marginTop: 4 }}>
                    {p.persona_md ? `${p.persona_md.slice(0, 80)}${p.persona_md.length > 80 ? '…' : ''}` : '（空）'}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button className="btn btn-sm btn-ghost" onClick={() => setEditing(p)}>编辑</button>
                  <button className="btn btn-sm btn-ghost" style={{ color: 'var(--danger)' }} onClick={async () => {
                    if (!confirm('确认删除？被引用时会失败。')) return;
                    try { await api.deletePersona(p.id); onChanged(); } catch (e) { setError(String(e)); }
                  }}>删除</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {showCreate && <CreatePersonaModal onClose={() => setShowCreate(false)} onCreated={() => { setShowCreate(false); onChanged(); }} setError={setError} />}
      {editing && <EditPersonaModal persona={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); onChanged(); }} setError={setError} />}
    </div>
  );
}

function CreatePersonaModal({ onClose, onCreated, setError }: { onClose: () => void; onCreated: () => void; setError: (s: string) => void }) {
  const [name, setName] = useState('');
  const [md, setMd] = useState('');
  const [busy, setBusy] = useState(false);
  const handle = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try { await api.createPersona({ name: name.trim(), persona_md: md || null }); onCreated(); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  return (
    <ModalShell onClose={onClose} title="新建人设">
      <FormField label="名称"><input className="input" value={name} onChange={e => setName(e.target.value)} autoFocus /></FormField>
      <FormField label="persona_md (可空)">
        <textarea className="textarea mono" style={{ minHeight: 200 }} value={md} onChange={e => setMd(e.target.value)} />
      </FormField>
      <ModalActions onCancel={onClose} onConfirm={handle} confirmLabel={busy ? '创建中...' : '创建'} disabled={busy || !name.trim()} />
    </ModalShell>
  );
}

function EditPersonaModal({ persona, onClose, onSaved, setError }: { persona: Persona; onClose: () => void; onSaved: () => void; setError: (s: string) => void }) {
  const [name, setName] = useState(persona.name);
  const [md, setMd] = useState(persona.persona_md ?? '');
  const [busy, setBusy] = useState(false);
  const handle = async () => {
    setBusy(true);
    try { await api.updatePersona(persona.id, { name, persona_md: md || null }); onSaved(); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  return (
    <ModalShell onClose={onClose} title={`编辑人设 · ${persona.name}`}>
      <FormField label="名称"><input className="input" value={name} onChange={e => setName(e.target.value)} /></FormField>
      <FormField label="persona_md">
        <textarea className="textarea mono" style={{ minHeight: 320 }} value={md} onChange={e => setMd(e.target.value)} />
      </FormField>
      <ModalActions onCancel={onClose} onConfirm={handle} confirmLabel={busy ? '保存中...' : '保存'} disabled={busy} />
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// Providers
// ---------------------------------------------------------------------------

function ProvidersView({ providers, onChanged, setError }: { providers: ProviderConfig[]; onChanged: () => void; setError: (s: string) => void }) {
  const [showCreate, setShowCreate] = useState(false);
  return (
    <div>
      <SectionHeader title="LLM Providers" hint="OpenAI 兼容后端，每次蒸馏 / 回复时显式引用">
        <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}>+ 新建</button>
      </SectionHeader>
      {providers.length === 0 ? <Empty>还没有 Provider。</Empty> : (
        <div style={{ display: 'grid', gap: 10 }}>
          {providers.map(p => (
            <div key={p.id} className="card" style={{ padding: '14px 16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontWeight: 500 }}>{p.name}</div>
                  <div className="mono ink-3" style={{ fontSize: 11, marginTop: 4 }}>
                    {p.base_url} · model: {p.default_model} · key: {p.api_key_preview ?? '未设置'}
                  </div>
                </div>
                <button className="btn btn-sm btn-ghost" style={{ color: 'var(--danger)' }} onClick={async () => {
                  if (!confirm('确认删除？')) return;
                  try { await api.deleteProviderConfig(p.id); onChanged(); } catch (e) { setError(String(e)); }
                }}>删除</button>
              </div>
            </div>
          ))}
        </div>
      )}
      {showCreate && <CreateProviderModal onClose={() => setShowCreate(false)} onCreated={() => { setShowCreate(false); onChanged(); }} setError={setError} />}
    </div>
  );
}

function CreateProviderModal({ onClose, onCreated, setError }: { onClose: () => void; onCreated: () => void; setError: (s: string) => void }) {
  const [name, setName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('');
  const [busy, setBusy] = useState(false);
  const handle = async () => {
    if (!name.trim() || !baseUrl.trim() || !model.trim()) return;
    setBusy(true);
    try { await api.createProviderConfig({ name: name.trim(), base_url: baseUrl.trim(), api_key: apiKey || null, default_model: model.trim() }); onCreated(); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  return (
    <ModalShell onClose={onClose} title="新建 Provider Config">
      <FormField label="名称"><input className="input" value={name} onChange={e => setName(e.target.value)} placeholder="例如 Deepseek" autoFocus /></FormField>
      <FormField label="base_url"><input className="input mono" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="https://api.deepseek.com/v1" /></FormField>
      <FormField label="api_key"><input className="input mono" type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} /></FormField>
      <FormField label="default_model"><input className="input mono" value={model} onChange={e => setModel(e.target.value)} placeholder="deepseek-chat" /></FormField>
      <ModalActions onCancel={onClose} onConfirm={handle} confirmLabel={busy ? '创建中...' : '创建'} disabled={busy || !name.trim() || !baseUrl.trim() || !model.trim()} />
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// Archives
// ---------------------------------------------------------------------------

function ArchivesView({ archives, inboxes, onChanged, setError }: { archives: Archive[]; inboxes: Inbox[]; onChanged: () => void; setError: (s: string) => void }) {
  const [inboxId, setInboxId] = useState(inboxes[0]?.id ?? '');
  const [selfWxid, setSelfWxid] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (!inboxId && inboxes.length > 0) setInboxId(inboxes[0].id); }, [inboxes, inboxId]);

  const handle = async () => {
    if (!inboxId || !selfWxid.trim() || !file) return;
    setBusy(true);
    try { await api.uploadArchive(inboxId, selfWxid.trim(), file); setFile(null); setSelfWxid(''); onChanged(); }
    catch (e) { setError(String(e)); } finally { setBusy(false); }
  };

  return (
    <div>
      <SectionHeader title="聊天档案 · Archives" hint="WeFlow JSON 上传 → 落到指定接管号下，作为蒸馏来源" />
      {inboxes.length === 0 ? <Empty>还没有接管号，请先创建。</Empty> : (
        <div className="card" style={{ padding: 16, marginBottom: 18 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
            <FormField label="目标接管号">
              <select value={inboxId} onChange={e => setInboxId(e.target.value)} className="select">
                {inboxes.map(ib => <option key={ib.id} value={ib.id}>{ib.display_name}</option>)}
              </select>
            </FormField>
            <FormField label={'self_wxid (这条记录里"我"的 wxid)'}>
              <input className="input mono" value={selfWxid} onChange={e => setSelfWxid(e.target.value)} placeholder="wxid_xxxxx" />
            </FormField>
            <FormField label="WeFlow JSON">
              <input type="file" accept="application/json,.json" onChange={e => setFile(e.target.files?.[0] ?? null)} className="input" />
            </FormField>
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 10 }}>
            <button className="btn btn-primary btn-sm" onClick={handle} disabled={!inboxId || !selfWxid.trim() || !file || busy}>
              {busy ? '上传中...' : '上传并解析'}
            </button>
          </div>
        </div>
      )}
      {archives.length === 0 ? <Empty>还没有上传任何档案。</Empty> : (
        <div style={{ display: 'grid', gap: 8 }}>
          {archives.map(a => {
            const ib = inboxes.find(i => i.id === a.inbox_id);
            return (
              <div key={a.id} className="card" style={{ padding: '12px 16px' }}>
                <div style={{ fontWeight: 500 }}>{a.filename}</div>
                <div className="mono ink-3" style={{ fontSize: 11, marginTop: 4 }}>
                  inbox: {ib?.display_name || a.inbox_id} · self: {a.self_wxid} · {a.message_count.toLocaleString()} 条 · 上传 {a.uploaded_at}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Distill
// ---------------------------------------------------------------------------

function DistillView({ jobs, inboxes, personas, providers, onChanged, setError }: {
  jobs: DistillJob[];
  inboxes: Inbox[];
  personas: Persona[];
  providers: ProviderConfig[];
  onChanged: () => void;
  setError: (s: string) => void;
}) {
  const ready = inboxes.length > 0 && personas.length > 0 && providers.length > 0;
  const [showCreate, setShowCreate] = useState(false);
  const hasActive = useMemo(() => jobs.some(j => j.status === 'pending' || j.status === 'running'), [jobs]);
  useEffect(() => {
    if (!hasActive) return;
    const t = window.setInterval(onChanged, 2500);
    return () => window.clearInterval(t);
  }, [hasActive, onChanged]);
  return (
    <div>
      <SectionHeader title="蒸馏 · Distill Jobs" hint="对一个接管号的历史，蒸出一个目标人设 + 各 contact 的卡片">
        {ready
          ? <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}>+ 触发蒸馏</button>
          : <span className="mono ink-4" style={{ fontSize: 12 }}>需要先有 接管号 + 人设 + Provider</span>}
      </SectionHeader>
      {jobs.length === 0 ? <Empty>还没有蒸馏任务。</Empty> : (
        <div style={{ display: 'grid', gap: 8 }}>
          {jobs.map(j => {
            const wt = j.progress?.windows_total ?? 0;
            const wd = j.progress?.windows_done ?? 0;
            const pct = wt > 0 ? Math.round((wd / wt) * 100) : 0;
            return (
              <div key={j.id} className="card" style={{ padding: '12px 16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                  <div className="mono" style={{ fontSize: 13 }}>{j.id}</div>
                  <span className={`chip ${j.status === 'done' ? 'ok' : j.status === 'failed' ? 'danger' : j.status === 'running' ? 'live' : 'muted'}`}>{j.status}</span>
                </div>
                <div className="mono ink-3" style={{ fontSize: 11, marginTop: 4 }}>
                  inbox: {inboxes.find(i => i.id === j.source_inbox_id)?.display_name || j.source_inbox_id} →
                  persona: {personas.find(p => p.id === j.target_persona_id)?.name || j.target_persona_id} ·
                  {wt > 0 ? ` ${wd}/${wt} windows (${pct}%)` : ' 尚未开始'}
                  {j.error_message && ` · ${j.error_message.slice(0, 80)}`}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {showCreate && (
        <CreateDistillModal
          inboxes={inboxes} personas={personas} providers={providers}
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); onChanged(); }}
          setError={setError}
        />
      )}
    </div>
  );
}

function CreateDistillModal({ inboxes, personas, providers, onClose, onCreated, setError }: {
  inboxes: Inbox[];
  personas: Persona[];
  providers: ProviderConfig[];
  onClose: () => void;
  onCreated: () => void;
  setError: (s: string) => void;
}) {
  const [inboxId, setInboxId] = useState(inboxes[0]?.id ?? '');
  const [personaId, setPersonaId] = useState(personas[0]?.id ?? '');
  const [providerId, setProviderId] = useState(providers[0]?.id ?? '');
  const [busy, setBusy] = useState(false);
  const handle = async () => {
    setBusy(true);
    try {
      await api.createDistillJob({
        source_inbox_id: inboxId,
        target_persona_id: personaId,
        provider_config_id: providerId,
      });
      onCreated();
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  return (
    <ModalShell onClose={onClose} title="触发蒸馏">
      <FormField label="来源接管号"><select value={inboxId} onChange={e => setInboxId(e.target.value)} className="select">{inboxes.map(i => <option key={i.id} value={i.id}>{i.display_name}</option>)}</select></FormField>
      <FormField label="目标人设"><select value={personaId} onChange={e => setPersonaId(e.target.value)} className="select">{personas.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></FormField>
      <FormField label="Provider"><select value={providerId} onChange={e => setProviderId(e.target.value)} className="select">{providers.map(p => <option key={p.id} value={p.id}>{p.name} ({p.default_model})</option>)}</select></FormField>
      <ModalActions onCancel={onClose} onConfirm={handle} confirmLabel={busy ? '提交中...' : '开始蒸馏'} disabled={busy || !inboxId || !personaId || !providerId} />
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------

function SectionHeader({ title, hint, children }: { title: string; hint: string; children?: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
      <div>
        <h2 className="serif" style={{ fontSize: 22, margin: 0 }}>{title}</h2>
        <div className="mono ink-3" style={{ fontSize: 11, marginTop: 4 }}>{hint}</div>
      </div>
      <div>{children}</div>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="card ink-3" style={{ padding: 18, textAlign: 'center' }}>{children}</div>;
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'block', marginBottom: 12 }}>
      {label && <div className="mono ink-3" style={{ fontSize: 11, marginBottom: 4 }}>{label}</div>}
      {children}
    </label>
  );
}

function ModalShell({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'oklch(0.06 0.005 60 / 0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }} onClick={onClose}>
      <div className="card" style={{ width: 'min(560px, 92vw)', maxHeight: '85vh', overflow: 'auto', padding: 22 }} onClick={e => e.stopPropagation()}>
        <h3 className="serif" style={{ fontSize: 20, margin: '0 0 16px' }}>{title}</h3>
        {children}
      </div>
    </div>
  );
}

function ModalActions({ onCancel, onConfirm, confirmLabel, disabled }: { onCancel: () => void; onConfirm: () => void; confirmLabel: string; disabled?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
      <button className="btn btn-ghost btn-sm" onClick={onCancel}>取消</button>
      <button className="btn btn-primary btn-sm" onClick={onConfirm} disabled={disabled}>{confirmLabel}</button>
    </div>
  );
}
