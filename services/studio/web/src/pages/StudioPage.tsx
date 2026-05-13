import { useCallback, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import * as api from '../lib/api';
import type {
  Account,
  AccountRole,
  Bridge,
  Contact,
  ConversationSummary,
  Inbox,
  Message,
  Persona,
  ProviderConfig,
} from '../lib/api';
import { useAuth } from '../lib/auth';

type Tab = 'overview' | 'takeover' | 'persona' | 'device' | 'settings';
type ChangeHandler = () => void | Promise<void>;

const ADMIN_NAV: { id: Tab; label: string; icon: string }[] = [
  { id: 'overview', label: '总览', icon: '◎' },
  { id: 'takeover', label: '接管', icon: '◇' },
  { id: 'persona', label: '人设', icon: '✶' },
  { id: 'device', label: '设备', icon: '⌥' },
  { id: 'settings', label: '设置', icon: '⚙' },
];

const USER_NAV: { id: Tab; label: string; icon: string }[] = [
  { id: 'takeover', label: '接管', icon: '◇' },
  { id: 'persona', label: '人设', icon: '✶' },
  { id: 'device', label: '设备', icon: '⌥' },
  { id: 'settings', label: '设置', icon: '⚙' },
];

const TAB_CONTEXT: Record<Tab, { ctx: string; sub: string }> = {
  overview: { ctx: '总览', sub: 'overview · 全系统用户与资源' },
  takeover: { ctx: '接管', sub: 'contacts · 你管的所有粉丝' },
  persona: { ctx: '人设', sub: 'personas · 你能扮演的人' },
  device: { ctx: '设备', sub: 'devices · 你的本地守护进程' },
  settings: { ctx: '设置', sub: 'settings · 账号 · Provider' },
};

export function StudioPage() {
  const navigate = useNavigate();
  const { account: me, logout } = useAuth();
  const isAdmin = me?.role === 'admin';
  const [tab, setTab] = useState<Tab>(isAdmin ? 'overview' : 'takeover');
  const [bridges, setBridges] = useState<Bridge[]>([]);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [inboxes, setInboxes] = useState<Inbox[]>([]);
  const [providers, setProviders] = useState<ProviderConfig[]>([]);
  const [error, setError] = useState('');

  const loadAll = useCallback(async () => {
    try {
      const [nextBridges, nextPersonas, nextInboxes, nextProviders] = await Promise.all([
        api.getBridges(),
        api.getPersonas(),
        api.getInboxes(),
        isAdmin ? api.getProviderConfigs() : Promise.resolve([]),
      ]);
      setBridges(nextBridges);
      setPersonas(nextPersonas);
      setInboxes(nextInboxes);
      setProviders(nextProviders);
    } catch (err) {
      setError(String(err));
    }
  }, [isAdmin]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const handleLogout = async () => {
    await logout();
    navigate('/', { replace: true });
  };

  const onlineBridges = useMemo(() => bridges.filter(bridge => bridge.status === 'online').length, [bridges]);
  const totalBridges = useMemo(() => bridges.filter(bridge => bridge.status !== 'revoked').length, [bridges]);

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
          {(isAdmin ? ADMIN_NAV : USER_NAV).map(item => {
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
        <div style={{ marginTop: 'auto' }}>
          <button
            title={`@${me.username} · 退出`}
            onClick={handleLogout}
            style={{
              width: 36,
              height: 36,
              borderRadius: 999,
              background: 'var(--bg-raised)',
              border: '1px solid var(--line)',
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
          {tab === 'overview' && isAdmin && (
            <OverviewView setError={setError} />
          )}
          {tab === 'takeover' && (
            <TakeoverView
              inboxes={inboxes}
              bridges={bridges}
              personas={personas}
              providers={providers}
              isAdmin={isAdmin}
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
          {tab === 'settings' && (
            <SettingsView providers={providers} me={me.username} isAdmin={isAdmin} onChanged={loadAll} setError={setError} />
          )}
        </main>
      </div>
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

function TakeoverView({ inboxes, bridges, personas, providers, isAdmin, onChanged, setError }: {
  inboxes: Inbox[];
  bridges: Bridge[];
  personas: Persona[];
  providers: ProviderConfig[];
  isAdmin: boolean;
  onChanged: ChangeHandler;
  setError: (message: string) => void;
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
      setSelectedId(previous => (
        previous && next.some(item => item.contact.id === previous)
          ? previous
          : next[0]?.contact.id ?? null
      ));
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, [setError]);

  useEffect(() => {
    reload();
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
  }, [reloadMessages]);

  const grouped = useMemo(() => {
    const result: Record<string, ConversationSummary[]> = {};
    for (const item of items) {
      const key = item.inbox.id;
      if (!result[key]) result[key] = [];
      result[key].push(item);
    }
    return result;
  }, [items]);

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
        title={`${items.length} 个接管`}
        kicker="contacts"
        right={<button className="btn btn-sm btn-ghost" onClick={reload}>{loading ? '刷新中…' : '刷新'}</button>}
      />
      {inboxOrder.length === 0 ? (
        <div style={{ padding: '0 28px 24px' }}>
          <Empty>
            还没有任何接管号。在主播 PC 上启动本地设备 daemon，它登进的每个 chat 账号都会自动出现在这里。
          </Empty>
        </div>
      ) : (
        <div style={{ padding: '0 28px 24px', display: 'grid', gridTemplateColumns: 'minmax(300px, 380px) minmax(0, 1fr)', gap: 12, alignItems: 'start' }}>
          <div style={{ display: 'grid', gap: 12 }}>
            {inboxOrder.map(inbox => (
              <InboxGroup
                key={inbox.id}
                inbox={inbox}
                bridge={bridges.find(bridge => bridge.id === inbox.bridge_id) ?? null}
                conversations={grouped[inbox.id] ?? []}
                selectedId={selectedId}
                onSelect={setSelectedId}
                personas={personas}
                providers={providers}
                isAdmin={isAdmin}
                onChanged={onChanged}
                onLocalRefresh={reload}
                setError={setError}
              />
            ))}
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
                providers={providers}
                isAdmin={isAdmin}
                onPatch={patchContact}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function InboxGroup({ inbox, bridge, conversations, selectedId, onSelect, personas, providers, isAdmin, onChanged, onLocalRefresh, setError }: {
  inbox: Inbox;
  bridge: Bridge | null;
  conversations: ConversationSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  personas: Persona[];
  providers: ProviderConfig[];
  isAdmin: boolean;
  onChanged: ChangeHandler;
  onLocalRefresh: () => Promise<void>;
  setError: (message: string) => void;
}) {
  const [showSettings, setShowSettings] = useState(false);
  const online = bridge?.status === 'online';

  return (
    <div className="card" style={{ padding: '12px 14px', display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', minWidth: 0 }}>
          <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 99, background: online ? 'var(--live)' : 'var(--ink-3)' }} />
          <strong style={{ fontSize: 13 }}>{inbox.display_name}</strong>
          <span className="chip muted">{inbox.platform}</span>
          {!inbox.enabled && <span className="chip warn">已停用</span>}
          {bridge && <span className="mono ink-3" style={{ fontSize: 11 }}>{bridge.hostname}</span>}
        </div>
        <button className="btn btn-sm btn-ghost" onClick={() => setShowSettings(value => !value)}>
          {showSettings ? '收起' : '默认值'}
        </button>
      </div>

      {showSettings && (
        <InboxDefaults
          inbox={inbox}
          personas={personas}
          providers={providers}
          isAdmin={isAdmin}
          onChanged={async () => {
            await Promise.resolve(onChanged());
            await onLocalRefresh();
          }}
          setError={setError}
        />
      )}

      {conversations.length === 0 ? (
        <div className="ink-3" style={{ fontSize: 12, padding: '8px 4px' }}>
          暂无粉丝，收到第一条消息时会自动出现。
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 6 }}>
          {conversations.map(item => (
            <button
              key={item.contact.id}
              className="card"
              onClick={() => onSelect(item.contact.id)}
              style={{
                padding: '10px 12px',
                textAlign: 'left',
                borderColor: selectedId === item.contact.id ? 'var(--brass-line)' : 'var(--line-subtle)',
                background: selectedId === item.contact.id ? 'var(--brass-soft)' : 'var(--bg-base)',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center' }}>
                <strong style={{ fontSize: 13 }}>{item.contact.display_name}</strong>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  {item.contact.autoreply_enabled ? <span className="chip live">接管中</span> : <span className="chip muted">手动</span>}
                  <span className="chip muted">{item.message_count}</span>
                </div>
              </div>
              <div className="ink-2" style={{ fontSize: 12, marginTop: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {item.latest_message ? `${item.latest_message.role === 'self' ? '我' : '对方'}：${item.latest_message.content}` : '暂无消息'}
              </div>
              <div className="mono ink-3" style={{ fontSize: 10, marginTop: 4 }}>
                {item.latest_message ? formatDateTime(item.latest_message.timestamp) : formatDateTime(item.contact.updated_at)}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function InboxDefaults({ inbox, personas, providers, isAdmin, onChanged, setError }: {
  inbox: Inbox;
  personas: Persona[];
  providers: ProviderConfig[];
  isAdmin: boolean;
  onChanged: ChangeHandler;
  setError: (message: string) => void;
}) {
  return (
    <div style={{ display: 'grid', gap: 6, padding: '8px 10px', background: 'var(--bg-raised)', borderRadius: 8, border: '1px solid var(--line-subtle)' }}>
      <div className="mono ink-3" style={{ fontSize: 11 }}>
        新粉丝默认（已存在的粉丝不受影响）
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: isAdmin ? '1fr 1fr' : '1fr', gap: 8 }}>
        <label style={{ fontSize: 11, color: 'var(--ink-3)' }}>
          默认人设
          <select
            value={inbox.default_persona_id ?? ''}
            className="select"
            style={{ marginLeft: 6, marginTop: 2 }}
            onChange={async event => {
              if (!event.target.value) return;
              try {
                await api.updateInbox(inbox.id, { default_persona_id: event.target.value });
                await Promise.resolve(onChanged());
              } catch (err) {
                setError(String(err));
              }
            }}
          >
            <option value="">（未选）</option>
            {personas.map(persona => <option key={persona.id} value={persona.id}>{persona.name}</option>)}
          </select>
        </label>
        {isAdmin && (
          <label style={{ fontSize: 11, color: 'var(--ink-3)' }}>
            默认 Provider
            <select
              value={inbox.reply_provider_config_id ?? ''}
              className="select"
              style={{ marginLeft: 6, marginTop: 2 }}
              onChange={async event => {
                try {
                  if (event.target.value) {
                    await api.updateInbox(inbox.id, { reply_provider_config_id: event.target.value });
                  } else {
                    await api.updateInbox(inbox.id, { clear_reply_provider: true });
                  }
                  await Promise.resolve(onChanged());
                } catch (err) {
                  setError(String(err));
                }
              }}
            >
              <option value="">跟随全局默认</option>
              {providers.map(provider => <option key={provider.id} value={provider.id}>{provider.name}{provider.is_default ? ' · 全局默认' : ''}</option>)}
            </select>
          </label>
        )}
      </div>
      <div>
        <button
          className="btn btn-sm btn-ghost"
          onClick={async () => {
            try {
              await api.updateInbox(inbox.id, { enabled: !inbox.enabled });
              await Promise.resolve(onChanged());
            } catch (err) {
              setError(String(err));
            }
          }}
        >
          {inbox.enabled ? '停用整个接管号' : '启用整个接管号'}
        </button>
      </div>
    </div>
  );
}

function ContactDetail({ contact, inbox, bridge, messages, personas, providers, isAdmin, onPatch }: {
  contact: Contact;
  inbox: Inbox;
  bridge: Bridge | null;
  messages: Message[];
  personas: Persona[];
  providers: ProviderConfig[];
  isAdmin: boolean;
  onPatch: (contactId: string, patch: Parameters<typeof api.updateContact>[1]) => Promise<void>;
}) {
  const [draftCard, setDraftCard] = useState(contact.card_md ?? '');
  const [savingCard, setSavingCard] = useState(false);

  useEffect(() => {
    setDraftCard(contact.card_md ?? '');
  }, [contact.id, contact.card_md]);

  const inboxLive = inbox.enabled && Boolean(bridge && bridge.status === 'online');
  const canAutoreply = inboxLive && Boolean(contact.persona_id);

  return (
    <div style={{ display: 'grid', gap: 14 }}>
      <div style={{ borderBottom: '1px solid var(--line-subtle)', paddingBottom: 12 }}>
        <div style={{ fontWeight: 600, fontSize: 16 }}>{contact.display_name}</div>
        <div className="mono ink-3" style={{ fontSize: 11, marginTop: 4 }}>
          {inbox.display_name} · {inbox.platform} · 粉丝平台 ID {contact.peer_platform_id}
        </div>
      </div>

      <div style={{ display: 'grid', gap: 8, padding: 12, background: 'var(--bg-raised)', borderRadius: 8, border: '1px solid var(--line-subtle)' }}>
        <div className="mono ink-3" style={{ fontSize: 11 }}>这个粉丝的接管设置</div>
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
          {isAdmin ? (
            <label style={{ fontSize: 11, color: 'var(--ink-3)' }}>
              Provider
              <select
                value={contact.reply_provider_config_id ?? ''}
                className="select"
                style={{ marginLeft: 6 }}
                onChange={event => {
                  if (event.target.value) {
                    onPatch(contact.id, { reply_provider_config_id: event.target.value });
                  } else {
                    onPatch(contact.id, { clear_reply_provider: true });
                  }
                }}
              >
                <option value="">
                  跟随接管号/全局默认（{providers.find(provider => provider.id === inbox.reply_provider_config_id)?.name ?? '全局默认'}）
                </option>
                {providers.map(provider => <option key={provider.id} value={provider.id}>{provider.name}{provider.is_default ? ' · 全局默认' : ''}</option>)}
              </select>
            </label>
          ) : (
            <span className="chip muted">模型由管理员统一配置</span>
          )}
          <label className="mono" style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 6 }}>
            <input
              type="checkbox"
              checked={contact.autoreply_enabled}
              disabled={!canAutoreply && !contact.autoreply_enabled}
              onChange={event => onPatch(contact.id, { autoreply_enabled: event.target.checked })}
            />
            自动接管
          </label>
        </div>
        {!canAutoreply && (
          <div className="mono" style={{ fontSize: 11, color: 'var(--warn)' }}>
            {!bridge && '— 这个接管号没绑定在线设备；'}
            {bridge && bridge.status !== 'online' && `— 设备 ${bridge.hostname} 离线；`}
            {!inbox.enabled && '— 接管号已停用；'}
            {!contact.persona_id && '— 没有人设；'}
            自动接管启不来。
          </div>
        )}

        <label className="ink-3" style={{ fontSize: 11 }}>关系卡（card_md）— 简单写下你跟这个人的关系，AI 回复时会读到</label>
        <textarea
          className="textarea mono"
          style={{ minHeight: 90, fontSize: 12 }}
          value={draftCard}
          onChange={event => setDraftCard(event.target.value)}
          placeholder="例如：北京大学生，喜欢户外，去年送过我一袋茶叶，叫我 alice 姐"
        />
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 6 }}>
          {draftCard !== (contact.card_md ?? '') && (
            <button className="btn btn-sm btn-ghost" onClick={() => setDraftCard(contact.card_md ?? '')}>
              放弃修改
            </button>
          )}
          <button
            className="btn btn-sm btn-primary"
            disabled={savingCard || draftCard === (contact.card_md ?? '')}
            onClick={async () => {
              setSavingCard(true);
              try {
                await onPatch(contact.id, { card_md: draftCard });
              } finally {
                setSavingCard(false);
              }
            }}
          >
            {savingCard ? '保存中…' : '保存关系卡'}
          </button>
        </div>
      </div>

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
      <PageHead title="设备" kicker="devices · 你的本地守护进程" />
      <div style={{ padding: '0 28px 24px', display: 'grid', gap: 14 }}>
        <BridgeCommandPanel meUsername={meUsername} setError={setError} />
        {bridges.length === 0 ? (
          <Empty>
            还没有设备。复制上面命令到主播的 PC 上运行；接好 chat 账号后会自动注册到这里。
          </Empty>
        ) : (
          <div style={{ display: 'grid', gap: 10 }}>
            {bridges.map(bridge => (
              <div key={bridge.id} className="card" style={{ padding: '14px 16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
                  <div>
                    <div style={{ fontWeight: 500, display: 'flex', alignItems: 'center', gap: 8 }}>
                      <StatusDot status={bridge.status} />
                      {bridge.hostname}
                      <span className={`chip ${statusChipClass(bridge.status)}`}>{statusText(bridge.status)}</span>
                    </div>
                    <div className="mono ink-3" style={{ fontSize: 11, marginTop: 4 }}>
                      最后心跳 {formatDateTime(bridge.last_seen_at)} · 承载 {(inboxesByBridge[bridge.id] || []).length} 个接管号
                    </div>
                  </div>
                  <button
                    className="btn btn-sm btn-ghost"
                    style={{ color: 'var(--danger)' }}
                    onClick={async () => {
                      if (!confirm(`确认撤销设备 ${bridge.hostname}？该机器上的接管号会从它身上脱钩，daemon 下次调用会被 401。`)) return;
                      try {
                        await api.deleteBridge(bridge.id);
                        await Promise.resolve(onChanged());
                      } catch (err) {
                        setError(String(err));
                      }
                    }}
                  >
                    撤销
                  </button>
                </div>
                {(inboxesByBridge[bridge.id] || []).length > 0 && (
                  <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--line-subtle)', display: 'grid', gap: 6 }}>
                    {(inboxesByBridge[bridge.id] || []).map(inbox => (
                      <div key={inbox.id} className="mono" style={{ fontSize: 11, color: 'var(--ink-2)' }}>
                        {inbox.platform} · {inbox.platform_self_id || '—'} · {inbox.display_name} · {inbox.enabled ? '启用' : '停用'}
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
  const color =
    status === 'online' ? 'var(--live)' :
    status === 'revoked' ? 'var(--danger)' : 'var(--ink-3)';
  return <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: 99, background: color }} />;
}

function statusText(status: Bridge['status']): string {
  if (status === 'online') return '在线';
  if (status === 'offline') return '离线';
  return '已撤销';
}

function statusChipClass(status: Bridge['status']): string {
  if (status === 'online') return 'live';
  if (status === 'revoked') return 'danger';
  return 'muted';
}

function PersonasView({ personas, onChanged, setError }: {
  personas: Persona[];
  onChanged: ChangeHandler;
  setError: (message: string) => void;
}) {
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<Persona | null>(null);

  return (
    <div>
      <PageHead
        title="人设"
        kicker="personas"
        right={<button className="btn btn-primary btn-sm" onClick={() => setShowCreate(true)}>+ 新建</button>}
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
                      {persona.name} <span className="chip muted">{persona.status}</span>
                    </div>
                    <div className="mono ink-3" style={{ fontSize: 11, marginTop: 4 }}>
                      {persona.persona_md ? `${persona.persona_md.slice(0, 80)}${persona.persona_md.length > 80 ? '…' : ''}` : '（空）'}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button className="btn btn-sm btn-ghost" onClick={() => setEditing(persona)}>编辑</button>
                    <button
                      className="btn btn-sm btn-ghost"
                      style={{ color: 'var(--danger)' }}
                      onClick={async () => {
                        if (!confirm('确认删除？被引用时会失败。')) return;
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
          onCreated={async () => {
            setShowCreate(false);
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

function CreatePersonaModal({ onClose, onCreated, setError }: {
  onClose: () => void;
  onCreated: () => void | Promise<void>;
  setError: (message: string) => void;
}) {
  const [name, setName] = useState('');
  const [md, setMd] = useState('');
  const [busy, setBusy] = useState(false);

  const handle = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await api.createPersona({ name: name.trim(), persona_md: md || null });
      await Promise.resolve(onCreated());
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell onClose={onClose} title="新建人设">
      <FormField label="名称"><input className="input" value={name} onChange={event => setName(event.target.value)} autoFocus /></FormField>
      <FormField label="persona_md (可空)">
        <textarea className="textarea mono" style={{ minHeight: 200 }} value={md} onChange={event => setMd(event.target.value)} />
      </FormField>
      <ModalActions onCancel={onClose} onConfirm={handle} confirmLabel={busy ? '创建中...' : '创建'} disabled={busy || !name.trim()} />
    </ModalShell>
  );
}

function EditPersonaModal({ persona, onClose, onSaved, setError }: {
  persona: Persona;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
  setError: (message: string) => void;
}) {
  const [name, setName] = useState(persona.name);
  const [md, setMd] = useState(persona.persona_md ?? '');
  const [busy, setBusy] = useState(false);

  const handle = async () => {
    setBusy(true);
    try {
      await api.updatePersona(persona.id, { name, persona_md: md || null });
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
      <FormField label="persona_md">
        <textarea className="textarea mono" style={{ minHeight: 320 }} value={md} onChange={event => setMd(event.target.value)} />
      </FormField>
      <ModalActions onCancel={onClose} onConfirm={handle} confirmLabel={busy ? '保存中...' : '保存'} disabled={busy} />
    </ModalShell>
  );
}

function SettingsView({ providers, me, isAdmin, onChanged, setError }: {
  providers: ProviderConfig[];
  me: string;
  isAdmin: boolean;
  onChanged: ChangeHandler;
  setError: (message: string) => void;
}) {
  const [showCreate, setShowCreate] = useState(false);
  const [accounts, setAccounts] = useState<Account[]>([]);

  const loadAccounts = useCallback(async () => {
    if (!isAdmin) return;
    try {
      setAccounts(await api.getAccounts());
    } catch (err) {
      setError(String(err));
    }
  }, [isAdmin, setError]);

  useEffect(() => {
    loadAccounts();
  }, [loadAccounts]);

  return (
    <div>
      <PageHead title="设置" kicker="settings" />
      <div style={{ padding: '0 28px 24px', display: 'grid', gridTemplateColumns: '220px minmax(0, 1fr)', gap: 24 }}>
        <nav style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span className="eyebrow" style={{ padding: '6px 10px' }}>账号</span>
          <button className="btn btn-ghost" style={{ justifyContent: 'flex-start' }}>个人 · @{me}</button>
          {isAdmin && <span className="eyebrow mt-3" style={{ padding: '6px 10px', marginTop: 12 }}>系统</span>}
          {isAdmin && <button className="btn" style={{ justifyContent: 'flex-start', background: 'var(--bg-raised)' }}>Provider</button>}
        </nav>
        <div style={{ display: 'grid', gap: 14 }}>
          <PasswordPanel me={me} setError={setError} />
          {isAdmin && <AccountsPanel accounts={accounts} onChanged={loadAccounts} setError={setError} />}
          {isAdmin && <ProviderPanel providers={providers} onChanged={onChanged} onCreate={() => setShowCreate(true)} setError={setError} />}
          {!isAdmin && (
            <div className="card p-5">
              <div style={{ fontWeight: 600, marginBottom: 8 }}>模型配置</div>
              <div className="text-sm text-ink-3">模型 Provider 由管理员统一配置，接管时无需选择模型。</div>
            </div>
          )}
        </div>
      </div>
      {isAdmin && showCreate && (
        <CreateProviderModal
          onClose={() => setShowCreate(false)}
          onCreated={async () => {
            setShowCreate(false);
            await Promise.resolve(onChanged());
          }}
          setError={setError}
        />
      )}
    </div>
  );
}

function PasswordPanel({ me, setError }: { me: string; setError: (message: string) => void }) {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [ok, setOk] = useState('');

  const handle = async () => {
    if (!currentPassword || !newPassword) return;
    setBusy(true);
    setOk('');
    try {
      await api.changeOwnPassword({ current_password: currentPassword, new_password: newPassword });
      setCurrentPassword('');
      setNewPassword('');
      setOk('密码已更新，请重新登录。');
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card p-5">
      <div style={{ fontWeight: 600, marginBottom: 8 }}>个人 · @{me}</div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 8, alignItems: 'end' }}>
        <FormField label="当前密码"><input className="input" type="password" value={currentPassword} onChange={event => setCurrentPassword(event.target.value)} /></FormField>
        <FormField label="新密码"><input className="input" type="password" value={newPassword} onChange={event => setNewPassword(event.target.value)} /></FormField>
        <button className="btn btn-primary btn-sm" onClick={handle} disabled={busy || !currentPassword || !newPassword}>{busy ? '保存中…' : '重置密码'}</button>
      </div>
      {ok && <div className="mono" style={{ color: 'var(--live)', fontSize: 11 }}>{ok}</div>}
    </div>
  );
}

function AccountsPanel({ accounts, onChanged, setError }: {
  accounts: Account[];
  onChanged: ChangeHandler;
  setError: (message: string) => void;
}) {
  const [showCreate, setShowCreate] = useState(false);
  const [resetting, setResetting] = useState<Account | null>(null);

  return (
    <div className="card p-5">
      <div className="row gap-2" style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <span style={{ fontWeight: 600 }}>账号 · 用户管理</span>
        <button className="btn btn-sm btn-primary" style={{ marginLeft: 'auto' }} onClick={() => setShowCreate(true)}>+ 新账号</button>
      </div>
      {accounts.length === 0 ? <Empty>还没有账号。</Empty> : (
        <div style={{ display: 'grid', gap: 10 }}>
          {accounts.map(account => (
            <div key={account.id} className="card" style={{ padding: '12px 14px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                <div>
                  <div style={{ fontWeight: 500 }}>@{account.username} <span className="chip muted">{account.role}</span> <span className={`chip ${account.status === 'active' ? 'live' : 'danger'}`}>{account.status}</span></div>
                  <div className="mono ink-3" style={{ fontSize: 11, marginTop: 4 }}>{account.display_name || '未命名'} · 最后登录 {formatDateTime(account.last_login_at)}</div>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button className="btn btn-sm btn-ghost" onClick={() => setResetting(account)}>重置密码</button>
                  <button
                    className="btn btn-sm btn-ghost"
                    onClick={async () => {
                      try {
                        await api.updateAccount(account.id, { status: account.status === 'active' ? 'disabled' : 'active' });
                        await Promise.resolve(onChanged());
                      } catch (err) { setError(String(err)); }
                    }}
                  >
                    {account.status === 'active' ? '停用' : '启用'}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
      {showCreate && <CreateAccountModal onClose={() => setShowCreate(false)} onCreated={async () => { setShowCreate(false); await Promise.resolve(onChanged()); }} setError={setError} />}
      {resetting && <ResetAccountPasswordModal account={resetting} onClose={() => setResetting(null)} onSaved={async () => { setResetting(null); await Promise.resolve(onChanged()); }} setError={setError} />}
    </div>
  );
}

function ProviderPanel({ providers, onChanged, onCreate, setError }: {
  providers: ProviderConfig[];
  onChanged: ChangeHandler;
  onCreate: () => void;
  setError: (message: string) => void;
}) {
  return (
    <div className="card p-5">
      <div className="row gap-2" style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
        <span style={{ fontWeight: 600 }}>Provider · LLM 接入</span>
        <button className="btn btn-sm btn-primary" style={{ marginLeft: 'auto' }} onClick={onCreate}>+ 新接入</button>
      </div>
      <div className="text-sm text-ink-3" style={{ marginBottom: 12 }}>管理员维护全局默认模型；未来可在接管上覆盖。</div>
      {providers.length === 0 ? <Empty>还没有 Provider。</Empty> : (
        <div style={{ display: 'grid', gap: 10 }}>
          {providers.map(provider => (
            <div key={provider.id} className="card" style={{ padding: '14px 16px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
                <div>
                  <div style={{ fontWeight: 500 }}>{provider.name} {provider.is_default && <span className="chip live">全局默认</span>}</div>
                  <div className="mono ink-3" style={{ fontSize: 11, marginTop: 4 }}>{provider.base_url} · model: {provider.default_model} · key: {provider.api_key_preview ?? '未设置'}</div>
                </div>
                <button
                  className="btn btn-sm btn-ghost"
                  style={{ color: 'var(--danger)' }}
                  onClick={async () => {
                    if (!confirm('确认删除？')) return;
                    try { await api.deleteProviderConfig(provider.id); await Promise.resolve(onChanged()); }
                    catch (err) { setError(String(err)); }
                  }}
                >删除</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CreateProviderModal({ onClose, onCreated, setError }: {
  onClose: () => void;
  onCreated: () => void | Promise<void>;
  setError: (message: string) => void;
}) {
  const [name, setName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState('');
  const [busy, setBusy] = useState(false);

  const handle = async () => {
    if (!name.trim() || !baseUrl.trim() || !model.trim()) return;
    setBusy(true);
    try {
      await api.createProviderConfig({
        name: name.trim(),
        base_url: baseUrl.trim(),
        api_key: apiKey || null,
        default_model: model.trim(),
      });
      await Promise.resolve(onCreated());
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell onClose={onClose} title="新建 Provider Config">
      <FormField label="名称"><input className="input" value={name} onChange={event => setName(event.target.value)} placeholder="例如 Deepseek" autoFocus /></FormField>
      <FormField label="base_url"><input className="input mono" value={baseUrl} onChange={event => setBaseUrl(event.target.value)} placeholder="https://api.deepseek.com" /></FormField>
      <FormField label="api_key"><input className="input mono" type="password" value={apiKey} onChange={event => setApiKey(event.target.value)} /></FormField>
      <FormField label="default_model"><input className="input mono" value={model} onChange={event => setModel(event.target.value)} placeholder="deepseek-chat" /></FormField>
      <ModalActions onCancel={onClose} onConfirm={handle} confirmLabel={busy ? '创建中...' : '创建'} disabled={busy || !name.trim() || !baseUrl.trim() || !model.trim()} />
    </ModalShell>
  );
}

function CreateAccountModal({ onClose, onCreated, setError }: {
  onClose: () => void;
  onCreated: () => void | Promise<void>;
  setError: (message: string) => void;
}) {
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<AccountRole>('user');
  const [busy, setBusy] = useState(false);

  const handle = async () => {
    if (!username.trim() || !password) return;
    setBusy(true);
    try {
      await api.createAccount({
        username: username.trim(),
        password,
        display_name: displayName.trim() || null,
        role,
      });
      await Promise.resolve(onCreated());
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell onClose={onClose} title="新建账号">
      <FormField label="username"><input className="input mono" value={username} onChange={event => setUsername(event.target.value)} autoFocus /></FormField>
      <FormField label="display_name"><input className="input" value={displayName} onChange={event => setDisplayName(event.target.value)} /></FormField>
      <FormField label="password"><input className="input mono" type="password" value={password} onChange={event => setPassword(event.target.value)} /></FormField>
      <FormField label="role">
        <select className="select" value={role} onChange={event => setRole(event.target.value as AccountRole)}>
          <option value="user">普通用户</option>
          <option value="admin">管理员</option>
        </select>
      </FormField>
      <ModalActions onCancel={onClose} onConfirm={handle} confirmLabel={busy ? '创建中...' : '创建'} disabled={busy || !username.trim() || !password} />
    </ModalShell>
  );
}

function ResetAccountPasswordModal({ account, onClose, onSaved, setError }: {
  account: Account;
  onClose: () => void;
  onSaved: () => void | Promise<void>;
  setError: (message: string) => void;
}) {
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);

  const handle = async () => {
    if (!password) return;
    setBusy(true);
    try {
      await api.resetAccountPassword(account.id, password);
      await Promise.resolve(onSaved());
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell onClose={onClose} title={`重置密码 · @${account.username}`}>
      <FormField label="新密码"><input className="input mono" type="password" value={password} onChange={event => setPassword(event.target.value)} autoFocus /></FormField>
      <div className="mono ink-3" style={{ fontSize: 11 }}>保存后该账号已有网页登录态会失效。</div>
      <ModalActions onCancel={onClose} onConfirm={handle} confirmLabel={busy ? '保存中...' : '保存'} disabled={busy || !password} />
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

function buildBridgeCommand({
  studioUsername,
  studioUrl,
  chatBaseUrl,
  chatUsername,
}: {
  studioUsername: string;
  studioUrl: string;
  chatBaseUrl: string;
  chatUsername: string;
}): string {
  return [
    'docker compose run --rm bridge \\',
    `  --studio-username=${studioUsername || '<studio账号>'} \\`,
    '  --studio-password=<填入你的密码> \\',
    `  --studio-url=${studioUrl} \\`,
    `  --chat-inbox 'base_url=${chatBaseUrl},username=${chatUsername || '<chat账号>'},password=<chat账号密码>'`,
  ].join('\n');
}

function BridgeCommandPanel({ meUsername, setError }: {
  meUsername: string;
  setError: (message: string) => void;
}) {
  const [studioUrl, setStudioUrl] = useState('http://host.docker.internal:23457');
  const [chatBaseUrl, setChatBaseUrl] = useState('http://host.docker.internal:23456');
  const [chatUsername, setChatUsername] = useState(meUsername);
  const [copied, setCopied] = useState(false);

  const command = useMemo(
    () => buildBridgeCommand({
      studioUsername: meUsername,
      studioUrl,
      chatBaseUrl,
      chatUsername,
    }),
    [meUsername, studioUrl, chatBaseUrl, chatUsername],
  );

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (err) {
      setError(String(err));
    }
  };

  return (
    <div className="card" style={{ padding: 16, display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>快速生成命令</span>
        <span className="mono ink-3" style={{ fontSize: 11 }}>
          在主播 PC 的 <span className="mono">services/bridge/</span> 下执行
        </span>
        <button className="btn btn-sm btn-ghost" style={{ marginLeft: 'auto' }} onClick={onCopy}>
          {copied ? '已复制' : '复制命令'}
        </button>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
        <label className="mono ink-3" style={{ fontSize: 11 }}>
          studio-url
          <input className="input mono" style={{ marginTop: 2 }} value={studioUrl} onChange={e => setStudioUrl(e.target.value)} />
        </label>
        <label className="mono ink-3" style={{ fontSize: 11 }}>
          chat base_url
          <input className="input mono" style={{ marginTop: 2 }} value={chatBaseUrl} onChange={e => setChatBaseUrl(e.target.value)} />
        </label>
        <label className="mono ink-3" style={{ fontSize: 11 }}>
          chat username
          <input className="input mono" style={{ marginTop: 2 }} value={chatUsername} onChange={e => setChatUsername(e.target.value)} placeholder="alice" />
        </label>
      </div>
      <pre
        className="mono"
        style={{
          margin: 0,
          padding: 12,
          background: 'var(--bg-deep)',
          border: '1px solid var(--line-subtle)',
          borderRadius: 8,
          fontSize: 12,
          lineHeight: 1.55,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
          color: 'var(--ink-2)',
        }}
      >{command}</pre>
      <div className="mono ink-3" style={{ fontSize: 11 }}>
        密码不要写进命令历史；建议 <span className="mono">read -s</span> 或 <span className="mono">.env</span> 注入。
      </div>
    </div>
  );
}

function OverviewView({ setError }: { setError: (message: string) => void }) {
  const [data, setData] = useState<api.AdminOverview | null>(null);
  const [loading, setLoading] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.getAdminOverview());
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, [setError]);

  useEffect(() => {
    reload();
  }, [reload]);

  return (
    <div>
      <PageHead
        title="总览"
        kicker="overview · SaaS 运营视角"
        right={<button className="btn btn-sm btn-ghost" onClick={reload}>{loading ? '刷新中…' : '刷新'}</button>}
      />
      <div style={{ padding: '0 28px 24px', display: 'grid', gap: 14 }}>
        {!data ? (
          <Empty>正在加载…</Empty>
        ) : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 10 }}>
              <StatCard label="账号" value={data.totals.accounts} sub={`管理员 ${data.totals.admins} · 用户 ${data.totals.users}`} />
              <StatCard label="设备" value={`${data.totals.bridges_online} 在线`} sub={`离线 ${data.totals.bridges_offline}`} />
              <StatCard label="接管号" value={data.totals.inboxes} />
              <StatCard label="人设" value={data.totals.personas} />
              <StatCard label="粉丝" value={data.totals.contacts} sub={`接管中 ${data.totals.contacts_autoreply}`} />
              <StatCard label="消息" value={data.totals.messages} />
              <StatCard label="Provider" value={data.totals.providers} />
              <StatCard label="待发 outbound" value={data.totals.outbound_pending} />
            </div>

            <div className="card" style={{ padding: 16 }}>
              <div style={{ fontWeight: 600, marginBottom: 10 }}>账号明细</div>
              {data.accounts.length === 0 ? (
                <Empty>系统里还没有账号。用 <span className="mono">python -m studio.cli create-account</span> 创建一个。</Empty>
              ) : (
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <thead>
                      <tr style={{ textAlign: 'left', color: 'var(--ink-3)' }}>
                        <th style={overviewTh}>账号</th>
                        <th style={overviewTh}>角色</th>
                        <th style={overviewTh}>状态</th>
                        <th style={overviewTh}>最后登录</th>
                        <th style={overviewTh}>设备</th>
                        <th style={overviewTh}>接管号</th>
                        <th style={overviewTh}>人设</th>
                        <th style={overviewTh}>粉丝(接管中)</th>
                        <th style={overviewTh}>消息</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.accounts.map(row => (
                        <tr key={row.account.id} style={{ borderTop: '1px solid var(--line-subtle)' }}>
                          <td style={overviewTd}>
                            <div style={{ fontWeight: 500 }}>@{row.account.username}</div>
                            <div className="mono ink-3" style={{ fontSize: 10 }}>{row.account.display_name || '未命名'}</div>
                          </td>
                          <td style={overviewTd}>
                            <span className={`chip ${row.account.role === 'admin' ? 'warn' : 'muted'}`}>{row.account.role}</span>
                          </td>
                          <td style={overviewTd}>
                            <span className={`chip ${row.account.status === 'active' ? 'live' : 'danger'}`}>{row.account.status}</span>
                          </td>
                          <td style={overviewTd} className="mono ink-3">{formatDateTime(row.account.last_login_at)}</td>
                          <td style={overviewTd}>
                            <span className="mono">{row.bridges_online}</span>
                            <span className="ink-3" style={{ fontSize: 10 }}> / {row.bridges_online + row.bridges_offline}</span>
                          </td>
                          <td style={overviewTd}>{row.inboxes}</td>
                          <td style={overviewTd}>{row.personas}</td>
                          <td style={overviewTd}>
                            <span className="mono">{row.contacts}</span>
                            <span className="ink-3" style={{ fontSize: 10 }}> ({row.contacts_autoreply})</span>
                          </td>
                          <td style={overviewTd}>{row.messages}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const overviewTh: CSSProperties = { padding: '6px 10px', fontWeight: 500, fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.04em' };
const overviewTd: CSSProperties = { padding: '8px 10px', verticalAlign: 'middle' };

function StatCard({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="card" style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span className="eyebrow">{label}</span>
      <span className="serif" style={{ fontSize: 26, lineHeight: 1, letterSpacing: '-0.02em' }}>{value}</span>
      {sub && <span className="mono ink-3" style={{ fontSize: 11 }}>{sub}</span>}
    </div>
  );
}
