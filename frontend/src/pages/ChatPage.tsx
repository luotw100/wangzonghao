import { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { cn, formatDate } from '../lib/utils';
import { LaborsterLogo, IconPlus, IconClose, IconArrowLeft } from '../components/Icons';
import { Modal } from '../components/Modal';
import * as api from '../lib/api';
import type { ChatUser, Conversation, Message } from '../lib/api';

export function ChatPage() {
  const [users, setUsers] = useState<ChatUser[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputText, setInputText] = useState('');
  const [activeSenderId, setActiveSenderId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarTab, setSidebarTab] = useState<'conversations' | 'users'>('conversations');
  // Modals
  const [showCreateUser, setShowCreateUser] = useState(false);
  const [showCreateConv, setShowCreateConv] = useState(false);
  const [newUserName, setNewUserName] = useState('');
  const [newConvTitle, setNewConvTitle] = useState('');
  const [newConvUserA, setNewConvUserA] = useState('');
  const [newConvUserB, setNewConvUserB] = useState('');

  const chatBoxRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const pollAbortRef = useRef<AbortController | null>(null);
  const lastMsgIdRef = useRef(0);
  const activeConvIdRef = useRef<string | null>(null);

  useEffect(() => { activeConvIdRef.current = activeConvId; }, [activeConvId]);

  const activeConv = conversations.find(c => c.id === activeConvId) || null;
  const activeUsers = users.filter(u => !u.is_deleted);

  // Get the two participants of the active conversation
  const userA = activeConv ? users.find(u => u.id === activeConv.user_a_id) : null;
  const userB = activeConv ? users.find(u => u.id === activeConv.user_b_id) : null;

  // Load data
  const loadUsers = useCallback(async () => {
    try { setUsers(await api.getUsers(true)); } catch (e) { setError(String(e)); }
  }, []);

  const loadConversations = useCallback(async () => {
    try { setConversations(await api.getConversations()); } catch (e) { setError(String(e)); }
  }, []);

  useEffect(() => { loadUsers(); loadConversations(); }, [loadUsers, loadConversations]);

  // Set default sender when conversation changes
  useEffect(() => {
    if (activeConv) {
      setActiveSenderId(activeConv.user_a_id);
    }
  }, [activeConv]);

  // Scroll to bottom
  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      if (chatBoxRef.current) chatBoxRef.current.scrollTop = chatBoxRef.current.scrollHeight;
    });
  }, []);
  useEffect(() => { scrollToBottom(); }, [messages.length, scrollToBottom]);

  // Polling
  const stopPolling = useCallback(() => {
    if (pollAbortRef.current) { pollAbortRef.current.abort(); pollAbortRef.current = null; }
  }, []);

  const startPolling = useCallback((convId: string) => {
    stopPolling();
    const controller = new AbortController();
    pollAbortRef.current = controller;
    const renderedIds = new Set(messages.map(m => m.id));

    const poll = async () => {
      let localLastId = lastMsgIdRef.current;
      while (!controller.signal.aborted && activeConvIdRef.current === convId) {
        try {
          const newMsgs = await api.getMessages(convId, localLastId, 30, controller.signal);
          if (controller.signal.aborted) return;
          const deduped = newMsgs.filter(m => !renderedIds.has(m.id));
          if (deduped.length > 0) {
            for (const m of deduped) renderedIds.add(m.id);
            localLastId = Math.max(localLastId, ...deduped.map(m => m.id));
            lastMsgIdRef.current = localLastId;
            setMessages(prev => [...prev, ...deduped]);
          }
        } catch {
          if (controller.signal.aborted) return;
          await new Promise(r => setTimeout(r, 2000));
        }
      }
    };
    poll();
  }, [stopPolling, messages]);

  // Select conversation
  const selectConversation = useCallback(async (convId: string) => {
    stopPolling();
    setActiveConvId(convId);
    setMessages([]);
    lastMsgIdRef.current = 0;
    setSidebarOpen(false);

    try {
      const msgs = await api.getMessages(convId, 0, 0);
      setMessages(msgs);
      if (msgs.length > 0) lastMsgIdRef.current = Math.max(...msgs.map(m => m.id));
      startPolling(convId);
    } catch (e) { setError(String(e)); }
  }, [stopPolling, startPolling]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  // Send message
  const handleSend = async () => {
    if (!inputText.trim() || !activeConvId || !activeSenderId) return;
    const text = inputText.trim();
    setInputText('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';

    try {
      await api.sendMessage(activeConvId, { sender_id: activeSenderId, msg_type: 'text', content: text });
    } catch (e) { setError(String(e)); }
  };

  // Create user
  const handleCreateUser = async () => {
    if (!newUserName.trim()) return;
    try {
      await api.createUser({ name: newUserName.trim() });
      setNewUserName('');
      setShowCreateUser(false);
      await loadUsers();
    } catch (e) { setError(String(e)); }
  };

  // Delete user
  const handleDeleteUser = async (userId: string) => {
    try {
      await api.deleteUser(userId);
      await loadUsers();
    } catch (e) { setError(String(e)); }
  };

  // Create conversation
  const handleCreateConv = async () => {
    if (!newConvUserA || !newConvUserB) return;
    try {
      const conv = await api.createConversation({
        title: newConvTitle.trim() || undefined,
        user_a_id: newConvUserA,
        user_b_id: newConvUserB,
      });
      setNewConvTitle('');
      setNewConvUserA('');
      setNewConvUserB('');
      setShowCreateConv(false);
      await loadConversations();
      selectConversation(conv.id);
    } catch (e) { setError(String(e)); }
  };

  // Delete conversation
  const handleDeleteConv = async (convId: string) => {
    try {
      await api.deleteConversation(convId);
      if (activeConvId === convId) { setActiveConvId(null); setMessages([]); stopPolling(); }
      await loadConversations();
    } catch (e) { setError(String(e)); }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  const autoResize = (e: React.FormEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, window.innerHeight * 0.3) + 'px';
  };

  useEffect(() => {
    if (!inputText && textareaRef.current) textareaRef.current.style.height = 'auto';
  }, [inputText]);

  return (
    <div className="w-full h-dvh overflow-hidden flex bg-bg-primary text-text-primary">
      {/* Sidebar */}
      {sidebarOpen && (
        <div onClick={() => setSidebarOpen(false)} className="fixed inset-0 bg-black/60 z-40 md:hidden backdrop-blur-md" />
      )}

      <aside className={cn(
        'w-80 bg-bg-secondary/90 backdrop-blur-xl flex flex-col fixed md:relative inset-y-0 left-0 z-50',
        'transform transition-transform duration-300 ease-out',
        'md:translate-x-0 md:bg-bg-secondary md:border-r md:border-border-glow/30',
        sidebarOpen ? 'translate-x-0' : '-translate-x-full'
      )}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 h-14 border-b border-border-glow/30">
          <div className="flex items-center gap-3">
            <Link to="/" className="flex items-center gap-1.5 text-text-secondary hover:text-accent transition-colors">
              <IconArrowLeft size={16} />
            </Link>
            <div className="w-px h-4 bg-border-glow/30" />
            <div className="flex items-center gap-2">
              <LaborsterLogo size={20} />
              <span className="font-brand font-medium tracking-wider text-sm text-accent">Chat</span>
            </div>
          </div>
          <button onClick={() => setSidebarOpen(false)} className="md:hidden w-10 h-10 flex items-center justify-center rounded-full hover:bg-bg-tertiary">
            <IconClose size={20} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-border-glow/20">
          <button
            onClick={() => setSidebarTab('conversations')}
            className={cn('flex-1 py-2.5 text-xs font-medium transition-colors', sidebarTab === 'conversations' ? 'text-accent border-b-2 border-accent' : 'text-text-secondary hover:text-text-primary')}
          >会话</button>
          <button
            onClick={() => setSidebarTab('users')}
            className={cn('flex-1 py-2.5 text-xs font-medium transition-colors', sidebarTab === 'users' ? 'text-accent border-b-2 border-accent' : 'text-text-secondary hover:text-text-primary')}
          >用户</button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto scrollbar-hide">
          {sidebarTab === 'conversations' ? (
            <div className="p-3 space-y-1">
              <button
                onClick={() => setShowCreateConv(true)}
                className="w-full px-4 py-2.5 flex items-center gap-3 rounded-xl border border-border-glow/30 hover:bg-accent/5 hover:border-accent/30 transition-all btn-neon mb-3"
              >
                <IconPlus /><span className="text-sm font-medium">新建会话</span>
              </button>
              {conversations.map(conv => {
                const uA = users.find(u => u.id === conv.user_a_id);
                const uB = users.find(u => u.id === conv.user_b_id);
                return (
                  <div
                    key={conv.id}
                    onClick={() => selectConversation(conv.id)}
                    className={cn(
                      'group flex items-center justify-between px-3 py-2.5 rounded-xl cursor-pointer transition-all',
                      activeConvId === conv.id ? 'bg-accent/10 session-active' : 'hover:bg-bg-tertiary/50'
                    )}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">{conv.title}</div>
                      <div className="text-xs text-text-secondary truncate">
                        {uA?.name || '?'} ↔ {uB?.name || '?'}
                      </div>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDeleteConv(conv.id); }}
                      className="opacity-0 group-hover:opacity-100 ml-2 text-text-tertiary hover:text-danger transition"
                      title="删除"
                    >
                      <IconClose size={14} />
                    </button>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="p-3 space-y-1">
              <button
                onClick={() => setShowCreateUser(true)}
                className="w-full px-4 py-2.5 flex items-center gap-3 rounded-xl border border-border-glow/30 hover:bg-accent/5 hover:border-accent/30 transition-all btn-neon mb-3"
              >
                <IconPlus /><span className="text-sm font-medium">新建用户</span>
              </button>
              {activeUsers.map(user => (
                <div
                  key={user.id}
                  className="group flex items-center justify-between px-3 py-2.5 rounded-xl hover:bg-bg-tertiary/50"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-accent/20 flex items-center justify-center text-xs font-medium text-accent">
                      {user.name[0]}
                    </div>
                    <div>
                      <div className="text-sm font-medium">{user.name}</div>
                      <div className="text-xs text-text-tertiary">{user.id}</div>
                    </div>
                  </div>
                  <button
                    onClick={() => handleDeleteUser(user.id)}
                    className="opacity-0 group-hover:opacity-100 text-text-tertiary hover:text-danger transition"
                    title="删除"
                  >
                    <IconClose size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </aside>

      {/* Main area */}
      <main className="flex-1 flex flex-col min-h-0 bg-bg-primary tech-grid">
        {/* Mobile hamburger */}
        <div className="md:hidden">
          <button
            onClick={() => setSidebarOpen(true)}
            className="fixed top-4 left-4 z-30 w-11 h-11 flex items-center justify-center rounded-full bg-bg-secondary/80 backdrop-blur-sm shadow-lg shadow-black/20 border border-border-glow/20"
          >
            <svg className="w-5 h-5 text-text-primary" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
            </svg>
          </button>
        </div>

        {/* Header */}
        <header className="h-14 flex items-center justify-between px-4 md:px-6 border-b border-border-glow/20 shrink-0 bg-bg-secondary/80 backdrop-blur-sm">
          <h2 className="font-medium text-text-primary">{activeConv ? activeConv.title : '选择或创建一个会话'}</h2>
          {activeConv && userA && userB && (
            <div className="text-xs text-text-secondary">
              {userA.name} ↔ {userB.name}
            </div>
          )}
        </header>

        {/* Error */}
        {error && (
          <div className="mx-4 mt-3 px-4 py-3 bg-danger-bg rounded-xl text-sm text-danger flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => setError('')} className="ml-2 text-danger hover:opacity-70">&times;</button>
          </div>
        )}

        {/* Messages */}
        <div ref={chatBoxRef} className="flex-1 overflow-y-auto overscroll-contain scrollbar-hide min-h-0">
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-4">
            {!activeConvId ? (
              <div className="flex flex-col items-center justify-center h-full min-h-[60vh] text-center">
                <div className="w-16 h-16 mb-6 rounded-full bg-bg-tertiary flex items-center justify-center laborster-empty-logo">
                  <LaborsterLogo size={32} id="chatEmptyGrad" />
                </div>
                <h3 className="text-xl font-medium mb-2">开始聊天</h3>
                <p className="text-text-secondary text-sm">先创建用户，再创建会话</p>
              </div>
            ) : (
              messages.map(msg => {
                const sender = users.find(u => u.id === msg.sender_id);
                const isLeft = msg.sender_id !== activeSenderId;
                return (
                  <div key={msg.id} className={cn('flex message-enter', isLeft ? 'justify-start' : 'justify-end')}>
                    {isLeft ? (
                      <div className="flex gap-3 max-w-[85%] md:max-w-[80%]">
                        <div className="w-8 h-8 rounded-full bg-accent/20 flex items-center justify-center text-xs font-bold text-accent shrink-0 mt-1">
                          {sender?.name?.[0] || '?'}
                        </div>
                        <div className="pt-1">
                          <div className="text-xs text-text-secondary mb-1">{sender?.name || msg.sender_id}</div>
                          <p className="whitespace-pre-wrap break-words leading-relaxed text-[15px]">{msg.content}</p>
                          <div className="text-[10px] text-text-tertiary mt-1">{formatDate(msg.created_at)}</div>
                        </div>
                      </div>
                    ) : (
                      <div className="max-w-[85%] md:max-w-[80%]">
                        <div className="text-xs text-text-secondary mb-1 text-right">{sender?.name || msg.sender_id}</div>
                        <div className="msg-user-bubble text-white rounded-2xl rounded-tr-md px-4 py-3">
                          <p className="whitespace-pre-wrap break-words leading-relaxed text-[15px]">{msg.content}</p>
                        </div>
                        <div className="text-[10px] text-text-tertiary mt-1 text-right">{formatDate(msg.created_at)}</div>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Input */}
        {activeConvId && activeConv && (
          <div className="border-t border-border-glow/20 bg-bg-secondary/80 backdrop-blur-sm px-4 py-3">
            <div className="max-w-3xl mx-auto">
              {/* Role switcher */}
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs text-text-secondary">以</span>
                {[activeConv.user_a_id, activeConv.user_b_id].map(uid => {
                  const u = users.find(x => x.id === uid);
                  return (
                    <button
                      key={uid}
                      onClick={() => setActiveSenderId(uid)}
                      className={cn(
                        'px-3 py-1 rounded-full text-xs font-medium transition-all',
                        activeSenderId === uid
                          ? 'bg-accent/20 text-accent border border-accent/40'
                          : 'bg-bg-tertiary text-text-secondary border border-transparent hover:border-border-glow/30'
                      )}
                    >
                      {u?.name || uid}
                    </button>
                  );
                })}
                <span className="text-xs text-text-secondary">的身份发送</span>
              </div>

              <div className="flex items-end gap-3">
                <div className="flex-1 bg-bg-tertiary/60 rounded-xl border border-border-glow/20 input-glow">
                  <textarea
                    ref={textareaRef}
                    value={inputText}
                    onChange={e => { setInputText(e.target.value); autoResize(e); }}
                    onKeyDown={handleKeyDown}
                    placeholder="输入消息..."
                    rows={1}
                    className="w-full bg-transparent px-4 py-3 text-[15px] resize-none outline-none placeholder:text-text-tertiary"
                  />
                </div>
                <button
                  onClick={handleSend}
                  disabled={!inputText.trim() || !activeSenderId}
                  className="w-11 h-11 flex items-center justify-center rounded-xl bg-accent/20 text-accent hover:bg-accent/30 disabled:opacity-30 disabled:cursor-not-allowed transition shrink-0"
                >
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
                  </svg>
                </button>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Create User Modal */}
      <Modal open={showCreateUser} onClose={() => setShowCreateUser(false)}>
        <h3 className="text-lg font-medium mb-4">新建用户</h3>
        <input
          value={newUserName}
          onChange={e => setNewUserName(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && handleCreateUser()}
          placeholder="用户名"
          autoFocus
          className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50 mb-4"
        />
        <div className="flex justify-end gap-3">
          <button onClick={() => setShowCreateUser(false)} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">取消</button>
          <button onClick={handleCreateUser} disabled={!newUserName.trim()} className="px-4 py-2 text-sm bg-accent/20 text-accent rounded-lg hover:bg-accent/30 disabled:opacity-30">创建</button>
        </div>
      </Modal>

      {/* Create Conversation Modal */}
      <Modal open={showCreateConv} onClose={() => setShowCreateConv(false)}>
        <h3 className="text-lg font-medium mb-4">新建会话</h3>
        <div className="space-y-3 mb-4">
          <input
            value={newConvTitle}
            onChange={e => setNewConvTitle(e.target.value)}
            placeholder="会话标题（可选）"
            className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50"
          />
          <select
            value={newConvUserA}
            onChange={e => setNewConvUserA(e.target.value)}
            className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50"
          >
            <option value="">选择用户 A</option>
            {activeUsers.filter(u => u.id !== newConvUserB).map(u => (
              <option key={u.id} value={u.id}>{u.name}</option>
            ))}
          </select>
          <select
            value={newConvUserB}
            onChange={e => setNewConvUserB(e.target.value)}
            className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50"
          >
            <option value="">选择用户 B</option>
            {activeUsers.filter(u => u.id !== newConvUserA).map(u => (
              <option key={u.id} value={u.id}>{u.name}</option>
            ))}
          </select>
        </div>
        <div className="flex justify-end gap-3">
          <button onClick={() => setShowCreateConv(false)} className="px-4 py-2 text-sm text-text-secondary hover:text-text-primary">取消</button>
          <button onClick={handleCreateConv} disabled={!newConvUserA || !newConvUserB} className="px-4 py-2 text-sm bg-accent/20 text-accent rounded-lg hover:bg-accent/30 disabled:opacity-30">创建</button>
        </div>
      </Modal>
    </div>
  );
}
