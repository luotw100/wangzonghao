import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from '../api';
import type { Message } from '../api';

const INITIAL_LIMIT = 100;

interface UseMessagesResult {
  messages: Message[];
  hasMore: boolean;
  loadOlder: () => Promise<void>;
  reload: () => Promise<void>;
  reset: (incoming: Message[]) => void;
}

export function useMessages(
  conversationId: string | null,
  enabled: boolean,
  seedMessages?: Message[],
): UseMessagesResult {
  const [messages, setMessages] = useState<Message[]>([]);
  const [hasMore, setHasMore] = useState(false);

  const lastIdRef = useRef(0);
  const oldestIdRef = useRef<number | null>(null);
  const hasMoreRef = useRef(false);
  const loadingOlderRef = useRef(false);
  const cancelledRef = useRef(false);
  const conversationIdRef = useRef<string | null>(null);
  // Keep the latest seed in a ref so the load effect can read it without
  // listing it as a dependency. Updated after commit, before the load effect
  // below runs (declaration order), so the effect always sees the latest seed.
  const seedRef = useRef(seedMessages);
  useEffect(() => {
    seedRef.current = seedMessages;
  });

  const updateLastId = useCallback((items: Message[]) => {
    if (items.length === 0) return;
    const max = items.reduce((m, x) => (x.id > m ? x.id : m), 0);
    if (max > lastIdRef.current) lastIdRef.current = max;
  }, []);

  const reset = useCallback((incoming: Message[]) => {
    setMessages(incoming);
    lastIdRef.current = incoming.reduce((m, x) => (x.id > m ? x.id : m), 0);
    oldestIdRef.current = incoming.length > 0 ? incoming[0].id : null;
    const more = incoming.length === INITIAL_LIMIT;
    hasMoreRef.current = more;
    setHasMore(more);
  }, []);

  const reload = useCallback(async () => {
    if (!conversationIdRef.current) return;
    const id = conversationIdRef.current;
    try {
      const initial = await api.getMessagesBefore(id, undefined, INITIAL_LIMIT);
      if (cancelledRef.current || conversationIdRef.current !== id) return;
      reset(initial);
    } catch {
      // silent — poll loop will retry
    }
  }, [reset]);

  const loadOlder = useCallback(async () => {
    if (!conversationIdRef.current || !hasMoreRef.current || loadingOlderRef.current) return;
    const id = conversationIdRef.current;
    const beforeId = oldestIdRef.current;
    if (!beforeId) return;

    loadingOlderRef.current = true;
    try {
      const older = await api.getMessagesBefore(id, beforeId, INITIAL_LIMIT);
      if (cancelledRef.current || conversationIdRef.current !== id) return;
      const more = older.length === INITIAL_LIMIT;
      if (older.length > 0) {
        oldestIdRef.current = older[0].id;
        setMessages((prev) => {
          const seen = new Set(prev.map((m) => m.id));
          const fresh = older.filter((m) => !seen.has(m.id));
          return fresh.length > 0 ? [...fresh, ...prev] : prev;
        });
      }
      hasMoreRef.current = more;
      setHasMore(more);
    } catch {
      // silent
    } finally {
      loadingOlderRef.current = false;
    }
  }, []);

  // This effect subscribes to an external system (the messages long-poll API)
  // and must synchronously reset/seed local state when the conversation
  // changes — a legitimate subscription effect, not derived-state syncing.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    cancelledRef.current = false;
    conversationIdRef.current = conversationId;

    if (!enabled || !conversationId) {
      setMessages([]);
      setHasMore(false);
      lastIdRef.current = 0;
      oldestIdRef.current = null;
      hasMoreRef.current = false;
      return () => {
        cancelledRef.current = true;
      };
    }

    let cancelled = false;
    cancelledRef.current = false;

    const id = conversationId;
    const seed = seedRef.current;
    const hasSeed = seed && seed.length > 0;

    if (hasSeed) {
      // Show cached messages immediately so the UI is responsive on switch.
      setMessages(seed);
      lastIdRef.current = seed.reduce((m, x) => (x.id > m ? x.id : m), 0);
      oldestIdRef.current = seed[0].id;
      const more = seed.length === INITIAL_LIMIT;
      hasMoreRef.current = more;
      setHasMore(more);
    } else {
      lastIdRef.current = 0;
      oldestIdRef.current = null;
      hasMoreRef.current = false;
      setMessages([]);
      setHasMore(false);
    }

    (async () => {
      if (!hasSeed) {
        // No cache: fetch initial batch first.
        try {
          const initial = await api.getMessagesBefore(id, undefined, INITIAL_LIMIT);
          if (cancelled || conversationIdRef.current !== id) return;
          setMessages(initial);
          lastIdRef.current = initial.reduce((m, x) => (x.id > m ? x.id : m), 0);
          oldestIdRef.current = initial.length > 0 ? initial[0].id : null;
          const more = initial.length === INITIAL_LIMIT;
          hasMoreRef.current = more;
          setHasMore(more);
        } catch {
          if (!cancelled) {
            await new Promise((resolve) => setTimeout(resolve, 1500));
          }
          return;
        }
      }

      // Long-poll for messages newer than what we already have.
      while (!cancelled && conversationIdRef.current === id) {
        try {
          const incoming = await api.getMessagesAfter(id, lastIdRef.current);
          if (cancelled || conversationIdRef.current !== id) return;
          if (incoming.length > 0) {
            setMessages((previous) => {
              const seen = new Set(previous.map((m) => m.id));
              const fresh = incoming.filter((m) => !seen.has(m.id));
              if (!fresh.length) return previous;
              return [...previous, ...fresh].sort((a, b) => a.id - b.id);
            });
            updateLastId(incoming);
          }
        } catch {
          await new Promise((resolve) => setTimeout(resolve, 1500));
        }
      }
    })();

    return () => {
      cancelled = true;
      cancelledRef.current = true;
    };
  }, [conversationId, enabled, updateLastId]);
  /* eslint-enable react-hooks/set-state-in-effect */

  return { messages, hasMore, loadOlder, reload, reset };
}
