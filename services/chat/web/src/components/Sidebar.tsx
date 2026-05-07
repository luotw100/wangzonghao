import { useState, useRef, FormEvent, MouseEvent } from 'react';
import type { Account, Conversation, Message } from '../api';
import Avatar from './Avatar';
import ContextMenu from './ContextMenu';
import { formatListPreview } from '../utils/time';

interface SidebarProps {
  account: Account;
  conversations: Conversation[];
  activeConversationId: string | null;
  onSelectConversation: (id: string) => void;
  onCreateContact: (name: string, note: string) => Promise<void>;
  onDeleteContact: (contactId: string) => Promise<void>;
  onLogout: () => void;
  /** map of conversationId → last message (for sidebar preview) */
  lastMessages: Record<string, Message | undefined>;
}

export default function Sidebar({
  account,
  conversations,
  activeConversationId,
  onSelectConversation,
  onCreateContact,
  onDeleteContact,
  onLogout,
  lastMessages,
}: SidebarProps) {
  const [query, setQuery] = useState('');
  const [showAdd, setShowAdd] = useState(false);
  const [name, setName] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [menu, setMenu] = useState<{ x: number; y: number; conversation: Conversation } | null>(null);
  const longPressTimer = useRef<number | null>(null);

  const q = query.trim().toLowerCase();
  const filtered = q
    ? conversations.filter((c) => {
        const name = c.contact.display_name.toLowerCase();
        const note = (c.contact.note || '').toLowerCase();
        const last = lastMessages[c.id]?.content.toLowerCase() || '';
        return name.includes(q) || note.includes(q) || last.includes(q);
      })
    : conversations;

  async function handleAdd(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    try {
      await onCreateContact(name.trim(), note.trim());
      setName('');
      setNote('');
      setShowAdd(false);
    } finally {
      setBusy(false);
    }
  }

  function openMenu(event: MouseEvent<HTMLElement>, conversation: Conversation) {
    event.preventDefault();
    setMenu({ x: event.clientX, y: event.clientY, conversation });
  }

  function startLongPress(conversation: Conversation, event: React.TouchEvent) {
    if (longPressTimer.current) window.clearTimeout(longPressTimer.current);
    const touch = event.touches[0];
    longPressTimer.current = window.setTimeout(() => {
      setMenu({ x: touch.clientX, y: touch.clientY, conversation });
    }, 500);
  }

  function cancelLongPress() {
    if (longPressTimer.current) {
      window.clearTimeout(longPressTimer.current);
      longPressTimer.current = null;
    }
  }

  return (
    <aside className="sidebar">
      <header className="sidebar-header">
        <button
          type="button"
          className="me"
          onClick={onLogout}
          title={`点击退出 @${account.username}`}
        >
          <Avatar name={account.display_name} seed={account.id} size={36} />
          <span className="me-text">
            <strong>{account.display_name}</strong>
            <small>@{account.username}</small>
          </span>
        </button>
        <button
          type="button"
          className="icon-btn"
          aria-label="添加联系人"
          onClick={() => setShowAdd((s) => !s)}
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>
      </header>

      <div className="search-row">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" />
        </svg>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索"
          aria-label="搜索联系人"
        />
        {query && (
          <button type="button" className="search-clear" onClick={() => setQuery('')} aria-label="清除">
            ×
          </button>
        )}
      </div>

      {showAdd && (
        <form className="new-contact" onSubmit={handleAdd}>
          <input
            placeholder="联系人昵称"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
          <input
            placeholder="备注（可选）"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <div className="new-contact-actions">
            <button type="button" className="ghost" onClick={() => setShowAdd(false)}>
              取消
            </button>
            <button className="primary" disabled={!name.trim() || busy}>
              {busy ? '添加中…' : '添加'}
            </button>
          </div>
        </form>
      )}

      <div className="conversation-list">
        {filtered.length === 0 && (
          <div className="empty-list">
            {conversations.length === 0 ? (
              <>
                <p>还没有联系人</p>
                <button type="button" className="link" onClick={() => setShowAdd(true)}>
                  添加第一个联系人
                </button>
              </>
            ) : (
              <p>没有匹配「{query}」的联系人</p>
            )}
          </div>
        )}
        {filtered.map((conversation) => {
          const last = lastMessages[conversation.id];
          const active = conversation.id === activeConversationId;
          return (
            <button
              key={conversation.id}
              type="button"
              className={active ? 'conversation active' : 'conversation'}
              onClick={() => onSelectConversation(conversation.id)}
              onContextMenu={(e) => openMenu(e, conversation)}
              onTouchStart={(e) => startLongPress(conversation, e)}
              onTouchEnd={cancelLongPress}
              onTouchMove={cancelLongPress}
              onTouchCancel={cancelLongPress}
            >
              <Avatar name={conversation.contact.display_name} seed={conversation.contact.id} size={44} />
              <span className="conversation-body">
                <span className="conversation-top">
                  <strong>{conversation.title || conversation.contact.display_name}</strong>
                  {last && <small>{formatListPreview(last.created_at)}</small>}
                </span>
                <span className="conversation-bottom">
                  <small>{last ? last.content : conversation.contact.note || '暂无消息'}</small>
                </span>
              </span>
            </button>
          );
        })}
      </div>

      {menu && (
        <ContextMenu
          x={menu.x}
          y={menu.y}
          onClose={() => setMenu(null)}
          items={[
            {
              label: '删除联系人',
              danger: true,
              onClick: async () => {
                const target = menu.conversation;
                setMenu(null);
                const ok = window.confirm(
                  `删除联系人「${target.contact.display_name}」？该联系人下的会话也会被一起标记为删除。`
                );
                if (!ok) return;
                await onDeleteContact(target.contact.id);
              },
            },
          ]}
        />
      )}
    </aside>
  );
}
