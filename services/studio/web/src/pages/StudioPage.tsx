import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import * as api from '../lib/api';
import type {
  Bridge,
  Contact,
  ContactSummary,
  ConversationSummary,
  Inbox,
  Message,
  Persona,
  PersonaSummary,
} from '../lib/api';
import { useAuth } from '../lib/auth';

type Tab = 'takeover' | 'persona' | 'device';
type ChangeHandler = () => void | Promise<void>;

const NAV: { id: Tab; label: string; icon: string }[] = [
  { id: 'takeover', label: '接管', icon: '◇' },
  { id: 'persona', label: '人设', icon: '✶' },
  { id: 'device', label: '设备', icon: '⌥' },
];

const TAB_CONTEXT: Record<Tab, { ctx: string; sub: string }> = {
  takeover: { ctx: '接管', sub: '你负责的所有粉丝' },
  persona: { ctx: '人设', sub: '你可以扮演的人设' },
  device: { ctx: '设备', sub: '主播电脑上的接入程序' },
};

export function StudioPage() {
  const navigate = useNavigate();
  const { account: me, logout } = useAuth();
  const [tab, setTab] = useState<Tab>('takeover');
  const [bridges, setBridges] = useState<Bridge[]>([]);
  const [personas, setPersonas] = useState<PersonaSummary[]>([]);
  const [inboxes, setInboxes] = useState<Inbox[]>([]);
  const [error, setError] = useState('');
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const [showChangePassword, setShowChangePassword] = useState(false);

  const loadAll = useCallback(async () => {
    try {
      const [nextBridges, nextPersonas, nextInboxes] = await Promise.all([
        api.getBridges(),
        api.getPersonas(),
        api.getInboxes(),
      ]);
      setBridges(nextBridges);
      setPersonas(nextPersonas);
      setInboxes(nextInboxes);
    } catch (err) {
      setError(String(err));
    }
  }, []);

  useEffect(() => {
    loadAll();
    const id = setInterval(loadAll, 10_000);
    return () => clearInterval(id);
  }, [loadAll]);

  const handleLogout = async () => {
    await logout();
    navigate('/', { replace: true });
  };

  const onlineBridges = useMemo(() => bridges.filter(bridge => bridge.status === 'online').length, [bridges]);
  const totalBridges = bridges.length;

  if (!me) return null;

  return (
    <div className="lab-screen" style={{ display: 'flex', height: '100dvh' }}>
      <aside
        style={{
          width: 64,
          flex: '0 0 64px',
          background: 'var(--bg-base)',
          borderRight: '1px solid var(--line-subtle)',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          padding: '14px 0',
        }}
      >
        <span className="lab-mark" style={{ marginBottom: 18 }} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, width: '100%', alignItems: 'center' }}>
          {NAV.map(item => {
            const active = tab === item.id;
            return (
              <button
                key={item.id}
                title={item.label}
                onClick={() => setTab(item.id)}
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: 10,
                  border: 'none',
                  background: active ? 'var(--brass-soft)' : 'transparent',
                  color: active ? 'var(--brass)' : 'var(--ink-3)',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  justifyContent: 'center',
                  cursor: 'pointer',
                  position: 'relative',
                  fontFamily: 'var(--f-serif)',
                }}
              >
                <span style={{ fontSize: 16 }}>{item.icon}</span>
                <span className="mono" style={{ marginTop: 2, fontSize: 9, opacity: 0.85 }}>{item.label}</span>
                {active && (
                  <span
                    style={{
                      position: 'absolute',
                      left: 0,
                      top: 8,
                      bottom: 8,
                      width: 2,
                      background: 'var(--brass)',
                      borderRadius: 2,
                    }}
                  />
                )}
              </button>
            );
          })}
        </div>
        <div style={{ marginTop: 'auto', position: 'relative' }}>
          {accountMenuOpen && (
            <>
              <div
                onClick={() => setAccountMenuOpen(false)}
                style={{ position: 'fixed', inset: 0, zIndex: 40 }}
              />
              <div
                style={{
                  position: 'absolute',
                  left: 'calc(100% + 8px)',
                  bottom: 0,
                  zIndex: 41,
                  minWidth: 168,
                  background: 'var(--bg-raised)',
                  border: '1px solid var(--line)',
                  borderRadius: 10,
                  padding: 6,
                  display: 'grid',
                  gap: 2,
                  boxShadow: 'var(--shadow)',
                }}
              >
                <div className="ink-3" style={{ fontSize: 11, padding: '6px 10px' }}>@{me.username}</div>
                <button
                  className="btn btn-ghost btn-sm"
                  style={{ justifyContent: 'flex-start' }}
                  onClick={() => { setAccountMenuOpen(false); setShowChangePassword(true); }}
                >
                  修改密码
                </button>
                <button
                  className="btn btn-ghost btn-sm"
                  style={{ justifyContent: 'flex-start', color: 'var(--danger)' }}
                  onClick={handleLogout}
                >
                  退出登录
                </button>
              </div>
            </>
          )}
          <button
            title={`@${me.username}`}
            onClick={() => setAccountMenuOpen(open => !open)}
            style={{
              width: 36,
              height: 36,
              borderRadius: 999,
              background: accountMenuOpen ? 'var(--brass-soft)' : 'var(--bg-raised)',
              border: `1px solid ${accountMenuOpen ? 'var(--brass-line)' : 'var(--line)'}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontFamily: 'var(--f-serif)',
              fontSize: 14,
              color: 'var(--brass)',
              cursor: 'pointer',
            }}
          >
            {(me.display_name || me.username)[0]}
          </button>
        </div>
      </aside>

      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <header
          style={{
            height: 48,
            flex: '0 0 48px',
            display: 'flex',
            alignItems: 'center',
            padding: '0 22px',
            gap: 18,
            borderBottom: '1px solid var(--line-subtle)',
          }}
        >
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
            <span style={{ fontSize: 14, fontWeight: 600 }}>{TAB_CONTEXT[tab].ctx}</span>
            <span className="mono text-xs text-ink-4">{TAB_CONTEXT[tab].sub}</span>
          </div>
          <span className="chip mono">
            <span className={`dot ${onlineBridges > 0 ? 'dot-live' : 'dot-off'}`} /> 设备 {onlineBridges}/{totalBridges}
          </span>
          <span className="chip mono">@{me.username}</span>
        </header>

        {error && (
          <div
            style={{
              margin: '10px 22px',
              padding: '10px 12px',
              background: 'oklch(0.62 0.150 22 / 0.12)',
              border: '1px solid oklch(0.62 0.150 22 / 0.35)',
              borderRadius: 8,
              color: 'var(--danger)',
              display: 'flex',
              justifyContent: 'space-between',
              gap: 12,
              fontSize: 12,
            }}
          >
            <span style={{ wordBreak: 'break-all' }}>{error}</span>
            <button onClick={() => setError('')} className="btn btn-ghost btn-sm">×</button>
          </div>
        )}

        <main style={{ flex: 1, overflow: 'auto' }}>
          {tab === 'takeover' && (
            <TakeoverView
              inboxes={inboxes}
              bridges={bridges}
              personas={personas}
              onChanged={loadAll}
              setError={setError}
            />
          )}
          {tab === 'persona' && (
            <PersonasView personas={personas} onChanged={loadAll} setError={setError} />
          )}
          {tab === 'device' && (
            <DevicesView
              bridges={bridges}
              inboxes={inboxes}
              meUsername={me.username}
              onChanged={loadAll}
              setError={setError}
            />
          )}
        </main>
      </div>

      {showChangePassword && (
        <ChangePasswordModal
          me={me.username}
          onClose={() => setShowChangePassword(false)}
          setError={setError}
        />
      )}
    </div>
  );
}

function PageHead({ title, kicker, right }: { title: string; kicker?: string; right?: ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 16, padding: '24px 28px 12px' }}>
      <div style={{ flex: 1 }}>
        {kicker && <span className="eyebrow">{kicker}</span>}
        <h1 className="serif" style={{ fontSize: 28, margin: '4px 0 0', fontWeight: 400, letterSpacing: '-0.02em' }}>{title}</h1>
      </div>
      {right}
    </div>
  );
}

function TakeoverView({ inboxes, bridges, personas, onChanged, setError }: {
  inboxes: Inbox[];
  bridges: Bridge[];
  personas: PersonaSummary[];
  onChanged: ChangeHandler;
  setError: (message: string) => void;
}) {
  const [showTaken, setShowTaken] = useState(true);
  const [showAvailable, setShowAvailable] = useState(true);
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);

  const reload = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      const next = await api.getConversations();
      setItems(next);
      setSelectedId(previous => (
        previous && next.some(item => item.contact.id === previous)
          ? previous
          : next[0]?.contact.id ?? null
      ));
    } catch (err) {
      setError(String(err));
    } finally {
      if (showLoading) setLoading(false);
    }
  }, [setError]);

  useEffect(() => {
    reload();
    const id = setInterval(() => reload(false), 3_000);
    return () => clearInterval(id);
  }, [reload]);

  const selected = items.find(item => item.contact.id === selectedId) ?? null;
  const selectedInbox = useMemo(() => {
    if (!selected) return null;
    return inboxes.find(inbox => inbox.id === selected.inbox.id) ?? selected.inbox;
  }, [selected, inboxes]);
  const selectedBridge = selectedInbox
    ? bridges.find(bridge => bridge.id === selectedInbox.bridge_id) ?? null
    : null;

  const reloadMessages = useCallback(async () => {
    if (!selectedId) {
      setMessages([]);
      return;
    }
    try {
      setMessages(await api.getContactMessages(selectedId));
    } catch (err) {
      setError(String(err));
    }
  }, [selectedId, setError]);

  useEffect(() => {
    reloadMessages();
    const id = setInterval(reloadMessages, 3_000);
    return () => clearInterval(id);
  }, [reloadMessages]);

  const takenItems = useMemo(() => items.filter(item => item.contact.takeover), [items]);
  const availableItems = useMemo(() => items.filter(item => !item.contact.takeover), [items]);

  const groupByInbox = (list: ConversationSummary[]) => {
    const result: Record<string, ConversationSummary[]> = {};
    for (const item of list) {
      if (!result[item.inbox.id]) result[item.inbox.id] = [];
      result[item.inbox.id].push(item);
    }
    return result;
  };

  const takenGrouped = useMemo(() => groupByInbox(takenItems), [takenItems]);
  const availableGrouped = useMemo(() => groupByInbox(availableItems), [availableItems]);

  const inboxOrder = useMemo(() => {
    const seen = new Set<string>();
    const ordered: Inbox[] = [];
    for (const item of items) {
      if (seen.has(item.inbox.id)) continue;
      seen.add(item.inbox.id);
      ordered.push(inboxes.find(inbox => inbox.id === item.inbox.id) ?? item.inbox);
    }
    for (const inbox of inboxes) {
      if (seen.has(inbox.id)) continue;
      seen.add(inbox.id);
      ordered.push(inbox);
    }
    return ordered;
  }, [items, inboxes]);

  const patchContact = async (contactId: string, patch: Parameters<typeof api.updateContact>[1]) => {
    try {
      await api.updateContact(contactId, patch);
      await reload();
      await reloadMessages();
      await Promise.resolve(onChanged());
    } catch (err) {
      setError(String(err));
    }
  };

  return (
    <div>
      <PageHead
        title={`${takenItems.length} 个已接管 · ${availableItems.length} 个未接管`}
        kicker="你负责的所有粉丝"
        right={<button className="btn btn-sm btn-ghost" onClick={() => reload()}>{loading ? '刷新中…' : '刷新'}</button>}
      />
      {inboxOrder.length === 0 ? (
        <div style={{ padding: '0 28px 24px' }}>
          <Empty>
            还没有任何账号。先在「设备」页按步骤把账号接进来，接好后这里会自动出现粉丝。
          </Empty>
        </div>
      ) : (
        <div className="takeover-grid" style={{ padding: '0 28px 24px' }}>
          <div style={{ display: 'grid', gap: 12, minWidth: 0 }}>
            <Drawer
              title="已接管"
              count={takenItems.length}
              open={showTaken}
              onToggle={() => setShowTaken(value => !value)}
            >
              {takenItems.length === 0 ? (
                <div className="ink-3" style={{ fontSize: 12, padding: '4px 2px' }}>
                  还没有接管任何会话。在下面「未接管」里点「接管」即可。
                </div>
              ) : (
                inboxOrder.map(inbox => {
                  const convs = takenGrouped[inbox.id] ?? [];
                  if (convs.length === 0) return null;
                  return (
                    <InboxGroup
                      key={`taken-${inbox.id}`}
                      inbox={inbox}
                      bridge={bridges.find(bridge => bridge.id === inbox.bridge_id) ?? null}
                      conversations={convs}
                      selectedId={selectedId}
                      onSelect={setSelectedId}
                      personas={personas}
                      onChanged={onChanged}
                      onLocalRefresh={reload}
                      onSetTakeover={(id, value) => patchContact(id, { takeover: value })}
                      setError={setError}
                    />
                  );
                })
              )}
            </Drawer>

            <Drawer
              title="未接管"
              count={availableItems.length}
              open={showAvailable}
              onToggle={() => setShowAvailable(value => !value)}
            >
              {availableItems.length === 0 ? (
                <div className="ink-3" style={{ fontSize: 12, padding: '4px 2px' }}>暂时没有未接管的粉丝。</div>
              ) : (
                inboxOrder.map(inbox => {
                  const convs = availableGrouped[inbox.id] ?? [];
                  if (convs.length === 0) return null;
                  return (
                    <div key={`avail-${inbox.id}`} className="card" style={{ padding: '10px 14px', display: 'grid', gap: 6 }}>
                      <span className="ink-3" style={{ fontSize: 11 }}>{inbox.display_name}</span>
                      {convs.map((item, index) => (
                        <div
                          key={item.contact.id}
                          style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, padding: '6px 0', borderBottom: index < convs.length - 1 ? '1px solid var(--line-subtle)' : 'none' }}
                        >
                          <button
                            className="card"
                            style={{ flex: 1, textAlign: 'left', padding: '6px 8px', background: selectedId === item.contact.id ? 'var(--brass-soft)' : undefined, borderColor: selectedId === item.contact.id ? 'var(--brass-line)' : 'var(--line-subtle)' }}
                            onClick={() => setSelectedId(item.contact.id)}
                          >
                            <span style={{ fontSize: 13 }}>{item.contact.display_name}</span>
                          </button>
                          <button
                            className="btn btn-sm btn-primary"
                            onClick={() => patchContact(item.contact.id, { takeover: true })}
                          >
                            + 接管
                          </button>
                        </div>
                      ))}
                    </div>
                  );
                })
              )}
            </Drawer>
          </div>

          <div className="card" style={{ padding: 16, minHeight: 420 }}>
            {!selected || !selectedInbox ? (
              <Empty>请从左侧选一个粉丝。</Empty>
            ) : (
              <ContactDetail
                contact={selected.contact}
                inbox={selectedInbox}
                bridge={selectedBridge}
                messages={messages}
                personas={personas}
                onPatch={patchContact}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function InboxGroup({ inbox, bridge, conversations, selectedId, onSelect, onSetTakeover }: {
  inbox: Inbox;
  bridge: Bridge | null;
  conversations: ConversationSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  personas: PersonaSummary[];
  onChanged: ChangeHandler;
  onLocalRefresh: () => Promise<void>;
  onSetTakeover: (contactId: string, value: boolean) => void;
  setError: (message: string) => void;
}) {
  const online = bridge?.status === 'online';

  return (
    <div className="card" style={{ padding: '12px 14px', display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', minWidth: 0 }}>
          <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 99, background: online ? 'var(--live)' : 'var(--ink-3)' }} />
          <strong style={{ fontSize: 13 }}>{inbox.display_name}</strong>
          <span className="chip muted">{inbox.platform}</span>
        </div>
      </div>

      {conversations.length === 0 ? (
        <div className="ink-3" style={{ fontSize: 12, padding: '8px 4px' }}>
          还没有粉丝，收到第一条消息时会自动出现。
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 6 }}>
          {conversations.map(item => (
            <div
              key={item.contact.id}
              className="card"
              style={{
                padding: '8px 10px',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                borderColor: selectedId === item.contact.id ? 'var(--brass-line)' : 'var(--line-subtle)',
                background: selectedId === item.contact.id ? 'var(--brass-soft)' : 'var(--bg-base)',
              }}
            >
              <button
                onClick={() => onSelect(item.contact.id)}
                style={{ flex: 1, minWidth: 0, textAlign: 'left', background: 'transparent', border: 'none', cursor: 'pointer', padding: 0, color: 'inherit' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                  <strong style={{ fontSize: 13 }}>{item.contact.display_name}</strong>
                  {item.contact.reply_policy === 'autoreply'
                    ? <span className="chip live">自动回复</span>
                    : <span className="chip muted">{item.message_count}</span>}
                </div>
                <div className="ink-2" style={{ fontSize: 12, marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {item.latest_message ? `${item.latest_message.role === 'self' ? '我' : '对方'}：${item.latest_message.content}` : '暂无消息'}
                </div>
                <div className="ink-3" style={{ fontSize: 10, marginTop: 4 }}>
                  {item.latest_message ? formatDateTime(item.latest_message.timestamp) : formatDateTime(item.contact.updated_at)}
                </div>
              </button>
              <button
                className="btn btn-sm btn-ghost"
                style={{ flex: '0 0 auto', color: 'var(--danger)' }}
                title="不再由你接管这个粉丝"
                onClick={() => {
                  if (!confirm(`取消接管「${item.contact.display_name}」？取消后将停止自动回复。`)) return;
                  onSetTakeover(item.contact.id, false);
                }}
              >
                取消接管
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ContactDetail({ contact, inbox, bridge, messages, personas, onPatch }: {
  contact: ContactSummary;
  inbox: Inbox;
  bridge: Bridge | null;
  messages: Message[];
  personas: PersonaSummary[];
  onPatch: (contactId: string, patch: Parameters<typeof api.updateContact>[1]) => Promise<void>;
}) {
  // card_md 不在列表里，需要按 id 单独拉
  const [full, setFull] = useState<Contact | null>(null);
  const [draftCard, setDraftCard] = useState('');
  const [savingCard, setSavingCard] = useState(false);
  const [cardJobBusy, setCardJobBusy] = useState(false);
  const [cardJobNote, setCardJobNote] = useState('');

  useEffect(() => {
    let alive = true;
    setFull(null);
    setDraftCard('');
    api.getContact(contact.id).then(c => {
      if (!alive) return;
      setFull(c);
      setDraftCard(c.card_md ?? '');
    }).catch(() => { /* ignore */ });
    return () => { alive = false; };
  }, [contact.id, contact.updated_at]);

  // 同样按需拉当前 contact 绑定的 persona 详情（用于自动回复缺料检查）
  const [selectedPersona, setSelectedPersona] = useState<Persona | null>(null);
  useEffect(() => {
    if (!contact.persona_id) { setSelectedPersona(null); return; }
    let alive = true;
    api.getPersona(contact.persona_id).then(p => { if (alive) setSelectedPersona(p); }).catch(() => { /* ignore */ });
    return () => { alive = false; };
  }, [contact.persona_id]);

  const currentCard = full?.card_md ?? '';

  const inboxLive = Boolean(bridge && bridge.status === 'online');
  const canAutoreply = inboxLive && Boolean(contact.persona_id);

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <div style={{ borderBottom: '1px solid var(--line-subtle)', paddingBottom: 12, display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 16 }}>{contact.display_name}</div>
          <div className="ink-3" style={{ fontSize: 11, marginTop: 4 }}>
            来自 {inbox.display_name}（{inbox.platform}）
          </div>
        </div>
        {contact.takeover ? (
          <button
            className="btn btn-sm btn-ghost"
            style={{ color: 'var(--danger)' }}
            onClick={() => {
              if (!confirm(`取消接管「${contact.display_name}」？取消后将停止自动回复。`)) return;
              onPatch(contact.id, { takeover: false });
            }}
          >
            取消接管
          </button>
        ) : (
          <button className="btn btn-sm btn-primary" onClick={() => onPatch(contact.id, { takeover: true })}>
            + 接管
          </button>
        )}
      </div>

      {contact.takeover && (
      <div style={{ display: 'grid', gap: 8, padding: 12, background: 'var(--bg-raised)', borderRadius: 8, border: '1px solid var(--line-subtle)' }}>
        <div className="ink-3" style={{ fontSize: 11 }}>这个粉丝的接管设置</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
          <label style={{ fontSize: 11, color: 'var(--ink-3)' }}>
            人设
            <select
              value={contact.persona_id ?? ''}
              className="select"
              style={{ marginLeft: 6 }}
              onChange={event => {
                if (event.target.value) onPatch(contact.id, { persona_id: event.target.value });
              }}
            >
              <option value="">（未选）</option>
              {personas.map(persona => <option key={persona.id} value={persona.id}>{persona.name}</option>)}
            </select>
          </label>
          <label style={{ fontSize: 11, color: 'var(--ink-3)', display: 'flex', alignItems: 'center', gap: 6 }}>
            回复方式
            <select
              value={contact.reply_policy}
              disabled={!canAutoreply && contact.reply_policy !== 'autoreply'}
              onChange={event => {
                const next = event.target.value as 'disabled' | 'autoreply';
                if (next === 'autoreply') {
                  const hasPersona = Boolean(contact.persona_id && selectedPersona?.persona_md && selectedPersona.persona_md.trim());
                  const hasCard = Boolean(currentCard && currentCard.trim());
                  if (!hasPersona || !hasCard) {
                    const missing = [hasPersona ? null : '人设', hasCard ? null : '关系备注'].filter(Boolean).join(' 和 ');
                    if (!confirm(`还缺${missing}（两样都要有才能自动回复）。可以去「人设」页自动生成。仍要开启自动回复吗？`)) return;
                  }
                }
                onPatch(contact.id, { reply_policy: next });
              }}
              style={{ fontSize: 11 }}
            >
              <option value="disabled">只接管，不自动回复</option>
              <option value="autoreply">自动回复</option>
            </select>
          </label>
        </div>
        {!canAutoreply && (
          <div style={{ fontSize: 11, color: 'var(--warn)' }}>
            {!bridge && '— 这个账号没有在线的设备；'}
            {bridge && bridge.status !== 'online' && `— 设备「${bridge.machine_id}」当前离线；`}
            {!contact.persona_id && '— 还没选人设；'}
            目前无法自动回复。
          </div>
        )}

        <label className="ink-3" style={{ fontSize: 11 }}>关系备注 —— 简单写下你和这个人的关系，回复时会参考它</label>
        <textarea
          className="textarea mono"
          style={{ minHeight: 90, fontSize: 12 }}
          value={draftCard}
          onChange={event => setDraftCard(event.target.value)}
          placeholder={full ? '例如：北京大学生，喜欢户外，去年送过我一袋茶叶，叫我 alice 姐' : '加载中…'}
          disabled={!full}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6 }}>
          <button
            className="btn btn-sm btn-ghost"
            disabled={cardJobBusy}
            title="读完和这个粉丝的全部聊天记录，自动整理出关系备注（在后台进行）"
            onClick={async () => {
              setCardJobBusy(true);
              setCardJobNote('');
              try {
                await api.createDistillJob({ contact_ids: [contact.id], target_persona_id: null });
                setCardJobNote('已开始，正在后台读聊天记录整理关系备注，稍后会自动刷新。');
              } catch (err) {
                setCardJobNote(String(err));
              } finally {
                setCardJobBusy(false);
              }
            }}
          >
            {cardJobBusy ? '处理中…' : '✶ 自动整理关系备注'}
          </button>
          <div style={{ display: 'flex', gap: 6 }}>
            {full && draftCard !== currentCard && (
              <button className="btn btn-sm btn-ghost" onClick={() => setDraftCard(currentCard)}>
                放弃修改
              </button>
            )}
            <button
              className="btn btn-sm btn-primary"
              disabled={!full || savingCard || draftCard === currentCard}
              onClick={async () => {
                setSavingCard(true);
                try {
                  await onPatch(contact.id, { card_md: draftCard });
                  setFull(prev => prev ? { ...prev, card_md: draftCard } : prev);
                } finally {
                  setSavingCard(false);
                }
              }}
            >
              {savingCard ? '保存中…' : '保存关系备注'}
            </button>
          </div>
        </div>
        {cardJobNote && (
          <div className="ink-3" style={{ fontSize: 11 }}>{cardJobNote}</div>
        )}
      </div>
      )}

      {messages.length === 0 ? (
        <Empty>暂无消息。</Empty>
      ) : (
        <div style={{ display: 'grid', gap: 8, maxHeight: '52dvh', overflow: 'auto', paddingRight: 4 }}>
          {messages.map(message => (
            <div key={message.id} style={{ display: 'flex', justifyContent: message.role === 'self' ? 'flex-end' : 'flex-start' }}>
              <div style={{ maxWidth: '76%' }}>
                <div className="mono ink-3" style={{ fontSize: 10, textAlign: message.role === 'self' ? 'right' : 'left', marginBottom: 3 }}>
                  {message.role === 'self' ? '我' : contact.display_name} · {formatDateTime(message.timestamp)}
                </div>
                <div
                  style={{
                    padding: '8px 10px',
                    borderRadius: 12,
                    background: message.role === 'self' ? 'var(--brass-soft)' : 'var(--bg-raised)',
                    border: '1px solid var(--line-subtle)',
                    whiteSpace: 'pre-wrap',
                    overflowWrap: 'anywhere',
                    fontSize: 13,
                    lineHeight: 1.5,
                  }}
                >
                  {message.content}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function DevicesView({ bridges, inboxes, meUsername, onChanged, setError }: {
  bridges: Bridge[];
  inboxes: Inbox[];
  meUsername: string;
  onChanged: ChangeHandler;
  setError: (message: string) => void;
}) {
  const inboxesByBridge = useMemo(() => {
    const result: Record<string, Inbox[]> = {};
    for (const inbox of inboxes) {
      if (!inbox.bridge_id) continue;
      if (!result[inbox.bridge_id]) result[inbox.bridge_id] = [];
      result[inbox.bridge_id].push(inbox);
    }
    return result;
  }, [inboxes]);

  return (
    <div>
      <PageHead title="设备" kicker="Windows / mac 上的接入程序" />
      <div style={{ padding: '0 28px 24px', display: 'grid', gap: 14 }}>
        <BridgeCommandPanel meUsername={meUsername} />
        {bridges.length === 0 ? (
          <Empty>
            还没有设备。按上面的步骤在主播电脑上接入账号，接好后会自动出现在这里。
          </Empty>
        ) : (
          <div style={{ display: 'grid', gap: 10 }}>
            {bridges.map(bridge => (
              <div key={bridge.id} className="card" style={{ padding: '14px 16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
                  <div>
                    <div style={{ fontWeight: 500, display: 'flex', alignItems: 'center', gap: 8 }}>
                      <StatusDot status={bridge.status} />
                      {bridge.machine_id}
                      <span className={`chip ${statusChipClass(bridge.status)}`}>{statusText(bridge.status)}</span>
                    </div>
                    <div className="ink-3" style={{ fontSize: 11, marginTop: 4 }}>
                      最后在线 {formatDateTime(bridge.last_seen_at)} · 接入了 {(inboxesByBridge[bridge.id] || []).length} 个账号
                    </div>
                  </div>
                  <button
                    className="btn btn-sm btn-ghost"
                    style={{ color: 'var(--danger)' }}
                    onClick={async () => {
                      if (!confirm(`确认移除设备「${bridge.machine_id}」？这台电脑上接入的账号会停止收发消息，需要重新接入。`)) return;
                      try {
                        await api.deleteBridge(bridge.id);
                        await Promise.resolve(onChanged());
                      } catch (err) {
                        setError(String(err));
                      }
                    }}
                  >
                    移除
                  </button>
                </div>
                {(inboxesByBridge[bridge.id] || []).length > 0 && (
                  <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--line-subtle)', display: 'grid', gap: 6 }}>
                    {(inboxesByBridge[bridge.id] || []).map(inbox => (
                      <div key={inbox.id} style={{ fontSize: 11, color: 'var(--ink-2)' }}>
                        {inbox.display_name}（{inbox.platform}）
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function StatusDot({ status }: { status: Bridge['status'] }) {
  const color = status === 'online' ? 'var(--live)' : 'var(--ink-3)';
  return <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 99, background: color }} />;
}

function statusText(status: Bridge['status']): string {
  return status === 'online' ? '在线' : '离线';
}

function statusChipClass(status: Bridge['status']): string {
  return status === 'online' ? 'live' : 'muted';
}

function PersonasView({ personas, onChanged, setError }: {
  personas: PersonaSummary[];
  onChanged: ChangeHandler;
  setError: (message: string) => void;
}) {
  const [showCreate, setShowCreate] = useState(false);
  const [showAuto, setShowAuto] = useState(false);
  const [editing, setEditing] = useState<PersonaSummary | null>(null);

  return (
    <div>
      <PageHead
        title="人设"
        kicker="你可以扮演的人设"
        right={
          <div style={{ display: 'flex', gap: 6 }}>
            <button className="btn btn-primary btn-sm" onClick={() => setShowAuto(true)}>✶ 自动创建</button>
            <button className="btn btn-ghost btn-sm" onClick={() => setShowCreate(true)}>+ 手动新建</button>
          </div>
        }
      />
      <div style={{ padding: '0 28px 24px' }}>
        {personas.length === 0 ? (
          <Empty>还没有人设。</Empty>
        ) : (
          <div style={{ display: 'grid', gap: 10 }}>
            {personas.map(persona => (
              <div key={persona.id} className="card" style={{ padding: '14px 16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
                  <div>
                    <div style={{ fontWeight: 500 }}>
                      {persona.name}
                    </div>
                    <div className="ink-3" style={{ fontSize: 11, marginTop: 4 }}>
                      {persona.timezone}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button className="btn btn-sm btn-ghost" onClick={() => setEditing(persona)}>编辑</button>
                    <button
                      className="btn btn-sm btn-ghost"
                      style={{ color: 'var(--danger)' }}
                      onClick={async () => {
                        if (!confirm('确认删除这个人设？如果还有粉丝在用它，会删除失败。')) return;
                        try {
                          await api.deletePersona(persona.id);
                          await Promise.resolve(onChanged());
                        } catch (err) {
                          setError(String(err));
                        }
                      }}
                    >
                      删除
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      {showCreate && (
        <CreatePersonaModal
          onClose={() => setShowCreate(false)}
          onSwitchToAuto={() => { setShowCreate(false); setShowAuto(true); }}
          onCreated={async () => {
            setShowCreate(false);
            await Promise.resolve(onChanged());
          }}
          setError={setError}
        />
      )}
      {showAuto && (
        <AutoCreatePersonaModal
          onClose={() => setShowAuto(false)}
          onSubmitted={async () => {
            setShowAuto(false);
            await Promise.resolve(onChanged());
          }}
          setError={setError}
        />
      )}
      {editing && (
        <EditPersonaModal
          persona={editing}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null);
            await Promise.resolve(onChanged());
          }}
          setError={setError}
        />
      )}
    </div>
  );
}

function CreatePersonaModal({ onClose, onCreated, onSwitchToAuto, setError }: {
  onClose: () => void;
  onCreated: () => void | Promise<void>;
  onSwitchToAuto: () => void;
  setError: (message: string) => void;
}) {
  const [name, setName] = useState('');
  const [md, setMd] = useState('');
  const [tz, setTz] = useState('Asia/Shanghai');
  const [busy, setBusy] = useState(false);

  const handle = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await api.createPersona({ name: name.trim(), persona_md: md || null, timezone: tz.trim() || 'UTC' });
      await Promise.resolve(onCreated());
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell onClose={onClose} title="新建人设">
      <div
        className="card"
        style={{ padding: '12px 14px', marginBottom: 16, background: 'var(--brass-soft)', borderColor: 'var(--brass-line)' }}
      >
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>不用自己写 ——可以从聊天记录自动创建</div>
        <div className="ink-3" style={{ fontSize: 12, marginBottom: 10 }}>
          选几段你和粉丝的真实对话，AI 会读完后替你总结出人设和每个粉丝的关系备注。
        </div>
        <button className="btn btn-primary btn-sm" onClick={onSwitchToAuto}>✶ 用聊天记录自动创建</button>
      </div>
      <FormField label="名称"><input className="input" value={name} onChange={event => setName(event.target.value)} autoFocus /></FormField>
      <FormField label="时区"><input className="input" value={tz} onChange={event => setTz(event.target.value)} placeholder="Asia/Shanghai" /></FormField>
      <FormField label="人设描述（可不填）">
        <textarea className="textarea mono" style={{ minHeight: 200 }} value={md} onChange={event => setMd(event.target.value)} />
      </FormField>
      <ModalActions onCancel={onClose} onConfirm={handle} confirmLabel={busy ? '创建中...' : '创建'} disabled={busy || !name.trim()} />
    </ModalShell>
  );
}

function AutoCreatePersonaModal({ onClose, onSubmitted, setError }: {
  onClose: () => void;
  onSubmitted: () => void | Promise<void>;
  setError: (message: string) => void;
}) {
  const [name, setName] = useState('');
  const [tz, setTz] = useState('Asia/Shanghai');
  const [items, setItems] = useState<ConversationSummary[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const next = await api.getConversations();
        const taken = next.filter(item => item.contact.takeover);
        setItems(taken);
        setSelected(new Set(taken.map(item => item.contact.id)));
      } catch (err) {
        setError(String(err));
      } finally {
        setLoading(false);
      }
    })();
  }, [setError]);

  const grouped = useMemo(() => {
    const result: Record<string, { inbox: ConversationSummary['inbox']; rows: ConversationSummary[] }> = {};
    for (const item of items) {
      if (!result[item.inbox.id]) result[item.inbox.id] = { inbox: item.inbox, rows: [] };
      result[item.inbox.id].rows.push(item);
    }
    return Object.values(result);
  }, [items]);

  const toggle = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const submit = async () => {
    if (!name.trim() || selected.size === 0) return;
    setBusy(true);
    try {
      const persona = await api.createPersona({
        name: name.trim(), persona_md: null, timezone: tz.trim() || 'UTC',
      });
      await api.createDistillJob({
        contact_ids: Array.from(selected),
        target_persona_id: persona.id,
      });
      await Promise.resolve(onSubmitted());
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell onClose={onClose} title="✶ 自动创建人设">
      <div className="ink-3" style={{ fontSize: 12, marginBottom: 14 }}>
        给人设起个名字，再选几段真实对话。AI 会在后台读完这些聊天，自动写出人设；同时也会顺手生成每个被选中粉丝的关系备注。生成在后台进行，关掉窗口也没关系。
      </div>
      <FormField label="人设名称"><input className="input" value={name} onChange={event => setName(event.target.value)} autoFocus placeholder="例如：阿言（抖音）" /></FormField>
      <FormField label="时区"><input className="input" value={tz} onChange={event => setTz(event.target.value)} placeholder="Asia/Shanghai" /></FormField>
      <div className="ink-3" style={{ fontSize: 11, marginBottom: 6 }}>
        从这些对话里学习（已选 {selected.size} / {items.length}）
      </div>
      {loading ? (
        <Empty>正在加载已接管的粉丝…</Empty>
      ) : items.length === 0 ? (
        <Empty>还没有接管任何粉丝。先去「接管」页接管一些粉丝。</Empty>
      ) : (
        <div style={{ display: 'grid', gap: 12, maxHeight: '40vh', overflow: 'auto', marginBottom: 8 }}>
          {grouped.map(group => (
            <div key={group.inbox.id} className="card" style={{ padding: '10px 12px', display: 'grid', gap: 4 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span className="ink-3" style={{ fontSize: 11 }}>{group.inbox.display_name}</span>
                <button
                  className="btn btn-sm btn-ghost"
                  onClick={() => {
                    const ids = group.rows.map(r => r.contact.id);
                    const allOn = ids.every(id => selected.has(id));
                    setSelected(prev => {
                      const next = new Set(prev);
                      for (const id of ids) { if (allOn) next.delete(id); else next.add(id); }
                      return next;
                    });
                  }}
                >
                  {group.rows.every(r => selected.has(r.contact.id)) ? '取消整组' : '全选整组'}
                </button>
              </div>
              {group.rows.map(item => (
                <label
                  key={item.contact.id}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, padding: '3px 0', cursor: 'pointer' }}
                >
                  <input
                    type="checkbox"
                    checked={selected.has(item.contact.id)}
                    onChange={() => toggle(item.contact.id)}
                  />
                  <span style={{ flex: 1 }}>{item.contact.display_name}</span>
                  <span className="mono ink-3" style={{ fontSize: 11 }}>{item.message_count} 条</span>
                </label>
              ))}
            </div>
          ))}
        </div>
      )}
      <ModalActions
        onCancel={onClose}
        onConfirm={submit}
        confirmLabel={busy ? '提交中…' : `开始自动创建（${selected.size}）`}
        disabled={busy || loading || !name.trim() || selected.size === 0}
      />
    </ModalShell>
  );
}

function EditPersonaModal({ persona, onClose, onSaved, setError }: {
  persona: PersonaSummary;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
  setError: (message: string) => void;
}) {
  const [name, setName] = useState(persona.name);
  const [md, setMd] = useState('');
  const [tz, setTz] = useState(persona.timezone ?? 'UTC');
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    api.getPersona(persona.id)
      .then(full => {
        if (!alive) return;
        setMd(full.persona_md ?? '');
        setLoaded(true);
      })
      .catch(err => { if (alive) setError(String(err)); });
    return () => { alive = false; };
  }, [persona.id, setError]);

  const handle = async () => {
    setBusy(true);
    try {
      await api.updatePersona(persona.id, { name, persona_md: md, timezone: tz.trim() || 'UTC' });
      await Promise.resolve(onSaved());
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell onClose={onClose} title={`编辑人设 · ${persona.name}`}>
      <FormField label="名称"><input className="input" value={name} onChange={event => setName(event.target.value)} /></FormField>
      <FormField label="时区"><input className="input" value={tz} onChange={event => setTz(event.target.value)} placeholder="Asia/Shanghai" /></FormField>
      <FormField label="人设描述">
        <textarea
          className="textarea mono"
          style={{ minHeight: 320 }}
          value={md}
          onChange={event => setMd(event.target.value)}
          placeholder={loaded ? '' : '加载中…'}
          disabled={!loaded}
        />
      </FormField>
      <ModalActions onCancel={onClose} onConfirm={handle} confirmLabel={busy ? '保存中...' : '保存'} disabled={busy || !loaded} />
    </ModalShell>
  );
}

function ChangePasswordModal({ me, onClose, setError }: {
  me: string;
  onClose: () => void;
  setError: (message: string) => void;
}) {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [ok, setOk] = useState('');

  const mismatch = confirmPassword.length > 0 && newPassword !== confirmPassword;
  const canSubmit = Boolean(currentPassword && newPassword && newPassword === confirmPassword);

  const handle = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setOk('');
    try {
      await api.changeOwnPassword({ current_password: currentPassword, new_password: newPassword });
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setOk('密码已修改，请用新密码重新登录。');
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell onClose={onClose} title={`修改密码 · @${me}`}>
      <FormField label="当前密码"><input className="input" type="password" value={currentPassword} onChange={event => setCurrentPassword(event.target.value)} autoFocus /></FormField>
      <FormField label="新密码"><input className="input" type="password" value={newPassword} onChange={event => setNewPassword(event.target.value)} /></FormField>
      <FormField label="再输一次新密码"><input className="input" type="password" value={confirmPassword} onChange={event => setConfirmPassword(event.target.value)} /></FormField>
      {mismatch && <div style={{ color: 'var(--danger)', fontSize: 11, marginBottom: 8 }}>两次输入的新密码不一致</div>}
      {ok && <div style={{ color: 'var(--live)', fontSize: 11, marginBottom: 8 }}>{ok}</div>}
      <ModalActions onCancel={onClose} onConfirm={handle} confirmLabel={busy ? '保存中…' : '修改密码'} disabled={busy || !canSubmit} />
    </ModalShell>
  );
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="card ink-3" style={{ padding: 18, textAlign: 'center' }}>{children}</div>;
}

function Drawer({ title, count, open, onToggle, children }: {
  title: string;
  count: number;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <div style={{ display: 'grid', gap: open ? 10 : 0 }}>
      <button
        onClick={onToggle}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          width: '100%',
          padding: '8px 10px',
          background: 'var(--bg-raised)',
          border: '1px solid var(--line-subtle)',
          borderRadius: 8,
          cursor: 'pointer',
          color: 'var(--ink-1)',
          textAlign: 'left',
        }}
      >
        <span style={{ fontSize: 12, color: 'var(--ink-3)', transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }}>▶</span>
        <span style={{ fontWeight: 600, fontSize: 13 }}>{title}</span>
        <span className="chip muted" style={{ marginLeft: 'auto' }}>{count}</span>
      </button>
      {open && <div style={{ display: 'grid', gap: 10 }}>{children}</div>}
    </div>
  );
}

function FormField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label style={{ display: 'block', marginBottom: 12 }}>
      {label && <div className="mono ink-3" style={{ fontSize: 11, marginBottom: 4 }}>{label}</div>}
      {children}
    </label>
  );
}

function ModalShell({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div style={{ position: 'fixed', inset: 0, background: 'oklch(0.06 0.005 60 / 0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }} onClick={onClose}>
      <div className="card" style={{ width: 'min(560px, 92vw)', maxHeight: '85vh', overflow: 'auto', padding: 22 }} onClick={event => event.stopPropagation()}>
        <h3 className="serif" style={{ fontSize: 20, margin: '0 0 16px' }}>{title}</h3>
        {children}
      </div>
    </div>
  );
}

function ModalActions({ onCancel, onConfirm, confirmLabel, disabled }: {
  onCancel: () => void;
  onConfirm: () => void;
  confirmLabel: string;
  disabled?: boolean;
}) {
  return (
    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
      <button className="btn btn-ghost btn-sm" onClick={onCancel}>取消</button>
      <button className="btn btn-primary btn-sm" onClick={onConfirm} disabled={disabled}>{confirmLabel}</button>
    </div>
  );
}

function BridgeCommandPanel({ meUsername }: { meUsername: string }) {
  const steps: { title: string; desc: string }[] = [
    {
      title: '下载并打开 Laborster Bridge',
      desc: '在主播本人的电脑上下载对应版本：Windows 双击 .exe，mac 双击 App。mac 首次打开若提示「无法验证开发者」，右键图标 → 打开 即可。数据目录已固定，无需设置。',
    },
    {
      title: '在「账号」标签里登录',
      desc: `打开顶部「账号」标签，填入你登录本网站的账号（你的账号是 ${meUsername}）和密码，点「登录」。`,
    },
    {
      title: '在「Channels」标签里添加聊天账号',
      desc: '切到「Channels」标签，点右上「+ 添加」，填入要托管的聊天账号和密码，点「添加」。可重复添加多个账号。',
    },
    {
      title: '在「状态」标签里确认接好',
      desc: '切到「状态」标签，daemon 显示「运行中」即说明接好了。接好之后这一页会自动列出设备和账号。',
    },
  ];

  return (
    <div className="card" style={{ padding: 16, display: 'grid', gap: 12 }}>
      <div>
        <div style={{ fontWeight: 600, fontSize: 14 }}>怎么把账号接进来</div>
        <div className="ink-3" style={{ fontSize: 12, marginTop: 4, lineHeight: 1.6 }}>
          在主播本人的电脑上安装并打开 Laborster Bridge 桌面程序，按下面四步操作即可，全程在窗口里点选，不用敲命令。
        </div>
      </div>
      <div style={{ display: 'grid', gap: 8 }}>
        {steps.map((step, index) => (
          <div
            key={step.title}
            style={{ display: 'flex', gap: 12, alignItems: 'flex-start', padding: '10px 12px', background: 'var(--bg-raised)', border: '1px solid var(--line-subtle)', borderRadius: 8 }}
          >
            <span
              className="serif"
              style={{ flex: '0 0 22px', width: 22, height: 22, borderRadius: 999, background: 'var(--brass-soft)', color: 'var(--brass)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13 }}
            >
              {index + 1}
            </span>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 13, color: 'var(--ink-1)', fontWeight: 500 }}>{step.title}</div>
              <div className="ink-3" style={{ fontSize: 12, marginTop: 3, lineHeight: 1.55 }}>{step.desc}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="ink-3" style={{ fontSize: 12, lineHeight: 1.6 }}>
        程序保持打开才会一直收发消息，最小化可在后台继续运行；关闭窗口会停止，重新打开后会自动登录恢复。
      </div>
    </div>
  );
}
