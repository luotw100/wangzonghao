import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, useNavigate } from 'react-router-dom';
import { HomePage } from './pages/HomePage';
import { ChatPage } from './pages/ChatPage';
import { RobotPage } from './pages/RobotPage';
import { LoginPage } from './pages/LoginPage';
import { AdminPage } from './pages/AdminPage';
import { setUnauthorizedHandler } from './lib/api';

function UnauthorizedRedirect() {
  const navigate = useNavigate();
  useEffect(() => {
    setUnauthorizedHandler(() => {
      // Avoid bouncing if already on /login
      if (window.location.pathname !== '/login') {
        navigate('/login', { replace: true });
      }
    });
    return () => setUnauthorizedHandler(null);
  }, [navigate]);
  return null;
}

export default function App() {
  return (
    <BrowserRouter>
      <UnauthorizedRedirect />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/robot" element={<RobotPage />} />
        <Route path="/admin" element={<AdminPage />} />
      </Routes>
    </BrowserRouter>
  );
}
