import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import * as api from '../lib/api';
import type {
  Archive,
  Contact,
  DistillJob,
  Inbox,
  InboxWithToken,
  Persona,
  ProviderConfig,
} from '../lib/api';
import { useAuth } from '../lib/auth';

type Tab = 'personas' | 'inboxes' | 'providers' | 'archives' | 'distill';

export function RobotPage() {
  const navigate = useNavigate();
  const { account: me, logout } = useAuth();
  const [tab, setTab] = useState<Tab>('inboxes');
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [inboxes, setInboxes] = useState<Inbox[]>([]);
  const [providers, setProviders] = useState<ProviderConfig[]>([]);
  const [archives, setArchives] = useState<Archive[]>([]);
  const [jobs, setJobs] = useState<DistillJob[]>([]);
  const [error, setError] = useState('');
  const [tokenJustIssued, setTokenJustIssued] = useState<{ inbox: InboxWithToken } | null>(null);

  const loadAll = useCallback(async () => {
    try {
      const [ps, ibs, pcs, ars, djs] = await Promise.all([
        api.getPersonas(),
        api.getInboxes(),
        api.getProviderConfigs(),
        api.getArchives(),
        api.getDistillJobs(),
      ]);
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
          <span className="font-brand" style={{ fontSize: 18, color: 'var(--accent)' }}>Laborster Robot</span>
          <nav style={{ display: 'flex', gap: 8 }}>
            {(['inboxes', 'personas', 'providers', 'archives', 'distill'] as Tab[]).map(t => (
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
        {tab === 'inboxes' && (
          <InboxesView
            inboxes={inboxes} personas={personas} providers={providers}
            onChanged={loadAll} setError={setError}
            onTokenIssued={(ib) => setTokenJustIssued({ inbox: ib })}
          />
        )}
        {tab === 'personas' && <PersonasView personas={personas} onChanged={loadAll} setError={setError} />}
        {tab === 'providers' && <ProvidersView providers={providers} onChanged={loadAll} setError={setError} />}
        {tab === 'archives' && <ArchivesView archives={archives} inboxes={inboxes} onChanged={loadAll} setError={setError} />}
        {tab === 'distill' && <DistillView jobs={jobs} inboxes={inboxes} personas={personas} providers={providers} onChanged={loadAll} setError={setError} />}
      </main>

      {tokenJustIssued && (
        <TokenModal inbox={tokenJustIssued.inbox} onClose={() => setTokenJustIssued(null)} />
      )}
    </div>
  );
}

function tabLabel(t: Tab): string {
  return { inboxes: '接管号', personas: '人设', providers: 'Provider', archives: '聊天档案', distill: '蒸馏' }[t];
}

// ---------------------------------------------------------------------------
// Inboxes view
// ---------------------------------------------------------------------------

function InboxesView({ inboxes, personas, providers, onChanged, setError, onTokenIssued }: {
  inboxes: Inbox[];
  personas: Persona[];
  providers: ProviderConfig[];
  onChanged: () => void;
  setError: (s: string) => void;
  onTokenIssued: (ib: InboxWithToken) => void;
}) {
  const [showCreate, setShowCreate] = useState(false);
  const [contactsOf, setContactsOf] = useState<string | null>(null);
  return (
    <div>
      <SectionHeader title="接管号 · Inboxes" hint="一个接管号 = 一个 platform 登录 = 一个 Bridge daemon">
        {personas.length === 0
          ? <span className="mono ink-4" style={{ fontSize: 12 }}>请先在「人设」里建至少一个</span>
          : <button className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}>+ 新增接管号</button>}
      </SectionHeader>
      {inboxes.length === 0 ? (
        <Empty>还没有接管号。</Empty>
      ) : (
        <div style={{ display: 'grid', gap: 10 }}>
          {inboxes.map(ib => (
            <div key={ib.id} className="card" style={{ padding: '14px 16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
                <div>
                  <div style={{ fontWeight: 500, display: 'flex', alignItems: 'center', gap: 8 }}>
                    <StatusDot status={ib.b_status} />
                    {ib.display_name}
                    <span className="chip muted">{ib.platform}</span>
                    {!ib.enabled && <span className="chip warn">disabled</span>}
                  </div>
                  <div className="mono ink-3" style={{ fontSize: 11, marginTop: 4 }}>
                    self: {ib.platform_self_id || '—'} · host: {ib.hostname || '—'} · default persona: {personaName(personas, ib.default_persona_id)} · reply provider: {providerName(providers, ib.reply_provider_config_id)}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button className="btn btn-sm btn-ghost" onClick={() => setContactsOf(contactsOf === ib.id ? null : ib.id)}>
                    {contactsOf === ib.id ? '收起 contacts' : 'contacts'}
                  </button>
                  <button className="btn btn-sm btn-ghost" onClick={async () => {
                    try {
                      const next = !ib.enabled;
                      await api.updateInbox(ib.id, { enabled: next });
                      onChanged();
                    } catch (e) { setError(String(e)); }
                  }}>{ib.enabled ? '停用' : '启用'}</button>
                  <button className="btn btn-sm btn-ghost" onClick={async () => {
                    if (!confirm('重新生成 token 会让旧 token 失效，确认？')) return;
                    try {
                      const fresh = await api.regenerateInboxToken(ib.id);
                      onTokenIssued(fresh);
                      onChanged();
                    } catch (e) { setError(String(e)); }
                  }}>重发 token</button>
                  <button className="btn btn-sm btn-ghost" style={{ color: 'var(--danger)' }} onClick={async () => {
                    if (!confirm('确认 revoke 这个接管号？所有 pending 的 outbound 会被取消。')) return;
                    try {
                      await api.deleteInbox(ib.id);
                      onChanged();
                    } catch (e) { setError(String(e)); }
                  }}>revoke</button>
                </div>
              </div>
              {contactsOf === ib.id && <InboxContacts inboxId={ib.id} personas={personas} setError={setError} onChanged={onChanged} />}
            </div>
          ))}
        </div>
      )}
      {showCreate && (
        <CreateInboxModal
          personas={personas}
          providers={providers}
          onClose={() => setShowCreate(false)}
          onCreated={(ib) => { setShowCreate(false); onTokenIssued(ib); onChanged(); }}
          setError={setError}
        />
      )}
    </div>
  );
}

function providerName(providers: ProviderConfig[], id: string | null): string {
  if (!id) return '未绑定';
  return providers.find(p => p.id === id)?.name || id;
}

function StatusDot({ status }: { status: Inbox['b_status'] }) {
  const color =
    status === 'online' ? 'var(--accent)' :
    status === 'paired_pending' ? 'var(--warn)' :
    status === 'revoked' ? 'var(--danger)' : 'var(--ink-3)';
  return <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 99, background: color }} />;
}

function personaName(personas: Persona[], id: string): string {
  return personas.find(p => p.id === id)?.name || id;
}

function InboxContacts({ inboxId, personas, setError, onChanged }: { inboxId: string; personas: Persona[]; setError: (s: string) => void; onChanged: () => void }) {
  const [contacts, setContacts] = useState<Contact[]>([]);
  useEffect(() => {
    api.getInboxContacts(inboxId).then(setContacts).catch(e => setError(String(e)));
  }, [inboxId, setError]);
  if (contacts.length === 0) return <div className="ink-3" style={{ fontSize: 12, marginTop: 12 }}>该接管号还没有 contacts。Bridge 上线收到第一条消息后会自动出现。</div>;
  return (
    <div style={{ marginTop: 12, borderTop: '1px solid var(--line-subtle)', paddingTop: 12 }}>
      {contacts.map(c => (
        <div key={c.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '6px 0', borderBottom: '1px dashed var(--line-subtle)' }}>
          <span style={{ fontSize: 13, flex: 1 }}>{c.display_name} <span className="mono ink-4" style={{ fontSize: 10 }}>· {c.peer_platform_id}</span></span>
          <select
            value={c.persona_id}
            onChange={async (e) => { try { await api.updateContact(c.id, { persona_id: e.target.value }); onChanged(); } catch (err) { setError(String(err)); } }}
            className="select"
            style={{ minWidth: 130 }}
          >
            {personas.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <label className="mono" style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
            <input type="checkbox" checked={c.autoreply_enabled} onChange={async (e) => { try { await api.updateContact(c.id, { autoreply_enabled: e.target.checked }); onChanged(); } catch (err) { setError(String(err)); } }} />
            autoreply
          </label>
        </div>
      ))}
    </div>
  );
}

function CreateInboxModal({ personas, providers, onClose, onCreated, setError }: {
  personas: Persona[];
  providers: ProviderConfig[];
  onClose: () => void;
  onCreated: (ib: InboxWithToken) => void;
  setError: (s: string) => void;
}) {
  const [platform, setPlatform] = useState('chat');
  const [displayName, setDisplayName] = useState('');
  const [defaultPersonaId, setDefaultPersonaId] = useState(personas[0]?.id ?? '');
  const [replyProviderId, setReplyProviderId] = useState<string>('');
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);
  const handle = async () => {
    if (!displayName.trim() || !defaultPersonaId) return;
    setBusy(true);
    try {
      const ib = await api.createInbox({
        platform: platform.trim(),
        display_name: displayName.trim(),
        default_persona_id: defaultPersonaId,
        reply_provider_config_id: replyProviderId || null,
        enabled,
      });
      onCreated(ib);
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  };
  return (
    <ModalShell onClose={onClose} title="新建接管号">
      <FormField label="Platform">
        <select value={platform} onChange={e => setPlatform(e.target.value)} className="select">
          <option value="chat">chat (sandbox)</option>
          <option value="wechat">wechat</option>
          <option value="feishu">feishu</option>
          <option value="qq">qq</option>
        </select>
      </FormField>
      <FormField label="显示名">
        <input className="input" value={displayName} onChange={e => setDisplayName(e.target.value)} placeholder="例如：MacBook 调试 / lily 工作机" autoFocus />
      </FormField>
      <FormField label="默认人设">
        <select value={defaultPersonaId} onChange={e => setDefaultPersonaId(e.target.value)} className="select">
          {personas.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </FormField>
      <FormField label="自动回复用的 Provider (可空)">
        <select value={replyProviderId} onChange={e => setReplyProviderId(e.target.value)} className="select">
          <option value="">（不绑定，autoreply 不会触发）</option>
          {providers.map(p => <option key={p.id} value={p.id}>{p.name} ({p.default_model})</option>)}
        </select>
      </FormField>
      <FormField label="">
        <label className="mono" style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
          <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} />
          创建后立即启用（master switch）
        </label>
      </FormField>
      <ModalActions onCancel={onClose} onConfirm={handle} confirmLabel={busy ? '创建中...' : '创建并生成 token'} disabled={busy || !displayName.trim() || !defaultPersonaId} />
    </ModalShell>
  );
}

function TokenModal({ inbox, onClose }: { inbox: InboxWithToken; onClose: () => void }) {
  return (
    <ModalShell onClose={onClose} title="Bridge token (仅显示一次)">
      <p className="ink-2" style={{ fontSize: 13, marginBottom: 12 }}>
        把下面这一段复制到 Bridge daemon 启动命令里。窗口关闭后无法再看到，丢失只能 revoke 重发。
      </p>
      <pre className="card mono" style={{ padding: 14, fontSize: 12, lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{`b run \\
  --robot-url <你的 robot 地址> \\
  --inbox-id ${inbox.id} \\
  --token ${inbox.b_token}`}</pre>
      <ModalActions onCancel={onClose} onConfirm={onClose} confirmLabel="我已复制" />
    </ModalShell>
  );
}

// ---------------------------------------------------------------------------
// Personas view
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
                    {p.persona_md ? `${p.persona_md.slice(0, 80)}${p.persona_md.length > 80 ? '…' : ''}` : '（空，等蒸馏或手写）'}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button className="btn btn-sm btn-ghost" onClick={() => setEditing(p)}>编辑</button>
                  <button className="btn btn-sm btn-ghost" style={{ color: 'var(--danger)' }} onClick={async () => {
                    if (!confirm('确认删除人设？(被引用时会失败)')) return;
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
// Providers view
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
// Archives view
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
    try {
      await api.uploadArchive(inboxId, selfWxid.trim(), file);
      setFile(null);
      setSelfWxid('');
      onChanged();
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
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
            <FormField label={'self_wxid (这条记录里的"我")'}>
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
                  inbox: {ib?.display_name || a.inbox_id} · self: {a.self_wxid} · {a.message_count.toLocaleString()} 条消息 · 上传 {a.uploaded_at}
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
// Distill view
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

  // Auto-poll while there's a running job
  const hasActive = useMemo(() => jobs.some(j => j.status === 'pending' || j.status === 'running'), [jobs]);
  useEffect(() => {
    if (!hasActive) return;
    const t = window.setInterval(onChanged, 2500);
    return () => window.clearInterval(t);
  }, [hasActive, onChanged]);

  return (
    <div>
      <SectionHeader title="蒸馏 · Distill Jobs" hint="对一个接管号的历史，蒸馏更新一个目标人设和它的 contact cards">
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
