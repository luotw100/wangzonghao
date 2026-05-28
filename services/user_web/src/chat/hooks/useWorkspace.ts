import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from '../api';
import type { Conversation } from '../api';

export interface WorkspaceState {
  conversations: Conversation[];
  loaded: boolean;
}

export function useWorkspace(enabled: boolean) {
  const [state, setState] = useState<WorkspaceState>({
    conversations: [],
    loaded: false,
  });
  const inFlight = useRef(false);

  const reload = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const conversations = await api.listConversations();
      setState({ conversations, loaded: true });
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      // Clear the workspace when the account goes away (e.g. logout) so a
      // later sign-in starts from a clean loading state rather than stale data.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setState({ conversations: [], loaded: false });
      return;
    }
    reload().catch(() => {
      /* error surfaced by caller */
    });
  }, [enabled, reload]);

  return { ...state, reload, setState };
}
