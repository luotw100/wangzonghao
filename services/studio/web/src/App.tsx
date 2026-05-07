import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, useNavigate } from 'react-router-dom';
import { HomePage } from './pages/HomePage';
import { StudioPage } from './pages/StudioPage';
import { LoginPage } from './pages/LoginPage';
import { setUnauthorizedHandler } from './lib/api';
import { AuthProvider, RedirectIfAuthed, RequireAuth, useAuth } from './lib/auth';

function UnauthorizedRedirect() {
  const navigate = useNavigate();
  const { refresh } = useAuth();
  useEffect(() => {
    setUnauthorizedHandler(() => {
      refresh();
      if (window.location.pathname !== '/login') {
        navigate('/login', { replace: true });
      }
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
          <Route path="/login" element={<RedirectIfAuthed><LoginPage /></RedirectIfAuthed>} />
          <Route path="/studio" element={<RequireAuth><StudioPage /></RequireAuth>} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
