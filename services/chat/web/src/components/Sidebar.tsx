import { useState, useRef, FormEvent, MouseEvent, KeyboardEvent } from 'react';
import type { Account, Conversation, Message } from '../api';
import { contactDisplayName } from '../api';
import Avatar from './Avatar';
import ContextMenu from './ContextMenu';
import { formatListPreview } from '../utils/time';

interface SidebarProps {
  account: Account;
  conversations: Conversation[];
  activeConversationId: string | null;
  onSelectConversation: (id: string) => void;
  onCreateContact: (nickname: string, remarkName: string) => Promise<void>;
  onUpdateContactRemark: (contactId: string, remarkName: string) => Promise<void>;
  onLogout: () => void;
  onUpdateNickname: (nickname: string) => Promise<void>;
  onOpenImport: () => void;
  lastMessages: Record<string, Message | undefined>;
}

export default function Sidebar({
  account,
  conversations,
  activeConversationId,
  onSelectConversation,
  onCreateContact,
  onUpdateContactRemark,
  onLogout,
  onUpdateNickname,
  onOpenImport,
  lastMessages,
}: SidebarProps) {
  const [query, setQuery] = useState('');
  const [showAdd, setShowAdd] = useState(false);
  const [nickname, setNickname] = useState('');
  const [remarkName, setRemarkName] = useState('');
  const [busy, setBusy] = useState(false);
  const [menu, setMenu] = useState<{ x: number; y: number; conversation: Conversation } | null>(null);
  const [editingNickname, setEditingNickname] = useState(false);
  const [nicknameInput, setNicknameInput] = useState('');
  const longPressTimer = useRef<number | null>(null);

  function startEditNickname() {
    setNicknameInput(account.nickname);
    setEditingNickname(true);
  }

  async function commitNickname() {
    const trimmed = nicknameInput.trim();
    setEditingNickname(false);
    if (!trimmed || trimmed === account.nickname) return;
    await onUpdateNickname(trimmed);
  }

  function handleNicknameKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') e.currentTarget.blur();
    if (e.key === 'Escape') setEditingNickname(false);
  }

  const q = query.trim().toLowerCase();
  const filtered = q
    ? conversations.filter((c) => {
        const name = contactDisplayName(c.contact).toLowerCase();
        const remark = (c.contact.remark_name || '').toLowerCase();
        const nick = c.contact.nickname.toLowerCase();
        const last = lastMessages[c.id]?.content.toLowerCase() || '';
        return name.includes(q) || remark.includes(q) || nick.includes(q) || last.includes(q);
      })
    : conversations;

  async function handleAdd(event: FormEvent) {
    event.preventDefault();
    if (!nickname.trim() || busy) return;
    setBusy(true);
    try {
      await onCreateContact(nickname.trim(), remarkName.trim());
      setNickname('');
      setRemarkName('');
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
        <div className="me">
          <Avatar name={account.nickname} seed={account.id} size={36} />
          <span className="me-text">
            {editingNickname ? (
              <input
                className="nickname-edit"
                value={nicknameInput}
                onChange={(e) => setNicknameInput(e.target.value)}
                onBlur={commitNickname}
                onKeyDown={handleNicknameKeyDown}
                autoFocus
              />
            ) : (
              <strong onClick={startEditNickname} title="点击修改昵称">{account.nickname}</strong>
            )}
            <small>@{account.username}</small>
          </span>
        </div>
        <button
          type="button"
          className="import-btn"
          aria-label="导入聊天记录"
          title="导入聊天记录"
          onClick={onOpenImport}
        >
          <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
            <polyline points="8 12 12 16 16 12" />
            <line x1="12" y1="3" x2="12" y2="16" />
          </svg>
          <span>导入</span>
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
        <button
          type="button"
          className="icon-btn"
          aria-label="退出登录"
          onClick={onLogout}
          title="退出登录"
        >
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
            <polyline points="16 17 21 12 16 7" />
            <line x1="21" y1="12" x2="9" y2="12" />
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
            placeholder="对方昵称"
            value={nickname}
            onChange={(e) => setNickname(e.target.value)}
            autoFocus
          />
          <input
            placeholder="备注名（可选）"
            value={remarkName}
            onChange={(e) => setRemarkName(e.target.value)}
          />
          <div className="new-contact-actions">
            <button type="button" className="ghost" onClick={() => setShowAdd(false)}>
              取消
            </button>
            <button className="primary" disabled={!nickname.trim() || busy}>
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
          const displayName = contactDisplayName(conversation.contact);
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
              <Avatar name={displayName} seed={conversation.contact.id} size={44} />
              <span className="conversation-body">
                <span className="conversation-top">
                  <strong>{displayName}</strong>
                  {last && <small>{formatListPreview(last.created_at)}</small>}
                </span>
                <span className="conversation-bottom">
                  <small>{last ? last.content : '暂无消息'}</small>
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
              label: '编辑备注名',
              onClick: async () => {
                const target = menu.conversation;
                setMenu(null);
                const current = target.contact.remark_name || '';
                const remark = window.prompt('修改备注名', current);
                if (remark === null) return;
                await onUpdateContactRemark(target.contact.id, remark.trim());
              },
            },
          ]}
        />
      )}
    </aside>
  );
}
