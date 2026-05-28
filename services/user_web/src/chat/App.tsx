import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '../lib/auth-context';
import * as api from './api';
import type { Account, Message } from './api';
import Sidebar from './components/Sidebar';
import ChatPanel from './components/ChatPanel';
import ImportDialog from './components/ImportDialog';
import { useWorkspace } from './hooks/useWorkspace';
import { useMessages } from './hooks/useMessages';

export default function ChatApp() {
  const navigate = useNavigate();
  const { account: studioAccount } = useAuth();

  // Adapter: chat components want { id, username, nickname }. Studio's
  // session account has display_name — we shadow it as nickname so the
  // rest of the chat UI doesn't have to know the difference.
  const account = useMemo<Account | null>(() => {
    if (!studioAccount) return null;
    return {
      id: studioAccount.id,
      username: studioAccount.username,
      nickname: studioAccount.display_name || studioAccount.username,
    };
  }, [studioAccount]);

  const workspace = useWorkspace(!!account);
  const { conversationId: routeConvId } = useParams<{ conversationId: string }>();
  const activeConversationId = routeConvId ?? null;
  const setActiveConversationId = useCallback((id: string | null, replace = false) => {
    navigate(id ? `/chat/c/${id}` : '/chat', { replace });
  }, [navigate]);
  const [globalError, setGlobalError] = useState('');
  const [mobileView, setMobileView] = useState<'list' | 'chat'>('list');
  const [showImport, setShowImport] = useState(false);

  // Per-conversation message cache: seeds useMessages on switch (instant display)
  // and provides lastMessages to the sidebar for all conversations.
  const msgCacheRef = useRef<Map<string, Message[]>>(new Map());
  const [lastMsgCache, setLastMsgCache] = useState<Record<string, Message | undefined>>({});

  useEffect(() => {
    if (!workspace.loaded) return;
    if (activeConversationId) return;
    if (workspace.conversations.length === 0) return;
    if (window.matchMedia('(min-width: 860px)').matches) {
      setActiveConversationId(workspace.conversations[0].id, true);
    }
  }, [workspace.loaded, workspace.conversations, activeConversationId, setActiveConversationId]);

  useEffect(() => {
    if (!activeConversationId) return;
    if (!workspace.loaded) return;
    const stillExists = workspace.conversations.some(c => c.id === activeConversationId);
    if (!stillExists) {
      // The selected conversation was deleted/filtered out after a workspace
      // reload — drop the selection and fall back to the list view.
      setActiveConversationId(null, true);
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMobileView('list');
    }
  }, [workspace.conversations, workspace.loaded, activeConversationId, setActiveConversationId]);

  const activeConversation = useMemo(
    () => workspace.conversations.find(c => c.id === activeConversationId) || null,
    [workspace.conversations, activeConversationId],
  );

  // Seed useMessages from the per-conversation cache for instant display on
  // switch; this is initial data only — useMessages refetches the live list.
  // eslint-disable-next-line react-hooks/refs
  const conversationSeed = activeConversationId ? msgCacheRef.current.get(activeConversationId) : undefined;

  const messagesState = useMessages(activeConversationId, !!account, conversationSeed);

  // Keep cache and sidebar previews in sync with live messages.
  // Guard: only write when messages actually belong to the active conversation.
  // Without this, switching conversations causes the old messages (still in state)
  // to be cached under the new conversation ID on the first render after switch.
  useEffect(() => {
    if (!activeConversationId || messagesState.messages.length === 0) return;
    if (messagesState.messages[0].conversation_id !== activeConversationId) return;
    msgCacheRef.current.set(activeConversationId, [...messagesState.messages]);
    const last = messagesState.messages[messagesState.messages.length - 1];
    // Accumulate the latest message per conversation so sidebar previews stay
    // populated across all visited conversations, driven by fetched messages.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLastMsgCache((prev) => ({ ...prev, [activeConversationId]: last }));
  }, [activeConversationId, messagesState.messages]);

  // lastMessages is now derived from the accumulated cache across all visited
  // conversations, so every sidebar row shows a preview regardless of which
  // conversation is currently active.
  const lastMessages = useMemo(() => lastMsgCache, [lastMsgCache]);

  if (!account) return null; // RequireAuth should prevent this state

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

  async function handleImportDone(conversationId: string) {
    setShowImport(false);
    await workspace.reload();
    setActiveConversationId(conversationId);
    setMobileView('chat');
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

  // Nickname is the studio account's display_name; editing happens in
  // studio settings. Chat just renders read-only here.
  async function handleUpdateNickname() {
    setGlobalError('账号昵称请到 Studio 设置中修改');
  }

  return (
    <main className={mobileView === 'chat' ? 'app-shell view-chat' : 'app-shell view-list'}>
      <Sidebar
        account={account}
        conversations={workspace.conversations}
        activeConversationId={activeConversationId}
        onSelectConversation={handleSelectConversation}
        onCreateContact={handleCreateContact}
        onUpdateContactRemark={handleUpdateContactRemark}
        onUpdateNickname={handleUpdateNickname}
        onOpenImport={() => setShowImport(true)}
        onExit={() => navigate('/studio')}
        lastMessages={lastMessages}
      />

      {activeConversation ? (
        <ChatPanel
          account={account}
          conversation={activeConversation}
          messages={messagesState.messages}
          hasMore={messagesState.hasMore}
          onLoadOlder={messagesState.loadOlder}
          onMessagesReload={messagesState.reload}
          onWorkspaceReload={workspace.reload}
          onBack={() => setMobileView('list')}
        />
      ) : (
        <section className="empty-page">
          <div>
            <EmptyArt />
            <h1>开始对话</h1>
            <p>从左侧选择一个联系人，或新建一个。</p>
          </div>
        </section>
      )}

      {showImport && (
        <ImportDialog onDone={handleImportDone} onCancel={() => setShowImport(false)} />
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
      <rect x="20" y="36" width="120" height="80" rx="20" fill="var(--brass-soft)" />
      <rect x="60" y="62" width="120" height="60" rx="20" fill="var(--brass-line)" />
      <circle cx="50" cy="68" r="4" fill="var(--brass)" />
      <circle cx="70" cy="68" r="4" fill="var(--brass)" />
      <circle cx="90" cy="68" r="4" fill="var(--brass)" />
    </svg>
  );
}
