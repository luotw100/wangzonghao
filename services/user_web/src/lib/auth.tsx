import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { Navigate } from 'react-router-dom';
import * as api from './api';
import type { Account } from './api';
import { AuthCtx, useAuth } from './auth-context';

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
    // Bootstrap auth from the stored token on mount; refresh() may clear
    // account synchronously when no token is present, which is intentional.
    // eslint-disable-next-line react-hooks/set-state-in-effect
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
