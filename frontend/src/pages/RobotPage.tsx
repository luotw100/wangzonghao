import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import * as api from '../lib/api';
import type {
  Account,
  ChatArchive,
  Character,
  Contact,
  DistillJob,
  ProviderConfig,
  RobotSession,
} from '../lib/api';
import { IconArrowLeft, IconClose, IconPlus, LaborsterLogo } from '../components/Icons';
import { Modal } from '../components/Modal';
import { cn, formatDate } from '../lib/utils';

type TabKey = 'persona' | 'contacts' | 'archives' | 'distill' | 'providers';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'persona', label: '人设' },
  { key: 'contacts', label: '联系人' },
  { key: 'archives', label: '聊天记录' },
  { key: 'distill', label: '蒸馏' },
  { key: 'providers', label: 'Provider' },
];


export function RobotPage() {
  const navigate = useNavigate();
  const [me, setMe] = useState<Account | null>(null);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [providers, setProviders] = useState<ProviderConfig[]>([]);
  const [tab, setTab] = useState<TabKey>('persona');
  const [error, setError] = useState('');
  const [showCreate, setShowCreate] = useState(false);

  const active = characters.find(o => o.id === activeId) || null;

  useEffect(() => {
    api.authMe()
      .then(setMe)
      .catch(() => navigate('/login', { replace: true }));
  }, [navigate]);

  const loadCharacters = useCallback(async () => {
    try { setCharacters(await api.getCharacters()); } catch (e) { setError(String(e)); }
  }, []);

  const loadProviders = useCallback(async () => {
    try { setProviders(await api.getProviderConfigs()); } catch (e) { setError(String(e)); }
  }, []);

  useEffect(() => {
    if (!me) return;
    loadCharacters(); loadProviders();
  }, [me, loadCharacters, loadProviders]);

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

  const handleLogout = async () => {
    await api.authLogout().catch(() => {});
    navigate('/login', { replace: true });
  };

  if (!me) return null;

  return (
    <div className="w-full h-dvh flex flex-col bg-bg-primary text-text-primary tech-grid">
      <header className="h-14 flex items-center justify-between px-4 md:px-6 border-b border-border-glow/30 shrink-0 bg-bg-secondary/80 backdrop-blur-sm">
        <div className="flex items-center gap-3 min-w-0">
          <Link to="/" className="text-text-secondary hover:text-accent transition-colors">
            <IconArrowLeft size={16} />
          </Link>
          <div className="w-px h-4 bg-border-glow/30" />
          <div className="flex items-center gap-2">
            <LaborsterLogo size={20} />
            <span className="font-brand font-medium tracking-wider text-sm text-accent">Robot</span>
          </div>
          <div className="w-px h-4 bg-border-glow/30 ml-2" />
          <select
            value={activeId ?? ''}
            onChange={e => setActiveId(e.target.value || null)}
            className="bg-bg-tertiary border border-border-glow/30 rounded-lg px-3 py-1.5 text-sm outline-none focus:border-accent/50"
          >
            {characters.length === 0 && <option value="">还没有 Character</option>}
            {characters.map(o => (
              <option key={o.id} value={o.id}>{o.name}</option>
            ))}
          </select>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-border-glow/30 text-text-secondary hover:text-accent hover:border-accent/40 text-xs btn-neon"
          >
            <IconPlus size={14} /> 新建 Character
          </button>
        </div>
        <div className="flex items-center gap-3 text-xs text-text-secondary">
          <Link to="/chat" className="hover:text-accent">前往 Chat 调试 →</Link>
          {me.role === 'admin' && (
            <Link to="/admin" className="hover:text-accent">Admin →</Link>
          )}
          <span className="text-text-tertiary">·</span>
          <span>{me.email}</span>
          <button onClick={handleLogout} className="hover:text-accent">退出</button>
        </div>
      </header>

      <div className="flex border-b border-border-glow/20 bg-bg-secondary/40 shrink-0">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              'px-5 py-2.5 text-sm transition-all',
              tab === t.key ? 'text-accent border-b-2 border-accent font-medium' : 'text-text-secondary hover:text-text-primary border-b-2 border-transparent'
            )}
          >{t.label}</button>
        ))}
      </div>

      {error && (
        <div className="mx-4 mt-3 px-4 py-3 bg-danger-bg rounded-xl text-sm text-danger flex items-center justify-between shrink-0">
          <span className="break-all">{error}</span>
          <button onClick={() => setError('')} className="ml-2 text-danger hover:opacity-70">&times;</button>
        </div>
      )}

      <main className="flex-1 overflow-y-auto min-h-0">
        {!active ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-8">
            <div className="w-16 h-16 mb-6 rounded-full bg-bg-tertiary flex items-center justify-center laborster-empty-logo">
              <LaborsterLogo size={32} id="emptyChGrad" />
            </div>
            <h3 className="text-xl font-medium mb-2">还没有 Character</h3>
            <p className="text-text-secondary text-sm mb-6">创建一个 Character，然后上传聊天记录开始蒸馏</p>
            <button
              onClick={() => setShowCreate(true)}
              className="px-5 py-2 rounded-lg bg-accent/20 text-accent border border-accent/40 hover:bg-accent/30 btn-neon text-sm flex items-center gap-2"
            >
              <IconPlus /> 新建 Character
            </button>
          </div>
        ) : (
          <div className="max-w-5xl mx-auto p-4 md:p-6">
            {tab === 'persona' && (
              <PersonaPanel character={active} onSaved={refreshActive} setError={setError} />
            )}
            {tab === 'contacts' && (
              <ContactsPanel character={active} setError={setError} />
            )}
            {tab === 'archives' && (
              <ArchivesPanel character={active} setError={setError} />
            )}
            {tab === 'distill' && (
              <DistillPanel character={active} setError={setError} />
            )}
            {tab === 'providers' && (
              <ProvidersPanel
                character={active}
                providers={providers}
                onChange={async () => { await loadProviders(); await refreshActive(); }}
                setError={setError}
              />
            )}
          </div>
        )}
      </main>

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


