import { createContext, useContext } from 'react';
import type { Account } from './api';

export interface AuthState {
  account: Account | null;
  loading: boolean;
  refresh: () => Promise<Account | null>;
  logout: () => Promise<void>;
}

export const AuthCtx = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const v = useContext(AuthCtx);
  if (!v) throw new Error('useAuth must be used within <AuthProvider>');
  return v;
}
