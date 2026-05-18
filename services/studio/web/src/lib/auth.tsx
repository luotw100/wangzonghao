import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import * as api from './api';
import type { Account } from './api';

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
    <div
      className="lab-screen lab-tech-grid"
      style={{ height: '100dvh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
    >
      <span className="lab-mark" style={{ opacity: 0.7 }} />
    </div>
  );
}


export function RequireAuth({ children }: { children: ReactNode }) {
  const { account, loading } = useAuth();
  if (loading) return <Splash />;
  if (!account) return <Navigate to="/" replace />;
  return <>{children}</>;
}