// ============================================================================
// Persona panel
// ============================================================================

function PersonaPanel({
  character, onSaved, setError,
}: { character: Character; onSaved: () => void; setError: (s: string) => void }) {
  const [draft, setDraft] = useState(character.persona_md ?? '');
  const [saving, setSaving] = useState(false);
  useEffect(() => { setDraft(character.persona_md ?? ''); }, [character.id, character.persona_md]);

  const dirty = draft !== (character.persona_md ?? '');

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updateCharacter(character.id, { persona_md: draft });
      onSaved();
    } catch (e) { setError(String(e)); } finally { setSaving(false); }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-medium">人设档案</h2>
          <p className="text-xs text-text-secondary mt-1">蒸馏后在此校对；运行时直接注入 system prompt。</p>
        </div>
        <div className="text-xs text-text-tertiary">
          {character.persona_md ? `更新于 ${formatDate(character.updated_at)}` : '尚未蒸馏'}
        </div>
      </div>
      <textarea
        value={draft}
        onChange={e => setDraft(e.target.value)}
        placeholder="（空——上传聊天记录并蒸馏后会自动填充，也可以直接手写）"
        className="w-full h-[60vh] bg-bg-tertiary/60 border border-border-glow/20 rounded-xl px-4 py-3 text-sm font-mono outline-none input-glow resize-none"
      />
      <div className="mt-3 flex justify-end gap-2">
        <button
          disabled={!dirty || saving}
          onClick={() => setDraft(character.persona_md ?? '')}
          className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary disabled:opacity-30"
        >还原</button>
        <button
          disabled={!dirty || saving}
          onClick={handleSave}
          className="px-5 py-2 rounded-lg bg-accent/20 text-accent border border-accent/40 hover:bg-accent/30 disabled:opacity-30 btn-neon text-sm"
        >{saving ? '保存中...' : '保存'}</button>
      </div>
    </div>
  );
}


// ============================================================================
// Contacts panel
// ============================================================================

