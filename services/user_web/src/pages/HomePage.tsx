import { useEffect, useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import * as api from '../lib/api';
import { useAuth } from '../lib/auth';

export function HomePage() {
  const navigate = useNavigate();
  const { account, loading, refresh } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!loading && account) navigate('/studio', { replace: true });
  }, [account, loading, navigate]);

  const handleLogin = async () => {
    if (!username.trim() || !password) {
      setError('请填写用户名和密码');
      return;
    }
    setError('');
    setBusy(true);
    try {
      const result = await api.login(username.trim(), password);
      api.setToken(result.token);
      await refresh();
      navigate('/studio', { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (loading) return null;
  if (account) return <Navigate to="/studio" replace />;

  return (
    <div className="lab-screen" style={{ display: 'flex', height: '100dvh' }}>
      <div
        style={{
          flex: 1,
          padding: '48px 56px',
          borderRight: '1px solid var(--line-subtle)',
          background: 'linear-gradient(135deg, var(--bg-deep) 0%, var(--bg-base) 100%)',
          position: 'relative',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span className="lab-mark" />
          <span style={{ fontFamily: 'var(--f-serif)', fontSize: 18, fontWeight: 500, letterSpacing: '-0.01em' }}>Laborster</span>
          <span className="chip mono" style={{ marginLeft: 6 }}>Studio</span>
        </div>

        <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: 20 }}>
          <h1
            className="serif"
            style={{
              fontSize: 56,
              lineHeight: 1,
              margin: 0,
              letterSpacing: '-0.03em',
              fontWeight: 400,
              color: 'var(--ink-1)',
            }}
          >
            一个人，
            <br />
            维持<span style={{ color: 'var(--brass)' }}>一千段关系</span>。
          </h1>
          <p style={{ margin: 0, maxWidth: 460, lineHeight: 1.75, color: 'var(--ink-3)', fontSize: 15 }}>
            你不在的时候，它替你接住每一条粉丝消息，按你的语气回复。
            <br />
            聊天记录留在你自己的电脑上，回复方式由你决定。
          </p>
        </div>
      </div>

      <div style={{ width: 460, flex: '0 0 460px', padding: '64px 56px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
        <h2 className="serif" style={{ fontSize: 28, margin: '0 0 28px', fontWeight: 400, letterSpacing: '-0.02em' }}>
          欢迎回来
        </h2>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span className="text-xs text-ink-3">用户名</span>
            <input
              className="input"
              autoFocus
              value={username}
              onChange={event => setUsername(event.target.value)}
              onKeyDown={event => {
                if (event.key === 'Enter') handleLogin();
              }}
            />
          </label>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span className="text-xs text-ink-3">密码</span>
            <input
              className="input"
              type="password"
              value={password}
              onChange={event => setPassword(event.target.value)}
              onKeyDown={event => {
                if (event.key === 'Enter') handleLogin();
              }}
            />
          </label>
          <button
            onClick={handleLogin}
            disabled={busy || !username.trim() || !password}
            className="btn btn-primary"
            style={{ height: 42, fontSize: 14, marginTop: 8 }}
          >
            {busy ? '登录中…' : '登录'}
          </button>

          {error && (
            <div
              style={{
                padding: '10px 12px',
                background: 'oklch(0.62 0.150 22 / 0.12)',
                border: '1px solid oklch(0.62 0.150 22 / 0.35)',
                borderRadius: 8,
                color: 'var(--danger)',
                fontSize: 12,
                wordBreak: 'break-all',
              }}
            >
              {error}
            </div>
          )}
        </div>

        <div className="divider mt-6" style={{ marginTop: 24 }} />
        <div style={{ marginTop: 16, fontSize: 12, color: 'var(--ink-4)', lineHeight: 1.6 }}>
          没有账号或忘记密码，请联系管理员。
        </div>
      </div>
    </div>
  );
}
