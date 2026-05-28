import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { HomePage } from './pages/HomePage';
import { StudioPage } from './pages/StudioPage.tsx';
import ChatApp from './chat/App';
import './chat/styles.css';
import { setUnauthorizedHandler } from './lib/api';
import { AuthProvider, RequireAuth } from './lib/auth';
import { useAuth } from './lib/auth-context';

function UnauthorizedRedirect() {
  const navigate = useNavigate();
  const { refresh } = useAuth();
  useEffect(() => {
    setUnauthorizedHandler(() => {
      refresh();
      if (window.location.pathname !== '/') navigate('/', { replace: true });
    });
    return () => setUnauthorizedHandler(null);
  }, [navigate, refresh]);
  return null;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <UnauthorizedRedirect />
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/studio" element={<Navigate to="/studio/takeover" replace />} />
          <Route path="/studio/:tab" element={<RequireAuth><StudioPage /></RequireAuth>} />
          <Route path="/chat" element={<RequireAuth><ChatApp /></RequireAuth>} />
          <Route path="/chat/c/:conversationId" element={<RequireAuth><ChatApp /></RequireAuth>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