function ContactsPanel({
  character, setError,
}: { character: Character; setError: (s: string) => void }) {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [sessions, setSessions] = useState<RobotSession[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [cs, ss] = await Promise.all([
        api.getContacts(character.id),
        api.getSessions(character.id),
      ]);
      setContacts(cs);
      setSessions(ss);
    } catch (e) { setError(String(e)); }
  }, [character.id, setError]);

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <div className="mb-4">
        <h2 className="text-lg font-medium">联系人</h2>
        <p className="text-xs text-text-secondary mt-1">{contacts.length} 人 · 卡片由蒸馏自动生成，可手动校对。</p>
      </div>
      {contacts.length === 0 ? (
        <div className="text-sm text-text-secondary py-8 text-center border border-border-glow/20 rounded-xl">
          还没有联系人。上传聊天记录后会自动识别。
        </div>
      ) : (
        <div className="space-y-2">
          {contacts.map(c => {
            const session = sessions.find(s => s.contact_id === c.id) || null;
            const expanded = openId === c.id;
            return (
              <ContactRow
                key={c.id}
                contact={c}
                session={session}
                expanded={expanded}
                onToggle={() => setOpenId(expanded ? null : c.id)}
                onSaved={load}
                setError={setError}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

function ContactRow({
  contact, session, expanded, onToggle, onSaved, setError,
}: {
  contact: Contact;
  session: RobotSession | null;
  expanded: boolean;
  onToggle: () => void;
  onSaved: () => void;
  setError: (s: string) => void;
}) {
  const [draft, setDraft] = useState(contact.card_md ?? '');
  const [name, setName] = useState(contact.display_name);
  const [saving, setSaving] = useState(false);
  useEffect(() => { setDraft(contact.card_md ?? ''); setName(contact.display_name); }, [contact.id, contact.card_md, contact.display_name]);

  const dirty = draft !== (contact.card_md ?? '') || name !== contact.display_name;

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.updateContact(contact.id, { card_md: draft, display_name: name });
      onSaved();
    } catch (e) { setError(String(e)); } finally { setSaving(false); }
  };

  return (
    <div className="border border-border-glow/20 rounded-xl bg-bg-secondary/50 overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-bg-tertiary/40 transition-colors"
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-8 h-8 rounded-full bg-accent/20 flex items-center justify-center text-xs font-bold text-accent shrink-0">
            {contact.display_name[0]}
          </div>
          <div className="text-left min-w-0">
            <div className="text-sm font-medium truncate">{contact.display_name}</div>
            <div className="text-xs text-text-tertiary truncate">
              wxid: {contact.wechat_wxid || '—'} · chat: {contact.chat_user_id || '—'}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs text-text-tertiary shrink-0">
          {contact.card_md ? '已蒸馏' : '未蒸馏'}
          <span className="text-text-secondary">{expanded ? '收起' : '展开'}</span>
        </div>
      </button>
      {expanded && (
        <div className="border-t border-border-glow/20 p-4 space-y-3">
          <div>
            <label className="text-xs text-text-secondary mb-1 block">备注名</label>
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              className="w-full bg-bg-tertiary/60 border border-border-glow/20 rounded-lg px-3 py-2 text-sm outline-none input-glow"
            />
          </div>
          <div>
            <label className="text-xs text-text-secondary mb-1 block">联系人卡片 (markdown / yaml)</label>
            <textarea
              value={draft}
              onChange={e => setDraft(e.target.value)}
              placeholder="（空——蒸馏后会填充结构化卡片）"
              className="w-full h-64 bg-bg-tertiary/60 border border-border-glow/20 rounded-lg px-3 py-2 text-sm font-mono outline-none input-glow resize-none"
            />
          </div>
          {session && (
            <div className="text-xs text-text-secondary">
              对应 chat 会话: <code className="text-accent">{session.adapter_thread_id}</code> ·{' '}
              <Link to="/chat" className="text-accent hover:underline">前往 Chat 调试</Link>
            </div>
          )}
          <div className="flex justify-end gap-2 pt-2">
            <button
              disabled={!dirty || saving}
              onClick={() => { setDraft(contact.card_md ?? ''); setName(contact.display_name); }}
              className="px-4 py-1.5 text-sm text-text-secondary hover:text-text-primary disabled:opacity-30"
            >还原</button>
            <button
              disabled={!dirty || saving}
              onClick={handleSave}
              className="px-4 py-1.5 rounded-lg bg-accent/20 text-accent border border-accent/40 hover:bg-accent/30 disabled:opacity-30 btn-neon text-sm"
            >{saving ? '保存中...' : '保存'}</button>
          </div>
        </div>
      )}
    </div>
  );
}


// ============================================================================
// Archives panel
// ============================================================================

function ArchivesPanel({
  character, setError,
}: { character: Character; setError: (s: string) => void }) {
  const [archives, setArchives] = useState<ChatArchive[]>([]);
  const [selfWxid, setSelfWxid] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try { setArchives(await api.getArchives(character.id)); } catch (e) { setError(String(e)); }
  }, [character.id, setError]);

  useEffect(() => { load(); }, [load]);

  const handleUpload = async () => {
    if (!file || !selfWxid.trim()) return;
    setUploading(true);
    try {
      await api.uploadArchive(character.id, file, selfWxid.trim());
      setFile(null);
      setSelfWxid('');
      if (fileInputRef.current) fileInputRef.current.value = '';
      await load();
    } catch (e) { setError(String(e)); } finally { setUploading(false); }
  };

  return (
    <div>
      <div className="mb-4">
        <h2 className="text-lg font-medium">聊天记录</h2>
        <p className="text-xs text-text-secondary mt-1">
          上传 WeFlow JSON 导出。每个文件对应一个粉丝的聊天记录（暂只支持 1 对 1）。
        </p>
      </div>

      <div className="border border-border-glow/20 rounded-xl bg-bg-secondary/50 p-4 mb-6 space-y-3">
        <div>
          <label className="text-xs text-text-secondary mb-1 block">主播本人的 wxid（必须出现在聊天记录中）</label>
          <input
            value={selfWxid}
            onChange={e => setSelfWxid(e.target.value)}
            placeholder="wxid_xxxxx"
            className="w-full bg-bg-tertiary/60 border border-border-glow/20 rounded-lg px-3 py-2 text-sm outline-none input-glow font-mono"
          />
        </div>
        <div>
          <label className="text-xs text-text-secondary mb-1 block">WeFlow JSON 文件</label>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/json,.json"
            onChange={e => setFile(e.target.files?.[0] ?? null)}
            className="block w-full text-sm text-text-primary file:mr-3 file:px-3 file:py-1.5 file:rounded-lg file:border-0 file:bg-accent/20 file:text-accent hover:file:bg-accent/30 cursor-pointer"
          />
        </div>
        <div className="flex justify-end">
          <button
            onClick={handleUpload}
            disabled={!file || !selfWxid.trim() || uploading}
            className="px-5 py-2 rounded-lg bg-accent/20 text-accent border border-accent/40 hover:bg-accent/30 disabled:opacity-30 btn-neon text-sm"
          >{uploading ? '上传中...' : '上传'}</button>
        </div>
      </div>

      {archives.length === 0 ? (
        <div className="text-sm text-text-secondary py-8 text-center border border-border-glow/20 rounded-xl">
          还没有上传任何聊天记录。
        </div>
      ) : (
        <div className="space-y-2">
          {archives.map(a => (
            <div key={a.id} className="border border-border-glow/20 rounded-xl bg-bg-secondary/50 px-4 py-3">
              <div className="text-sm font-medium truncate">{a.filename}</div>
              <div className="text-xs text-text-tertiary mt-0.5">
                self: {a.self_wxid} · {a.message_count} 条消息 · {a.contact_count} 个联系人 · {formatDate(a.uploaded_at)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


// ============================================================================
// Distill panel
// ============================================================================

function DistillPanel({
  character, setError,
}: { character: Character; setError: (s: string) => void }) {
  const [jobs, setJobs] = useState<DistillJob[]>([]);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try { setJobs(await api.getDistillJobs(character.id)); } catch (e) { setError(String(e)); }
  }, [character.id, setError]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const hasActive = jobs.some(j => j.status === 'pending' || j.status === 'running');
    if (!hasActive) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [jobs, load]);

  const handleCreate = async () => {
    setCreating(true);
    try {
      await api.createDistillJob(character.id);
      await load();
    } catch (e) { setError(String(e)); } finally { setCreating(false); }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-medium">蒸馏</h2>
          <p className="text-xs text-text-secondary mt-1">
            从 upload 聊天记录中提取 Persona + Contact Cards。Worker 进程后台执行。
          </p>
        </div>
        <button
          onClick={handleCreate}
          disabled={creating || !character.provider_config_id}
          className="px-5 py-2 rounded-lg bg-accent/20 text-accent border border-accent/40 hover:bg-accent/30 disabled:opacity-30 btn-neon text-sm"
          title={!character.provider_config_id ? '请先在 Provider tab 选择 Provider' : ''}
        >{creating ? '创建中...' : '开始蒸馏'}</button>
      </div>

      {jobs.length === 0 ? (
        <div className="text-sm text-text-secondary py-8 text-center border border-border-glow/20 rounded-xl">
          还没有蒸馏任务。
        </div>
      ) : (
        <div className="space-y-2">
          {jobs.map(j => <DistillJobRow key={j.id} job={j} />)}
        </div>
      )}
    </div>
  );
}

function DistillJobRow({ job }: { job: DistillJob }) {
  const statusColor: Record<DistillJob['status'], string> = {
    pending: 'text-text-secondary',
    running: 'text-accent',
    done: 'text-success',
    failed: 'text-danger',
  };
  const wt = job.progress.windows_total ?? 0;
  const wd = job.progress.windows_done ?? 0;
  const ct = job.progress.contacts_total ?? 0;
  const cd = job.progress.contacts_done ?? 0;

  return (
    <div className="border border-border-glow/20 rounded-xl bg-bg-secondary/50 px-4 py-3">
      <div className="flex items-center justify-between mb-1">
        <div className="text-sm font-mono">{job.id}</div>
        <div className={cn('text-xs font-medium', statusColor[job.status])}>{job.status}</div>
      </div>
      <div className="text-xs text-text-secondary">
        {wt > 0 ? `${wd}/${wt} windows · ${cd}/${ct} contacts` : '尚未开始'}
        {' · '}{formatDate(job.created_at)}
      </div>
      {wt > 0 && (
        <div className="mt-2 h-1 bg-bg-tertiary rounded-full overflow-hidden">
          <div
            className="h-full bg-accent transition-all"
            style={{ width: `${Math.round((wd / wt) * 100)}%` }}
          />
        </div>
      )}
      {job.error_message && (
        <div className="mt-2 text-xs text-danger break-all">{job.error_message}</div>
      )}
    </div>
  );
}


// ============================================================================
// Providers panel
// ============================================================================

function ProvidersPanel({
  character, providers, onChange, setError,
}: {
  character: Character;
  providers: ProviderConfig[];
  onChange: () => Promise<void>;
  setError: (s: string) => void;
}) {
  const [showCreate, setShowCreate] = useState(false);

  const setCharacterProvider = async (pid: string | null) => {
    try {
      await api.updateCharacter(character.id, { provider_config_id: pid });
      await onChange();
    } catch (e) { setError(String(e)); }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('确认删除此 Provider Config？')) return;
    try {
      await api.deleteProviderConfig(id);
      await onChange();
    } catch (e) { setError(String(e)); }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-medium">LLM Provider</h2>
          <p className="text-xs text-text-secondary mt-1">
            当前 Character 绑定: <span className="text-accent">{character.provider_config?.name || '未绑定'}</span>
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-accent/20 text-accent border border-accent/40 hover:bg-accent/30 btn-neon text-sm"
        ><IconPlus size={14} /> 新建</button>
      </div>

      {providers.length === 0 ? (
        <div className="text-sm text-text-secondary py-8 text-center border border-border-glow/20 rounded-xl">
          还没有 Provider Config。
        </div>
      ) : (
        <div className="space-y-2">
          {providers.map(p => {
            const bound = character.provider_config_id === p.id;
            return (
              <div key={p.id} className={cn(
                'border rounded-xl px-4 py-3 flex items-center justify-between',
                bound ? 'border-accent/40 bg-accent/5' : 'border-border-glow/20 bg-bg-secondary/50'
              )}>
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate">
                    {p.name} <span className="text-text-tertiary text-xs ml-2">{p.default_model}</span>
                  </div>
                  <div className="text-xs text-text-tertiary mt-0.5 truncate">
                    {p.base_url} · key: {p.api_key_preview || '未设置'}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {bound ? (
                    <span className="text-xs text-accent">已绑定</span>
                  ) : (
                    <button
                      onClick={() => setCharacterProvider(p.id)}
                      className="text-xs text-text-secondary hover:text-accent"
                    >绑定</button>
                  )}
                  <button
                    onClick={() => handleDelete(p.id)}
                    className="text-text-tertiary hover:text-danger transition"
                    title="删除"
                  ><IconClose size={14} /></button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <CreateProviderModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreated={async () => { setShowCreate(false); await onChange(); }}
        setError={setError}
      />
    </div>
  );
}


// ============================================================================
// Modals
// ============================================================================

function CreateCharacterModal({
  open, providers, onClose, onCreated, setError,
}: {
  open: boolean;
  providers: ProviderConfig[];
  onClose: () => void;
  onCreated: (c: Character) => void;
  setError: (s: string) => void;
}) {
  const [name, setName] = useState('');
  const [providerId, setProviderId] = useState<string>('');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (!open) { setName(''); return; }
    if (providers.length > 0 && !providerId) setProviderId(providers[0].id);
  }, [open, providers, providerId]);

  const handle = async () => {
    if (!name.trim()) return;
    setCreating(true);
    try {
      const c = await api.createCharacter({
        name: name.trim(),
        provider_config_id: providerId || null,
      });
      onCreated(c);
    } catch (e) { setError(String(e)); } finally { setCreating(false); }
  };

  return (
    <Modal open={open} onClose={onClose}>
      <h3 className="text-lg font-medium mb-4">新建 Character</h3>
      <div className="space-y-3 mb-4">
        <div>
          <label className="text-xs text-text-secondary mb-1 block">姓名</label>
          <input
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Character 显示名"
            autoFocus
            className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50"
          />
        </div>
        <div>
          <label className="text-xs text-text-secondary mb-1 block">Provider Config</label>
          <select
            value={providerId}
            onChange={e => setProviderId(e.target.value)}
            className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50"
          >
            <option value="">（不绑定，稍后再选）</option>
            {providers.map(p => (
              <option key={p.id} value={p.id}>{p.name} ({p.default_model})</option>
            ))}
          </select>
          <p className="text-xs text-text-tertiary mt-1">创建后会自动在 chat 服务里建一个对应的 user。</p>
        </div>
      </div>
      <div className="flex justify-end gap-3">
        <button onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">取消</button>
        <button
          onClick={handle}
          disabled={!name.trim() || creating}
          className="px-4 py-2 text-sm bg-accent/20 text-accent rounded-lg hover:bg-accent/30 disabled:opacity-30"
        >{creating ? '创建中...' : '创建'}</button>
      </div>
    </Modal>
  );
}

function CreateProviderModal({
  open, onClose, onCreated, setError,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
  setError: (s: string) => void;
}) {
  const [name, setName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (!open) { setName(''); setBaseUrl(''); setApiKey(''); setModel(''); }
  }, [open]);

  const handle = async () => {
    if (!name.trim() || !baseUrl.trim() || !model.trim()) return;
    setCreating(true);
    try {
      await api.createProviderConfig({
        name: name.trim(),
        base_url: baseUrl.trim(),
        api_key: apiKey || null,
        default_model: model.trim(),
      });
      onCreated();
    } catch (e) { setError(String(e)); } finally { setCreating(false); }
  };

  return (
    <Modal open={open} onClose={onClose}>
      <h3 className="text-lg font-medium mb-4">新建 Provider Config</h3>
      <div className="space-y-3 mb-4">
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="名称（如 Deepseek）"
          className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50"
        />
        <input
          value={baseUrl}
          onChange={e => setBaseUrl(e.target.value)}
          placeholder="base_url（如 https://api.deepseek.com/v1）"
          className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50 font-mono"
        />
        <input
          value={apiKey}
          onChange={e => setApiKey(e.target.value)}
          type="password"
          placeholder="api_key"
          className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50 font-mono"
        />
        <input
          value={model}
          onChange={e => setModel(e.target.value)}
          placeholder="default_model（如 deepseek-chat）"
          className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50 font-mono"
        />
      </div>
      <div className="flex justify-end gap-3">
        <button onClick={onClose} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">取消</button>
        <button
          onClick={handle}
          disabled={!name.trim() || !baseUrl.trim() || !model.trim() || creating}
          className="px-4 py-2 text-sm bg-accent/20 text-accent rounded-lg hover:bg-accent/30 disabled:opacity-30"
        >{creating ? '创建中...' : '创建'}</button>
      </div>
    </Modal>
  );
}
