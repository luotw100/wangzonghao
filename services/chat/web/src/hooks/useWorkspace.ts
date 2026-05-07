import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from '../api';
import type { Contact, Conversation } from '../api';

export interface WorkspaceState {
  contacts: Contact[];
  conversations: Conversation[];
  loaded: boolean;
}

export function useWorkspace(enabled: boolean) {
  const [state, setState] = useState<WorkspaceState>({
    contacts: [],
    conversations: [],
    loaded: false,
  });
  const inFlight = useRef(false);

  const reload = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const [contacts, conversations] = await Promise.all([
        api.listContacts(),
        api.listConversations(),
      ]);
      setState({ contacts, conversations, loaded: true });
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      setState({ contacts: [], conversations: [], loaded: false });
      return;
    }
    reload().catch(() => {
      /* error surfaced by caller */
    });
  }, [enabled, reload]);

  return { ...state, reload, setState };
}
