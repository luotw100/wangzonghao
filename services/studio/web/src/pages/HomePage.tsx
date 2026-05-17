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
    <div className="lab-screen lab-tech-grid" style={{ display: 'flex', height: '100dvh' }}>
      <div
        className="col"
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
        <div className="row gap-3" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span className="lab-mark" />
          <span style={{ fontFamily: 'var(--f-serif)', fontSize: 18, fontWeight: 500, letterSpacing: '-0.01em' }}>Laborster</span>
          <span className="chip mono" style={{ marginLeft: 6 }}>Studio</span>
        </div>

        <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: 18 }}>
          <span className="eyebrow">Private Relationship Cockpit</span>
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
          <p style={{ margin: 0, maxWidth: 480, lineHeight: 1.7, color: 'var(--ink-3)', fontSize: 14 }}>
            把人设、记忆、节奏托管给 Studio。设备在你电脑上跑，
            消息留在本地，回复由你的语料蒸馏出来，不是替你说话，是替你保温。
          </p>
        </div>

        <div style={{ display: 'flex', gap: 24, marginTop: 38, color: 'var(--ink-4)' }}>
          {[
            { n: '聊天账号', s: '微信 · 飞书 等', e: '消息来源' },
            { n: '设备', s: '主播电脑上运行', e: '在你电脑' },
            { n: 'Studio', s: '统一管理后台', e: '在云端' },
          ].map((block, index) => (
            <div key={index} style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
              <span className="eyebrow text-brass">{block.e}</span>
              <span className="serif text-lg mt-1" style={{ color: 'var(--ink-2)', fontSize: 16 }}>{block.n}</span>
              <span className="text-xs mono mt-1">{block.s}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ width: 460, flex: '0 0 460px', padding: '64px 56px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
        <span className="eyebrow">登录</span>
        <h2 className="serif mt-2" style={{ fontSize: 28, margin: '6px 0 28px', fontWeight: 400, letterSpacing: '-0.02em' }}>
          欢迎回来
        </h2>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <label className="col gap-2" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span className="text-xs text-ink-3 mono">USERNAME</span>
            <input
              className="input"
              autoFocus
              value={username}
              onChange={event => setUsername(event.target.value)}
              onKeyDown={event => {
                if (event.key === 'Enter') handleLogin();
              }}
              placeholder="alice"
            />
          </label>
          <label className="col gap-2" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span className="text-xs text-ink-3 mono">PASSWORD</span>
            <input
              className="input"
              type="password"
              value={password}
              onChange={event => setPassword(event.target.value)}
              onKeyDown={event => {
                if (event.key === 'Enter') handleLogin();
              }}
              placeholder="········"
            />
          </label>
          <button
            onClick={handleLogin}
            disabled={busy || !username.trim() || !password}
            className="btn btn-primary"
            style={{ height: 42, fontSize: 14, marginTop: 8 }}
          >
            {busy ? '登录中…' : '进入 Studio'}
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
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 16, fontSize: 11, color: 'var(--ink-4)' }}>
          <div>没有账号？请联系管理员为你创建。</div>
          <div>忘记密码请联系管理员，在「设置」里帮你重置。</div>
        </div>
      </div>
    </div>
  );
}
