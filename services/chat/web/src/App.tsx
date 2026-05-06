import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import * as api from './api';
import type { Account, Contact, Conversation, Message } from './api';

type SenderType = 'self' | 'contact';

const sampleImport = JSON.stringify(
  [
    { sender_type: 'contact', msg_type: 'text', content: '你今天在忙吗？', created_at: '2026-05-06T12:00:00' },
    { sender_type: 'self', msg_type: 'text', content: '刚忙完，怎么啦', created_at: '2026-05-06T12:00:12' },
  ],
  null,
  2
);

function formatTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { hour12: false });
}

function initials(name: string): string {
  return name.slice(0, 2).toUpperCase();
}

export default function App() {
  const [account, setAccount] = useState<Account | null>(null);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [senderType, setSenderType] = useState<SenderType>('contact');
  const [input, setInput] = useState('');
  const [error, setError] = useState('');
  const [loginUsername, setLoginUsername] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [newContactName, setNewContactName] = useState('');
  const [newContactNote, setNewContactNote] = useState('');
  const [showImport, setShowImport] = useState(false);
  const [importText, setImportText] = useState(sampleImport);
  const [importFilename, setImportFilename] = useState('manual-import.json');
  const [loading, setLoading] = useState(false);

  const lastMessageIdRef = useRef(0);
  const activeConversationIdRef = useRef<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeConversationId) || null,
    [activeConversationId, conversations]
  );

  useEffect(() => {
    activeConversationIdRef.current = activeConversationId;
  }, [activeConversationId]);

  const loadWorkspace = useCallback(async () => {
    const [nextContacts, nextConversations] = await Promise.all([api.listContacts(), api.listConversations()]);
    setContacts(nextContacts);
    setConversations(nextConversations);
    if (!activeConversationIdRef.current && nextConversations.length > 0) {
      setActiveConversationId(nextConversations[0].id);
    }
  }, []);

  useEffect(() => {
    if (!api.getToken()) return;
    api.me()
      .then((me) => {
        setAccount(me);
        return loadWorkspace();
      })
      .catch((err) => setError(String(err instanceof Error ? err.message : err)));
  }, [loadWorkspace]);

  useEffect(() => {
    if (!activeConversationId || !account) return;
    let cancelled = false;
    const conversationId = activeConversationId;
    lastMessageIdRef.current = 0;
    setMessages([]);

    async function initialLoad() {
      const initialMessages = await api.getMessages(conversationId, 0, 0);
      if (cancelled) return;
      setMessages(initialMessages);
      lastMessageIdRef.current = initialMessages.reduce((max, message) => Math.max(max, message.id), 0);
    }

    initialLoad().catch((err) => setError(String(err instanceof Error ? err.message : err)));
    return () => {
      cancelled = true;
    };
  }, [activeConversationId, account]);

  useEffect(() => {
    if (!activeConversationId || !account) return;
    let cancelled = false;
    const conversationId = activeConversationId;

    async function poll() {
      while (!cancelled && activeConversationIdRef.current === conversationId) {
        try {
          const incoming = await api.getMessages(conversationId, lastMessageIdRef.current, 30);
          if (cancelled) return;
          if (incoming.length > 0) {
            lastMessageIdRef.current = Math.max(lastMessageIdRef.current, ...incoming.map((message) => message.id));
            setMessages((previous) => {
              const seen = new Set(previous.map((message) => message.id));
              return [...previous, ...incoming.filter((message) => !seen.has(message.id))];
            });
          }
        } catch (err) {
          if (!cancelled) setError(String(err instanceof Error ? err.message : err));
          await new Promise((resolve) => setTimeout(resolve, 1200));
        }
      }
    }

    poll();
    return () => {
      cancelled = true;
    };
  }, [activeConversationId, account]);

  useEffect(() => {
    requestAnimationFrame(() => {
      if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
    });
  }, [messages.length]);

  async function handleLogin(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError('');
    try {
      const result = await api.login(loginUsername.trim(), loginPassword);
      api.setToken(result.token);
      setAccount(result.account);
      await loadWorkspace();
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    } finally {
      setLoading(false);
    }
  }

  async function handleLogout() {
    try {
      await api.logout();
    } catch {
      // ignore
    }
    api.setToken(null);
    setAccount(null);
    setContacts([]);
    setConversations([]);
    setMessages([]);
    setActiveConversationId(null);
  }

  async function handleCreateContact(event: FormEvent) {
    event.preventDefault();
    if (!newContactName.trim()) return;
    setError('');
    try {
      await api.createContact({ display_name: newContactName.trim(), note: newContactNote.trim() || undefined });
      setNewContactName('');
      setNewContactNote('');
      await loadWorkspace();
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    }
  }

  async function handleSend() {
    if (!activeConversationId || !input.trim()) return;
    const content = input.trim();
    setInput('');
    setError('');
    try {
      await api.sendMessage(activeConversationId, { sender_type: senderType, msg_type: 'text', content });
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    }
  }

  async function handleImport(event: FormEvent) {
    event.preventDefault();
    if (!activeConversationId) return;
    setError('');
    try {
      const parsed = JSON.parse(importText) as Array<{
        sender_type: SenderType;
        msg_type?: string;
        content: string;
        created_at: string;
      }>;
      const messagesToImport = parsed.map((item) => ({
        sender_type: item.sender_type,
        msg_type: item.msg_type || 'text',
        content: item.content,
        created_at: item.created_at,
      }));
      await api.bulkImportMessages(activeConversationId, { filename: importFilename.trim() || undefined, messages: messagesToImport });
      setShowImport(false);
      const nextMessages = await api.getMessages(activeConversationId, 0, 0);
      setMessages(nextMessages);
      lastMessageIdRef.current = nextMessages.reduce((max, message) => Math.max(max, message.id), 0);
      await loadWorkspace();
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    }
  }

  if (!account) {
    return (
      <main className="login-shell">
        <section className="login-card">
          <div className="brand-mark">Chat</div>
          <p className="eyebrow">LOCAL DEBUG PLATFORM</p>
          <h1>登录一个服务器上生成的 Chat 账号</h1>
          <p className="muted">每个账号都是一个独立的微信式沙盒。联系人只属于当前账号。</p>
          <form onSubmit={handleLogin} className="stack">
            <label>
              用户名
              <input value={loginUsername} onChange={(event) => setLoginUsername(event.target.value)} autoFocus />
            </label>
            <label>
              密码
              <input type="password" value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} />
            </label>
            <button className="primary" disabled={loading || !loginUsername.trim() || !loginPassword}>
              {loading ? '登录中…' : '进入 Chat'}
            </button>
          </form>
          {error && <div className="error">{error}</div>}
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <header className="sidebar-header">
          <div>
            <p className="eyebrow">CHAT ACCOUNT</p>
            <h2>{account.display_name}</h2>
            <span>@{account.username}</span>
          </div>
          <button className="ghost" onClick={handleLogout}>退出</button>
        </header>

        <form className="new-contact" onSubmit={handleCreateContact}>
          <input placeholder="新建联系人，例如 小明" value={newContactName} onChange={(event) => setNewContactName(event.target.value)} />
          <input placeholder="备注，可选" value={newContactNote} onChange={(event) => setNewContactNote(event.target.value)} />
          <button className="primary" disabled={!newContactName.trim()}>添加联系人</button>
        </form>

        <div className="conversation-list">
          {conversations.map((conversation) => (
            <button
              key={conversation.id}
              className={conversation.id === activeConversationId ? 'conversation active' : 'conversation'}
              onClick={() => setActiveConversationId(conversation.id)}
            >
              <span className="avatar">{initials(conversation.contact.display_name)}</span>
              <span>
                <strong>{conversation.title}</strong>
                <small>{conversation.contact.platform_contact_id}</small>
              </span>
            </button>
          ))}
        </div>
        <div className="sidebar-footer">{contacts.length} contacts · {conversations.length} threads</div>
      </aside>

      <section className="chat-panel">
        {activeConversation ? (
          <>
            <header className="chat-header">
              <div>
                <p className="eyebrow">DIRECT THREAD</p>
                <h1>{activeConversation.contact.display_name}</h1>
              </div>
              <button className="secondary" onClick={() => setShowImport(true)}>导入聊天记录</button>
            </header>

            <div className="messages" ref={listRef}>
              {messages.map((message) => (
                <article key={message.id} className={message.sender_type === 'self' ? 'bubble-row self' : 'bubble-row contact'}>
                  <div className="bubble-meta">
                    {message.sender_type === 'self' ? account.display_name : activeConversation.contact.display_name}
                    <span>{formatTime(message.created_at)}</span>
                    {message.source === 'import' && <em>import</em>}
                  </div>
                  <div className="bubble">{message.content}</div>
                </article>
              ))}
              {messages.length === 0 && <div className="empty-state">还没有消息。可以选择任意身份发送，或导入历史记录。</div>}
            </div>

            <footer className="composer">
              <div className="sender-toggle" aria-label="选择发送身份">
                <button className={senderType === 'contact' ? 'selected' : ''} onClick={() => setSenderType('contact')}>作为 {activeConversation.contact.display_name}</button>
                <button className={senderType === 'self' ? 'selected' : ''} onClick={() => setSenderType('self')}>作为 {account.display_name}</button>
              </div>
              <div className="input-row">
                <textarea
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault();
                      handleSend();
                    }
                  }}
                  placeholder="输入消息，Enter 发送，Shift+Enter 换行"
                />
                <button className="primary send" onClick={handleSend} disabled={!input.trim()}>发送</button>
              </div>
              {error && <div className="error compact">{error}</div>}
            </footer>
          </>
        ) : (
          <div className="empty-page">
            <h1>先创建一个联系人</h1>
            <p>联系人是当前 Chat 账号下的本地身份，不会和其它账号共享。</p>
          </div>
        )}
      </section>

      {showImport && activeConversation && (
        <div className="modal-backdrop" onClick={() => setShowImport(false)}>
          <form className="import-modal" onSubmit={handleImport} onClick={(event) => event.stopPropagation()}>
            <p className="eyebrow">BULK IMPORT</p>
            <h2>导入到 {activeConversation.contact.display_name}</h2>
            <input value={importFilename} onChange={(event) => setImportFilename(event.target.value)} />
            <textarea value={importText} onChange={(event) => setImportText(event.target.value)} />
            <div className="modal-actions">
              <button type="button" className="ghost" onClick={() => setShowImport(false)}>取消</button>
              <button className="primary">导入</button>
            </div>
            {error && <div className="error compact">{error}</div>}
          </form>
        </div>
      )}
    </main>
  );
}
