import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, useNavigate } from 'react-router-dom';
import { HomePage } from './pages/HomePage';
import { StudioPage } from './pages/StudioPage.tsx';
import ChatApp from './chat/App';
import './chat/styles.css';
import { setUnauthorizedHandler } from './lib/api';
import { AuthProvider, RequireAuth, useAuth } from './lib/auth';

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
          <Route path="/studio" element={<RequireAuth><StudioPage /></RequireAuth>} />
          <Route path="/chat" element={<RequireAuth><ChatApp /></RequireAuth>} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
