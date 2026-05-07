import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import * as api from '../lib/api';
import { useAuth } from '../lib/auth';
import { LaborsterLogo } from '../components/Icons';

export function LoginPage() {
  const navigate = useNavigate();
  const { refresh } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const handleLogin = async () => {
    if (!username.trim() || !password) {
      setError('请填写用户名和密码');
      return;
    }
    setError('');
    setBusy(true);
    try {
      const r = await api.login(username.trim(), password);
      api.setToken(r.token);
      await refresh();
      navigate('/studio', { replace: true });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="w-full h-dvh flex items-center justify-center bg-bg-primary tech-grid">
      <div className="w-full max-w-md px-8">
        <div className="flex flex-col items-center mb-8">
          <div className="w-16 h-16 rounded-full bg-bg-tertiary flex items-center justify-center laborster-empty-logo mb-4">
            <LaborsterLogo size={32} id="loginGrad" />
          </div>
          <h1 className="font-brand text-xl tracking-wider text-accent">Laborster</h1>
          <p className="text-text-secondary text-sm mt-2">Studio 后台</p>
        </div>

        <div className="bg-bg-secondary/50 border border-border-glow/20 rounded-2xl p-6">
          <label className="text-xs text-text-secondary mb-2 block">用户名</label>
          <input
            value={username}
            autoFocus
            onChange={e => setUsername(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleLogin(); }}
            placeholder="username"
            className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50 mb-4"
          />
          <label className="text-xs text-text-secondary mb-2 block">密码</label>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleLogin(); }}
            placeholder="password"
            className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50 mb-4"
          />
          <button
            onClick={handleLogin}
            disabled={busy || !username.trim() || !password}
            className="w-full px-4 py-3 rounded-xl bg-accent/20 text-accent border border-accent/40 hover:bg-accent/30 disabled:opacity-30 btn-neon text-sm"
          >{busy ? '登录中...' : '登录'}</button>

          {error && (
            <div className="mt-4 px-3 py-2 bg-danger-bg rounded-lg text-xs text-danger break-all">{error}</div>
          )}
        </div>

        <div className="text-center text-xs text-text-tertiary mt-6">
          账号由 CLI 创建：<span className="font-mono">uv run python -m studio.cli create-account ...</span>
        </div>
      </div>
    </div>
  );
}
