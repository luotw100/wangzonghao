import { useState, useCallback, useRef, useEffect } from 'react';
import * as api from '../lib/api';
import type { Robot, Contact, Session, ProviderConfig, Message, PlannedReply } from '../lib/api';

export function useAppStore() {
  const [robots, setRobots] = useState<Robot[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [providerConfigs, setProviderConfigs] = useState<ProviderConfig[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [currentMessages, setCurrentMessages] = useState<Message[]>([]);
  const [inputText, setInputText] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [showDeletedItems, setShowDeletedItems] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [collapsedRobots, setCollapsedRobots] = useState<Record<string, boolean>>({});
  const [plannedReplies, setPlannedReplies] = useState<PlannedReply[]>([]);

  // Polling refs
  const pollAbortRef = useRef<AbortController | null>(null);
  const plannedPollAbortRef = useRef<AbortController | null>(null);
  const lastMsgIdRef = useRef(0);
  const activeSessionIdRef = useRef<string | null>(null);

  // Keep ref in sync
  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
  }, [activeSessionId]);

  // Computed
  const activeSession = sessions.find((s) => s.id === activeSessionId) || null;
  const activeConversationId = activeSession?.adapter?.thread_id || null;
  const isActiveSessionDeleted = Boolean(activeSession && activeSession.status === 'deleted');
  const isActiveSessionReadOnly = isActiveSessionDeleted;

  const activeRobots = robots.filter((r) => !r.is_deleted);
  const activeContacts = contacts.filter((c) => !c.is_deleted);

  const sessionsByRobot: Record<string, Session[]> = {};
  for (const robot of robots) {
    sessionsByRobot[robot.id] = [];
  }
  for (const session of sessions) {
    if (!sessionsByRobot[session.robot_id]) sessionsByRobot[session.robot_id] = [];
    sessionsByRobot[session.robot_id].push(session);
  }

  const activeSessionProviderName = (() => {
    if (!activeSession) return null;
    const pid = activeSession.provider_config_id;
    if (pid) {
      const p = providerConfigs.find((p) => p.id === pid);
      return p ? p.name : null;
    }
    if (providerConfigs.length > 0) return providerConfigs[0].name;
    return null;
  })();

  // --- Data Loading ---
  const loadRobots = useCallback(
    async (includeDeleted?: boolean) => {
      try {
        setRobots(await api.getRobots(includeDeleted ?? showDeletedItems));
      } catch (err: unknown) {
        setErrorMessage('加载 Robot 列表失败: ' + (err instanceof Error ? err.message : String(err)));
      }
    },
    [showDeletedItems]
  );

  const loadContacts = useCallback(
    async (includeDeleted?: boolean) => {
      try {
        setContacts(await api.getContacts(includeDeleted ?? showDeletedItems));
      } catch (err: unknown) {
        setErrorMessage('加载联系人列表失败: ' + (err instanceof Error ? err.message : String(err)));
      }
    },
    [showDeletedItems]
  );

  const loadSessions = useCallback(
    async (includeDeleted?: boolean) => {
      try {
        const list = await api.getSessions(includeDeleted ?? showDeletedItems);
        setSessions(list);
      } catch (err: unknown) {
        setErrorMessage('加载 Session 列表失败: ' + (err instanceof Error ? err.message : String(err)));
      }
    },
    [showDeletedItems]
  );

  const loadProviderConfigs = useCallback(async () => {
    try {
      setProviderConfigs(await api.getProviderConfigs());
    } catch (err: unknown) {
      setErrorMessage('加载 Provider 配置失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  }, []);

  const refreshAll = useCallback(async () => {
    await Promise.all([loadRobots(), loadContacts(), loadSessions(), loadProviderConfigs()]);
  }, [loadRobots, loadContacts, loadSessions, loadProviderConfigs]);

  // Load data on mount
  const mountedRef = useRef(false);
  useEffect(() => {
    if (!mountedRef.current) {
      mountedRef.current = true;
      refreshAll();
    }
  }, [refreshAll]);

  // Reload when showDeletedItems changes
  const prevShowDeletedRef = useRef(showDeletedItems);
  useEffect(() => {
    if (prevShowDeletedRef.current !== showDeletedItems) {
      prevShowDeletedRef.current = showDeletedItems;
      refreshAll();
    }
  }, [showDeletedItems, refreshAll]);

  // --- Polling ---
  const stopPolling = useCallback(() => {
    if (pollAbortRef.current) {
      pollAbortRef.current.abort();
      pollAbortRef.current = null;
    }
    if (plannedPollAbortRef.current) {
      plannedPollAbortRef.current.abort();
      plannedPollAbortRef.current = null;
    }
  }, []);

  const startLongPolling = useCallback(
    (convId: string, sessionId: string) => {
      stopPolling();
      const controller = new AbortController();
      pollAbortRef.current = controller;

      const renderedIds = new Set(currentMessages.map((m) => m.id));

      const pollLoop = async () => {
        let localLastMsgId = lastMsgIdRef.current;
        while (!controller.signal.aborted && activeSessionIdRef.current === sessionId) {
          try {
            const newMsgs = await api.getMessages(convId, localLastMsgId, 30, controller.signal);
            if (controller.signal.aborted || activeSessionIdRef.current !== sessionId) return;
            const dedupedMsgs = newMsgs.filter((m) => !renderedIds.has(m.id));
            if (dedupedMsgs.length > 0) {
              dedupedMsgs.forEach((m) => renderedIds.add(m.id));
              setCurrentMessages((prev) => [...prev, ...dedupedMsgs]);
              localLastMsgId = dedupedMsgs[dedupedMsgs.length - 1].id;
              lastMsgIdRef.current = localLastMsgId;
            }
          } catch (err: unknown) {
            if (controller.signal.aborted) return;
            const msg = err instanceof Error ? err.message : '';
            if (!msg.includes('超时') && !msg.includes('abort')) {
              setErrorMessage('消息同步异常: ' + msg);
            }
            await new Promise((r) => setTimeout(r, 1500));
          }
        }
      };

      pollLoop();
    },
    [stopPolling, currentMessages]
  );

  const startPlannedRepliesPolling = useCallback(
    (sessionId: string) => {
      if (plannedPollAbortRef.current) {
        plannedPollAbortRef.current.abort();
      }
      const controller = new AbortController();
      plannedPollAbortRef.current = controller;

      const pollLoop = async () => {
        let lastCount = -1;
        while (!controller.signal.aborted && activeSessionIdRef.current === sessionId) {
          try {
            const replies = await api.getPlannedReplies(sessionId, 30, controller.signal, lastCount);
            if (controller.signal.aborted || activeSessionIdRef.current !== sessionId) return;
            lastCount = replies.length;
            setPlannedReplies(replies);
          } catch (err: unknown) {
            if (controller.signal.aborted) return;
            const msg = err instanceof Error ? err.message : '';
            if (!msg.includes('超时') && !msg.includes('abort')) {
              // Silently ignore planned replies polling errors
            }
            await new Promise((r) => setTimeout(r, 1500));
          }
        }
      };

      pollLoop();
    },
    []
  );

  // --- Session Selection ---
  const clearActiveSession = useCallback(() => {
    stopPolling();
    setActiveSessionId(null);
    setCurrentMessages([]);
    setPlannedReplies([]);
    lastMsgIdRef.current = 0;
  }, [stopPolling]);

  const selectSession = useCallback(
    async (sessionId: string) => {
      stopPolling();
      setActiveSessionId(sessionId);
      setErrorMessage('');
      setCurrentMessages([]);
      setPlannedReplies([]);
      lastMsgIdRef.current = 0;

      try {
        const detail = await api.getSession(sessionId);
        setSessions((prev) => prev.map((s) => (s.id === sessionId ? detail : s)));

        const convId = detail.adapter?.thread_id;
        if (convId) {
          setTimeout(() => {
            startLongPolling(convId, sessionId);
            startPlannedRepliesPolling(sessionId);
          }, 0);
        }
      } catch (err: unknown) {
        setErrorMessage('加载 Session 详情失败: ' + (err instanceof Error ? err.message : String(err)));
      }
    },
    [stopPolling, startLongPolling, startPlannedRepliesPolling]
  );

  // --- Send Message ---
  const sendTextMessage = useCallback(async () => {
    const text = inputText.trim();
    if (!text || !activeConversationId) return;
    if (isActiveSessionReadOnly) {
      setErrorMessage('已删除的 Session 不能发送消息');
      return;
    }
    setInputText('');
    try {
      await api.sendMessage(activeConversationId, { role: 'user', msg_type: 'text', content: text });
    } catch (err: unknown) {
      setErrorMessage('发送消息失败: ' + (err instanceof Error ? err.message : String(err)));
    }
  }, [inputText, activeConversationId, isActiveSessionReadOnly]);

  // --- Provider switch ---
  const switchSessionProvider = useCallback(
    async (providerId: string) => {
      if (!activeSessionId || isActiveSessionReadOnly) return;
      try {
        const updated = await api.updateSession(activeSessionId, { provider_config_id: providerId });
        setSessions((prev) => prev.map((s) => (s.id === activeSessionId ? updated : s)));
      } catch (err: unknown) {
        setErrorMessage('切换 Provider 失败: ' + (err instanceof Error ? err.message : String(err)));
      }
    },
    [activeSessionId, isActiveSessionReadOnly]
  );

  const toggleRobot = useCallback((robotId: string) => {
    setCollapsedRobots((prev) => ({ ...prev, [robotId]: !prev[robotId] }));
  }, []);

  // Cleanup
  useEffect(() => {
    return () => {
      stopPolling();
    };
  }, [stopPolling]);

  return {
    // State
    robots,
    contacts,
    sessions,
    setSessions,
    providerConfigs,
    activeSessionId,
    activeSession,
    activeConversationId,
    currentMessages,
    plannedReplies,
    inputText,
    setInputText,
    errorMessage,
    setErrorMessage,
    showDeletedItems,
    setShowDeletedItems,
    sidebarOpen,
    setSidebarOpen,
    collapsedRobots,
    isActiveSessionDeleted,
    isActiveSessionReadOnly,
    sessionsByRobot,
    activeRobots,
    activeContacts,
    activeSessionProviderName,

    // Actions
    refreshAll,
    loadRobots,
    loadContacts,
    loadSessions,
    loadProviderConfigs,
    selectSession,
    clearActiveSession,
    sendTextMessage,
    switchSessionProvider,
    toggleRobot,
  };
}
