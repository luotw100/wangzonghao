import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import * as api from './api';
import type { Account } from './api';
import { LaborsterLogo } from '../components/Icons';

interface AuthState {
  account: Account | null;
  loading: boolean;
  refresh: () => Promise<Account | null>;
  logout: () => Promise<void>;
}

const AuthCtx = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const v = useContext(AuthCtx);
  if (!v) throw new Error('useAuth must be used within <AuthProvider>');
  return v;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!api.getToken()) {
      setAccount(null);
      return null;
    }
    try {
      const a = await api.authMe();
      setAccount(a);
      return a;
    } catch {
      setAccount(null);
      return null;
    }
  }, []);

  const logout = useCallback(async () => {
    try { await api.authLogout(); } catch { /* ignore */ }
    api.setToken(null);
    setAccount(null);
  }, []);

  useEffect(() => {
    refresh().finally(() => setLoading(false));
  }, [refresh]);

  return (
    <AuthCtx.Provider value={{ account, loading, refresh, logout }}>
      {children}
    </AuthCtx.Provider>
  );
}


function Splash() {
  return (
    <div className="w-full h-dvh flex items-center justify-center bg-bg-primary tech-grid">
      <div className="w-12 h-12 rounded-full bg-bg-tertiary flex items-center justify-center laborster-empty-logo opacity-60">
        <LaborsterLogo size={24} id="splashGrad" />
      </div>
    </div>
  );
}


export function RequireAuth({ children }: { children: ReactNode }) {
  const { account, loading } = useAuth();
  if (loading) return <Splash />;
  if (!account) return <Navigate to="/login" replace />;
  return <>{children}</>;
}


export function RedirectIfAuthed({ children }: { children: ReactNode }) {
  const { account, loading } = useAuth();
  if (loading) return <Splash />;
  if (account) return <Navigate to="/studio" replace />;
  return <>{children}</>;
}
