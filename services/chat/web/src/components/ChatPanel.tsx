import { useState } from 'react';
import type { Account, Conversation, Message } from '../api';
import * as api from '../api';
import MessageList from './MessageList';
import Composer from './Composer';
import ImportModal, { ParsedMessage } from './ImportModal';
import Avatar from './Avatar';

interface ChatPanelProps {
  account: Account;
  conversation: Conversation;
  messages: Message[];
  onMessagesReload: () => Promise<void>;
  onWorkspaceReload: () => Promise<void>;
  onBack?: () => void;
}

export default function ChatPanel({
  account,
  conversation,
  messages,
  onMessagesReload,
  onWorkspaceReload,
  onBack,
}: ChatPanelProps) {
  const [perspective, setPerspective] = useState<'self' | 'contact'>(() => {
    const saved = localStorage.getItem('laborster-chat-perspective');
    return saved === 'contact' ? 'contact' : 'self';
  });
  const [showImport, setShowImport] = useState(false);

  function changePerspective(next: 'self' | 'contact') {
    setPerspective(next);
    localStorage.setItem('laborster-chat-perspective', next);
  }

  async function handleSend(content: string, sender: 'self' | 'contact') {
    await api.sendMessage(conversation.id, { sender_type: sender, msg_type: 'text', content });
    // The long-poll will pick up the new message; no need to manually reload.
  }

  async function handleImport(filename: string, parsed: ParsedMessage[]) {
    await api.bulkImportMessages(conversation.id, { filename, messages: parsed });
    setShowImport(false);
    await onMessagesReload();
    await onWorkspaceReload();
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
        <Avatar name={conversation.contact.display_name} seed={conversation.contact.id} size={38} />
        <div className="chat-title">
          <h1>{conversation.contact.display_name}</h1>
          {conversation.contact.note && <p>{conversation.contact.note}</p>}
        </div>
        <button type="button" className="secondary import-btn" onClick={() => setShowImport(true)}>
          <span className="label-long">导入聊天记录</span>
          <span className="label-short">导入</span>
        </button>
      </header>

      <MessageList
        account={account}
        conversation={conversation}
        messages={messages}
        perspective={perspective}
      />

      <Composer
        account={account}
        conversation={conversation}
        perspective={perspective}
        onChangePerspective={changePerspective}
        onSend={handleSend}
      />

      {showImport && (
        <ImportModal
          conversation={conversation}
          onClose={() => setShowImport(false)}
          onSubmit={handleImport}
        />
      )}
    </section>
  );
}
