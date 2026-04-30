import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { LaborsterLogo, IconPlus, IconArrowLeft } from '../components/Icons';
import { Modal } from '../components/Modal';
import { cn } from '../lib/utils';
import * as api from '../lib/api';
import type { ChatUser, Conversation, Session, ProviderConfig } from '../lib/api';
import { PROVIDER_TEMPLATES } from '../lib/templates';

export function RobotPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [providerConfigs, setProviderConfigs] = useState<ProviderConfig[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [users, setUsers] = useState<ChatUser[]>([]);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<'sessions' | 'providers'>('sessions');

  // Takeover modal
  const [showTakeover, setShowTakeover] = useState(false);
  const [selectedConvId, setSelectedConvId] = useState('');
  const [selectedUserId, setSelectedUserId] = useState('');
  const [takeoverProfile, setTakeoverProfile] = useState('');
  const [counterpartProfile, setCounterpartProfile] = useState('');
  const [selectedProviderId, setSelectedProviderId] = useState('');

  // Provider modal
  const [showCreateProvider, setShowCreateProvider] = useState(false);
  const [providerName, setProviderName] = useState('');
  const [providerBaseUrl, setProviderBaseUrl] = useState('');
  const [providerApiKey, setProviderApiKey] = useState('');
  const [providerModel, setProviderModel] = useState('');
  const [selectedTemplate, setSelectedTemplate] = useState(-1);

  // Edit session modal
  const [editingSession, setEditingSession] = useState<Session | null>(null);
  const [editProfile, setEditProfile] = useState('');
  const [editCounterpartProfile, setEditCounterpartProfile] = useState('');
  const [editProviderId, setEditProviderId] = useState('');

  const loadSessions = useCallback(async () => {
    try { setSessions(await api.getSessions()); } catch (e) { setError(String(e)); }
  }, []);

  const loadProviders = useCallback(async () => {
    try { setProviderConfigs(await api.getProviderConfigs()); } catch (e) { setError(String(e)); }
  }, []);

  const loadConversations = useCallback(async () => {
    try { setConversations(await api.getRobotConversations()); } catch (e) { setError(String(e)); }
  }, []);

  const loadUsers = useCallback(async () => {
    try { setUsers(await api.getUsers(true)); } catch (e) { setError(String(e)); }
  }, []);

  useEffect(() => { loadSessions(); loadProviders(); loadUsers(); loadConversations(); }, [loadSessions, loadProviders, loadUsers, loadConversations]);

  const userMap = new Map(users.map(u => [u.id, u.name]));
  const userName = (id: string) => userMap.get(id) || id;

  const selectedConv = conversations.find(c => c.id === selectedConvId);

  // Takeover
  const openTakeover = async () => {
    await loadConversations();
    setSelectedConvId('');
    setSelectedUserId('');
    setTakeoverProfile('');
    setCounterpartProfile('');
    setSelectedProviderId(providerConfigs.length > 0 ? providerConfigs[0].id : '');
    setShowTakeover(true);
  };

  const handleTakeover = async () => {
    if (!selectedConvId || !selectedUserId) return;
    try {
      await api.createSession({
        adapter_thread_id: selectedConvId,
        takeover_user_id: selectedUserId,
        profile: takeoverProfile || null,
        counterpart_profile: counterpartProfile || null,
        provider_config_id: selectedProviderId || null,
      });
      setShowTakeover(false);
      await loadSessions();
    } catch (e) { setError(String(e)); }
  };

  // Toggle session status
  const handleToggleSession = async (session: Session) => {
    const newStatus = session.status === 'active' ? 'paused' : 'active';
    try {
      await api.updateSession(session.id, { status: newStatus });
      await loadSessions();
    } catch (e) { setError(String(e)); }
  };

  // Delete session
  const handleDeleteSession = async (sessionId: string) => {
    try {
      await api.deleteSession(sessionId);
      await loadSessions();
    } catch (e) { setError(String(e)); }
  };

  // Edit session
  const openEditSession = (session: Session) => {
    setEditingSession(session);
    setEditProfile(session.profile || '');
    setEditCounterpartProfile(session.counterpart_profile || '');
    setEditProviderId(session.provider_config_id || '');
  };

  const handleEditSession = async () => {
    if (!editingSession) return;
    try {
      await api.updateSession(editingSession.id, {
        profile: editProfile || null,
        counterpart_profile: editCounterpartProfile || null,
        provider_config_id: editProviderId || null,
      });
      setEditingSession(null);
      await loadSessions();
    } catch (e) { setError(String(e)); }
  };

  // Create provider
  const handleCreateProvider = async () => {
    if (!providerName.trim() || !providerBaseUrl.trim() || !providerModel.trim()) return;
    try {
      await api.createProviderConfig({
        name: providerName.trim(),
        base_url: providerBaseUrl.trim(),
        api_key: providerApiKey || null,
        default_model: providerModel.trim(),
      });
      setProviderName(''); setProviderBaseUrl(''); setProviderApiKey(''); setProviderModel(''); setSelectedTemplate(-1);
      setShowCreateProvider(false);
      await loadProviders();
    } catch (e) { setError(String(e)); }
  };

  // Delete provider
  const handleDeleteProvider = async (id: string) => {
    try { await api.deleteProviderConfig(id); await loadProviders(); } catch (e) { setError(String(e)); }
  };

  return (
    <div className="w-full h-dvh overflow-hidden flex flex-col bg-bg-primary text-text-primary">
      {/* Header */}
      <header className="h-14 flex items-center justify-between px-6 border-b border-border-glow/20 shrink-0 bg-bg-secondary/80 backdrop-blur-sm">
        <div className="flex items-center gap-4">
          <Link to="/" className="flex items-center gap-2 text-text-secondary hover:text-accent transition-colors">
            <IconArrowLeft size={18} />
            <span className="text-sm">返回</span>
          </Link>
          <div className="w-px h-5 bg-border-glow/30" />
          <div className="flex items-center gap-2">
            <LaborsterLogo size={22} />
            <span className="font-brand font-medium tracking-wider text-sm text-accent">Robot</span>
          </div>
        </div>
      </header>

      {/* Error */}
      {error && (
        <div className="mx-6 mt-3 px-4 py-3 bg-danger-bg rounded-xl text-sm text-danger flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError('')} className="ml-2 text-danger hover:opacity-70">&times;</button>
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-border-glow/20 px-6">
        <button
          onClick={() => setTab('sessions')}
          className={cn('px-4 py-3 text-sm font-medium transition-colors', tab === 'sessions' ? 'text-accent border-b-2 border-accent' : 'text-text-secondary hover:text-text-primary')}
        >接管的会话</button>
        <button
          onClick={() => setTab('providers')}
          className={cn('px-4 py-3 text-sm font-medium transition-colors', tab === 'providers' ? 'text-accent border-b-2 border-accent' : 'text-text-secondary hover:text-text-primary')}
        >LLM Provider</button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-4xl mx-auto">
          {tab === 'sessions' ? (
            <div>
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-lg font-medium">接管的会话</h2>
                <button
                  onClick={openTakeover}
                  className="px-4 py-2 flex items-center gap-2 rounded-xl bg-accent/20 text-accent hover:bg-accent/30 transition text-sm font-medium btn-neon"
                >
                  <IconPlus /> 接管新会话
                </button>
              </div>

              {sessions.length === 0 ? (
                <div className="text-center py-16 text-text-secondary">
                  <p>还没有接管任何会话</p>
                  <p className="text-xs mt-1">先在聊天页面创建会话和用户，然后回来接管</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {sessions.map(session => (
                    <div
                      key={session.id}
                      className="group flex items-center justify-between p-4 rounded-xl border border-border-glow/20 bg-bg-secondary/40 hover:bg-bg-secondary/60 transition"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium">
                            {(() => {
                              const conv = conversations.find(c => c.id === session.adapter_thread_id);
                              if (conv) {
                                return `${userName(conv.user_a_id)} ↔ ${userName(conv.user_b_id)}`;
                              }
                              return `会话 ${session.adapter_thread_id}`;
                            })()}
                          </span>
                          <span className={cn(
                            'px-2 py-0.5 rounded-full text-[10px] font-medium',
                            session.status === 'active' ? 'bg-success/10 text-success' : 'bg-warning/10 text-warning'
                          )}>
                            {session.status === 'active' ? '运行中' : '已暂停'}
                          </span>
                        </div>
                        <div className="text-xs text-text-secondary mt-1">
                          AI 扮演: {userName(session.takeover_user_id)}
                          {session.provider_config?.name && ` · Provider: ${session.provider_config.name}`}
                        </div>
                        {session.profile && (
                          <div className="text-xs text-text-tertiary mt-1 truncate">人设: {session.profile.slice(0, 80)}...</div>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => handleToggleSession(session)}
                          className={cn(
                            'px-3 py-1.5 text-xs rounded-lg transition font-medium',
                            session.status === 'active'
                              ? 'bg-warning/10 text-warning hover:bg-warning/20'
                              : 'bg-success/10 text-success hover:bg-success/20'
                          )}
                        >{session.status === 'active' ? '暂停' : '启动'}</button>
                        <button
                          onClick={() => openEditSession(session)}
                          className="px-3 py-1.5 text-xs rounded-lg bg-bg-tertiary hover:bg-accent/10 text-text-secondary hover:text-accent transition opacity-0 group-hover:opacity-100"
                        >编辑</button>
                        <button
                          onClick={() => handleDeleteSession(session.id)}
                          className="px-3 py-1.5 text-xs rounded-lg bg-bg-tertiary hover:bg-danger-bg text-text-secondary hover:text-danger transition opacity-0 group-hover:opacity-100"
                        >删除</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div>
              <div className="flex items-center justify-between mb-6">
                <h2 className="text-lg font-medium">LLM Provider 配置</h2>
                <button
                  onClick={() => setShowCreateProvider(true)}
                  className="px-4 py-2 flex items-center gap-2 rounded-xl bg-accent/20 text-accent hover:bg-accent/30 transition text-sm font-medium btn-neon"
                >
                  <IconPlus /> 添加 Provider
                </button>
              </div>

              {providerConfigs.length === 0 ? (
                <div className="text-center py-16 text-text-secondary">还没有配置任何 Provider</div>
              ) : (
                <div className="space-y-3">
                  {providerConfigs.map(pc => (
                    <div
                      key={pc.id}
                      className="group flex items-center justify-between p-4 rounded-xl border border-border-glow/20 bg-bg-secondary/40 hover:bg-bg-secondary/60 transition"
                    >
                      <div>
                        <div className="text-sm font-medium">{pc.name}</div>
                        <div className="text-xs text-text-secondary mt-1">
                          {pc.base_url} · {pc.default_model}
                          {pc.api_key_preview && ` · Key: ${pc.api_key_preview}`}
                        </div>
                      </div>
                      <button
                        onClick={() => handleDeleteProvider(pc.id)}
                        className="opacity-0 group-hover:opacity-100 px-3 py-1.5 text-xs rounded-lg bg-bg-tertiary hover:bg-danger-bg text-text-secondary hover:text-danger transition"
                      >删除</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Takeover Modal */}
      <Modal open={showTakeover} onClose={() => setShowTakeover(false)} maxWidth="max-w-2xl">
        <h3 className="text-lg font-medium mb-4">接管会话</h3>
        <div className="space-y-3 mb-4 max-h-[60vh] overflow-y-auto">
          <div>
            <label className="text-xs text-text-secondary mb-1 block">选择要接管的会话</label>
            <select
              value={selectedConvId}
              onChange={e => { setSelectedConvId(e.target.value); setSelectedUserId(''); }}
              className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50"
            >
              <option value="">选择会话</option>
              {conversations.map(c => (
                <option key={c.id} value={c.id}>
                  {c.title} — {userName(c.user_a_id)} ↔ {userName(c.user_b_id)}
                </option>
              ))}
            </select>
          </div>

          {selectedConv && (
            <div>
              <label className="text-xs text-text-secondary mb-1 block">以哪个用户的身份接管（AI 将扮演此用户）</label>
              <div className="flex gap-2">
                {[selectedConv.user_a_id, selectedConv.user_b_id].map(uid => (
                  <button
                    key={uid}
                    onClick={() => setSelectedUserId(uid)}
                    className={cn(
                      'flex-1 px-4 py-2.5 rounded-xl text-sm border transition-all',
                      selectedUserId === uid
                        ? 'border-accent/50 bg-accent/10 text-accent'
                        : 'border-border-glow/30 bg-bg-tertiary text-text-secondary hover:border-accent/30'
                    )}
                  >
                    {userName(uid)}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div>
            <label className="text-xs text-text-secondary mb-1 block">AI 人设 Profile（System Prompt）</label>
            <textarea
              value={takeoverProfile}
              onChange={e => setTakeoverProfile(e.target.value)}
              placeholder="描述 AI 要扮演的角色..."
              rows={4}
              className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50 resize-none"
            />
          </div>

          <div>
            <label className="text-xs text-text-secondary mb-1 block">对方画像 Profile</label>
            <textarea
              value={counterpartProfile}
              onChange={e => setCounterpartProfile(e.target.value)}
              placeholder="描述对话对象的信息..."
              rows={3}
              className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50 resize-none"
            />
          </div>

          <div>
            <label className="text-xs text-text-secondary mb-1 block">LLM Provider</label>
            <select
              value={selectedProviderId}
              onChange={e => setSelectedProviderId(e.target.value)}
              className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50"
            >
              <option value="">自动选择</option>
              {providerConfigs.map(pc => (
                <option key={pc.id} value={pc.id}>{pc.name} ({pc.default_model})</option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex justify-end gap-3">
          <button onClick={() => setShowTakeover(false)} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">取消</button>
          <button onClick={handleTakeover} disabled={!selectedConvId || !selectedUserId} className="px-4 py-2 text-sm bg-accent/20 text-accent rounded-lg hover:bg-accent/30 disabled:opacity-30">接管</button>
        </div>
      </Modal>

      {/* Edit Session Modal */}
      <Modal open={!!editingSession} onClose={() => setEditingSession(null)} maxWidth="max-w-2xl">
        <h3 className="text-lg font-medium mb-4">编辑 Session</h3>
        <div className="space-y-3 mb-4 max-h-[60vh] overflow-y-auto">
          <div>
            <label className="text-xs text-text-secondary mb-1 block">AI 人设 Profile</label>
            <textarea
              value={editProfile}
              onChange={e => setEditProfile(e.target.value)}
              rows={4}
              className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50 resize-none"
            />
          </div>
          <div>
            <label className="text-xs text-text-secondary mb-1 block">对方画像 Profile</label>
            <textarea
              value={editCounterpartProfile}
              onChange={e => setEditCounterpartProfile(e.target.value)}
              rows={3}
              className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50 resize-none"
            />
          </div>
          <div>
            <label className="text-xs text-text-secondary mb-1 block">LLM Provider</label>
            <select
              value={editProviderId}
              onChange={e => setEditProviderId(e.target.value)}
              className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50"
            >
              <option value="">自动选择</option>
              {providerConfigs.map(pc => (
                <option key={pc.id} value={pc.id}>{pc.name} ({pc.default_model})</option>
              ))}
            </select>
          </div>
        </div>
        <div className="flex justify-end gap-3">
          <button onClick={() => setEditingSession(null)} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">取消</button>
          <button onClick={handleEditSession} className="px-4 py-2 text-sm bg-accent/20 text-accent rounded-lg hover:bg-accent/30">保存</button>
        </div>
      </Modal>

      {/* Create Provider Modal */}
      <Modal open={showCreateProvider} onClose={() => setShowCreateProvider(false)}>
        <h3 className="text-lg font-medium mb-4">添加 Provider</h3>
        <div className="space-y-3 mb-4">
          {/* Template selector */}
          <div>
            <label className="text-xs text-text-secondary mb-1.5 block">快速填充模板</label>
            <div className="flex flex-wrap gap-1.5">
              {PROVIDER_TEMPLATES.map((tpl, i) => (
                <button
                  key={i}
                  onClick={() => {
                    setSelectedTemplate(i);
                    setProviderName(tpl.name);
                    setProviderBaseUrl(tpl.base_url);
                    setProviderModel(tpl.default_model);
                  }}
                  className={cn(
                    'px-2.5 py-1 rounded-lg text-xs border transition-all',
                    selectedTemplate === i
                      ? 'border-accent/50 bg-accent/10 text-accent'
                      : 'border-border-glow/30 bg-bg-tertiary text-text-secondary hover:border-accent/30 hover:text-text-primary'
                  )}
                >
                  {tpl.name}
                </button>
              ))}
            </div>
          </div>

          <input
            value={providerName}
            onChange={e => setProviderName(e.target.value)}
            placeholder="名称"
            className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50"
          />
          <input
            value={providerBaseUrl}
            onChange={e => setProviderBaseUrl(e.target.value)}
            placeholder="Base URL (如 https://api.openai.com/v1)"
            className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50"
          />
          <input
            value={providerApiKey}
            onChange={e => setProviderApiKey(e.target.value)}
            placeholder="API Key"
            type="password"
            className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50"
          />
          <input
            value={providerModel}
            onChange={e => setProviderModel(e.target.value)}
            placeholder="默认模型 (如 gpt-4o)"
            className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50"
          />
        </div>
        <div className="flex justify-end gap-3">
          <button onClick={() => setShowCreateProvider(false)} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">取消</button>
          <button onClick={handleCreateProvider} disabled={!providerName.trim() || !providerBaseUrl.trim() || !providerModel.trim()} className="px-4 py-2 text-sm bg-accent/20 text-accent rounded-lg hover:bg-accent/30 disabled:opacity-30">创建</button>
        </div>
      </Modal>
    </div>
  );
}
