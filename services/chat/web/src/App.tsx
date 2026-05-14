import { useEffect, useMemo, useState } from 'react';
import * as api from './api';
import Login from './components/Login';
import Sidebar from './components/Sidebar';
import ChatPanel from './components/ChatPanel';
import { useAuth } from './hooks/useAuth';
import { useWorkspace } from './hooks/useWorkspace';
import { useMessages } from './hooks/useMessages';

export default function App() {
  const auth = useAuth();
  const workspace = useWorkspace(!!auth.account);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [globalError, setGlobalError] = useState('');
  const [mobileView, setMobileView] = useState<'list' | 'chat'>('list');

  // Auto-pick the first conversation once we have data and nothing is selected.
  useEffect(() => {
    if (!workspace.loaded) return;
    if (activeConversationId) return;
    if (workspace.conversations.length === 0) return;
    // On wide screens, auto-select the first conversation. On narrow screens,
    // keep the user on the list view until they tap one.
    if (window.matchMedia('(min-width: 860px)').matches) {
      setActiveConversationId(workspace.conversations[0].id);
    }
  }, [workspace.loaded, workspace.conversations, activeConversationId]);

  // If the active conversation disappears (e.g. contact deleted), clear it.
  useEffect(() => {
    if (!activeConversationId) return;
    if (!workspace.loaded) return;
    const stillExists = workspace.conversations.some((c) => c.id === activeConversationId);
    if (!stillExists) {
      setActiveConversationId(null);
      setMobileView('list');
    }
  }, [workspace.conversations, workspace.loaded, activeConversationId]);

  const activeConversation = useMemo(
    () => workspace.conversations.find((c) => c.id === activeConversationId) || null,
    [workspace.conversations, activeConversationId]
  );

  const messagesState = useMessages(activeConversationId, !!auth.account);

  // Build a map: conversationId → most recent message (for sidebar previews).
  // We only have full messages for the *active* conversation; for the others
  // we fall back to undefined and the sidebar shows the contact note instead.
  const lastMessages = useMemo(() => {
    const out: Record<string, typeof messagesState.messages[number] | undefined> = {};
    if (activeConversation && messagesState.messages.length > 0) {
      out[activeConversation.id] = messagesState.messages[messagesState.messages.length - 1];
    }
    return out;
  }, [activeConversation, messagesState.messages]);

  if (!auth.account) {
    return <Login loading={auth.loading} error={auth.error} onLogin={auth.login} />;
  }

  function handleSelectConversation(id: string) {
    setActiveConversationId(id);
    setMobileView('chat');
  }

  async function handleCreateContact(nickname: string, remarkName: string) {
    setGlobalError('');
    try {
      await api.createContact({ nickname, remark_name: remarkName || undefined });
      await workspace.reload();
    } catch (err) {
      setGlobalError(err instanceof Error ? err.message : String(err));
      throw err;
    }
  }

  async function handleDeleteContact(contactId: string) {
    setGlobalError('');
    try {
      await api.deleteContact(contactId);
      await workspace.reload();
    } catch (err) {
      setGlobalError(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleUpdateContactRemark(contactId: string, remarkName: string) {
    setGlobalError('');
    try {
      await api.updateContact(contactId, { remark_name: remarkName || undefined });
      await workspace.reload();
    } catch (err) {
      setGlobalError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <main className={mobileView === 'chat' ? 'app-shell view-chat' : 'app-shell view-list'}>
      <Sidebar
        account={auth.account}
        conversations={workspace.conversations}
        activeConversationId={activeConversationId}
        onSelectConversation={handleSelectConversation}
        onCreateContact={handleCreateContact}
        onUpdateContactRemark={handleUpdateContactRemark}
        onDeleteContact={handleDeleteContact}
        onLogout={auth.logout}
        onUpdateNickname={auth.updateNickname}
        lastMessages={lastMessages}
      />

      {activeConversation ? (
        <ChatPanel
          account={auth.account}
          conversation={activeConversation}
          messages={messagesState.messages}
          onMessagesReload={messagesState.reload}
          onWorkspaceReload={workspace.reload}
          onBack={() => setMobileView('list')}
        />
      ) : (
        <section className="empty-page">
          <div>
            <EmptyArt />
            <h1>选择一个联系人</h1>
            <p>左侧选择联系人开始对话，或新建一个联系人。</p>
          </div>
        </section>
      )}

      {globalError && (
        <div className="toast" role="alert" onClick={() => setGlobalError('')}>
          {globalError}
        </div>
      )}
    </main>
  );
}

function EmptyArt() {
  return (
    <svg viewBox="0 0 200 160" width="180" height="144" aria-hidden="true">
      <rect x="20" y="36" width="120" height="80" rx="20" fill="#e7f5ea" />
      <rect x="60" y="62" width="120" height="60" rx="20" fill="#cfe9d6" />
      <circle cx="50" cy="68" r="4" fill="#7eb289" />
      <circle cx="70" cy="68" r="4" fill="#7eb289" />
      <circle cx="90" cy="68" r="4" fill="#7eb289" />
    </svg>
  );
}
