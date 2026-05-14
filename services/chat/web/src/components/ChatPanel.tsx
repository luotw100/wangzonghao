import { useState } from 'react';
import type { Account, Conversation, Message } from '../api';
import * as api from '../api';
import { contactDisplayName } from '../api';
import MessageList from './MessageList';
import Composer from './Composer';
import Avatar from './Avatar';

interface ChatPanelProps {
  account: Account;
  conversation: Conversation;
  messages: Message[];
  hasMore: boolean;
  onLoadOlder: () => Promise<void>;
  onMessagesReload: () => Promise<void>;
  onWorkspaceReload: () => Promise<void>;
  onBack?: () => void;
}

export default function ChatPanel({
  account,
  conversation,
  messages,
  hasMore,
  onLoadOlder,
  onMessagesReload,
  onWorkspaceReload,
  onBack,
}: ChatPanelProps) {
  const [perspective, setPerspective] = useState<'self' | 'contact'>(() => {
    const saved = localStorage.getItem('laborster-chat-perspective');
    return saved === 'contact' ? 'contact' : 'self';
  });

  function changePerspective(next: 'self' | 'contact') {
    setPerspective(next);
    localStorage.setItem('laborster-chat-perspective', next);
  }

  async function handleSend(content: string, sender: 'self' | 'contact') {
    await api.sendMessage(conversation.id, { sender_type: sender, msg_type: 'text', content });
    // The long-poll will pick up the new message; no need to manually reload.
  }

  return (
    <section className="chat-panel">
      <header className="chat-header">
        {onBack && (
          <button type="button" className="back-btn" onClick={onBack} aria-label="返回联系人列表">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
              <path d="m15 6-6 6 6 6" />
            </svg>
          </button>
        )}
        <Avatar name={contactDisplayName(conversation.contact)} seed={conversation.contact.id} size={38} />
        <div className="chat-title">
          <h1>{contactDisplayName(conversation.contact)}</h1>
          {conversation.contact.remark_name && <p>{conversation.contact.nickname}</p>}
        </div>
      </header>

      <MessageList
        account={account}
        conversation={conversation}
        messages={messages}
        perspective={perspective}
        hasMore={hasMore}
        loadOlder={onLoadOlder}
      />

      <Composer
        account={account}
        conversation={conversation}
        perspective={perspective}
        onChangePerspective={changePerspective}
        onSend={handleSend}
      />

      </section>
  );
}
