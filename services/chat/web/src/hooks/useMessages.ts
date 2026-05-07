import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from '../api';
import type { Message } from '../api';

interface UseMessagesResult {
  messages: Message[];
  loading: boolean;
  error: string;
  reload: () => Promise<void>;
  /** Optimistically append a message (used by Composer + import). */
  prepend: (incoming: Message[]) => void;
  reset: (incoming: Message[]) => void;
}

/**
 * Loads messages for a conversation and keeps them live with long-polling.
 *
 * Fixes from previous version:
 *  - The initial fetch and the long-poll loop are sequenced (poll waits for
 *    initial load), so the poll can't race ahead with `lastId=0` while the
 *    server is still answering the immediate fetch.
 *  - Uses `serverTimeout=0` for the initial load (immediate, even if the
 *    conversation has zero messages — previously this hung).
 *  - StrictMode-safe: cancellation flag is checked before every state write.
 */
export function useMessages(conversationId: string | null, enabled: boolean): UseMessagesResult {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const lastIdRef = useRef(0);
  const cancelledRef = useRef(false);
  const conversationIdRef = useRef<string | null>(null);

  const updateLastId = useCallback((items: Message[]) => {
    if (items.length === 0) return;
    const max = items.reduce((m, x) => (x.id > m ? x.id : m), 0);
    if (max > lastIdRef.current) lastIdRef.current = max;
  }, []);

  const prepend = useCallback(
    (incoming: Message[]) => {
      if (!incoming.length) return;
      setMessages((previous) => {
        const seen = new Set(previous.map((m) => m.id));
        const fresh = incoming.filter((m) => !seen.has(m.id));
        if (!fresh.length) return previous;
        return [...previous, ...fresh].sort((a, b) => a.id - b.id);
      });
      updateLastId(incoming);
    },
    [updateLastId]
  );

  const reset = useCallback(
    (incoming: Message[]) => {
      setMessages(incoming);
      lastIdRef.current = incoming.reduce((m, x) => (x.id > m ? x.id : m), 0);
    },
    []
  );

  const reload = useCallback(async () => {
    if (!conversationIdRef.current) return;
    const id = conversationIdRef.current;
    setLoading(true);
    try {
      const initial = await api.getMessages(id, 0, 0);
      if (cancelledRef.current || conversationIdRef.current !== id) return;
      reset(initial);
      setError('');
    } catch (err) {
      if (!cancelledRef.current) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (!cancelledRef.current) setLoading(false);
    }
  }, [reset]);

  useEffect(() => {
    cancelledRef.current = false;
    conversationIdRef.current = conversationId;

    if (!enabled || !conversationId) {
      setMessages([]);
      lastIdRef.current = 0;
      return () => {
        cancelledRef.current = true;
      };
    }

    let cancelled = false;
    cancelledRef.current = false;
    lastIdRef.current = 0;
    setMessages([]);
    setError('');
    setLoading(true);

    const id = conversationId;

    (async () => {
      try {
        const initial = await api.getMessages(id, 0, 0);
        if (cancelled || conversationIdRef.current !== id) return;
        setMessages(initial);
        lastIdRef.current = initial.reduce((m, x) => (x.id > m ? x.id : m), 0);
        setLoading(false);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
        return;
      }

      while (!cancelled && conversationIdRef.current === id) {
        try {
          const incoming = await api.getMessages(id, lastIdRef.current, 30);
          if (cancelled || conversationIdRef.current !== id) return;
          if (incoming.length > 0) {
            setMessages((previous) => {
              const seen = new Set(previous.map((m) => m.id));
              const fresh = incoming.filter((m) => !seen.has(m.id));
              if (!fresh.length) return previous;
              return [...previous, ...fresh].sort((a, b) => a.id - b.id);
            });
            lastIdRef.current = incoming.reduce(
              (m, x) => (x.id > m ? x.id : m),
              lastIdRef.current
            );
          }
        } catch (err) {
          if (!cancelled) setError(err instanceof Error ? err.message : String(err));
          await new Promise((resolve) => setTimeout(resolve, 1500));
        }
      }
    })();

    return () => {
      cancelled = true;
      cancelledRef.current = true;
    };
  }, [conversationId, enabled]);

  return { messages, loading, error, reload, prepend, reset };
}
