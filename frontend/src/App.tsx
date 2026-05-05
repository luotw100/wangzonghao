import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, useNavigate } from 'react-router-dom';
import { HomePage } from './pages/HomePage';
import { ChatPage } from './pages/ChatPage';
import { RobotPage } from './pages/RobotPage';
import { LoginPage } from './pages/LoginPage';
import { AdminPage } from './pages/AdminPage';
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
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/robot" element={<RequireAuth><RobotPage /></RequireAuth>} />
          <Route path="/admin" element={<RequireAuth role="admin"><AdminPage /></RequireAuth>} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
