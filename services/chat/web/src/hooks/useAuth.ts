import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from '../api';
import type { Account } from '../api';

export interface AuthState {
  account: Account | null;
  loading: boolean;
  error: string;
}

export function useAuth() {
  const [state, setState] = useState<AuthState>({ account: null, loading: false, error: '' });
  const bootRef = useRef(false);

  useEffect(() => {
    if (bootRef.current) return;
    bootRef.current = true;
    if (!api.getToken()) return;
    api
      .me()
      .then((account) => setState((s) => ({ ...s, account })))
      .catch((err) => {
        setState((s) => ({ ...s, error: err instanceof Error ? err.message : String(err) }));
      });
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    setState((s) => ({ ...s, loading: true, error: '' }));
    try {
      const result = await api.login(username, password);
      api.setToken(result.token);
      setState({ account: result.account, loading: false, error: '' });
    } catch (err) {
      setState((s) => ({
        ...s,
        loading: false,
        error: err instanceof Error ? err.message : String(err),
      }));
      throw err;
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // ignore — local clear is enough
    }
    api.setToken(null);
    setState({ account: null, loading: false, error: '' });
  }, []);

  return { ...state, login, logout };
}
