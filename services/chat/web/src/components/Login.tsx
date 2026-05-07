import { FormEvent, useState } from 'react';

interface LoginProps {
  loading: boolean;
  error: string;
  onLogin: (username: string, password: string) => Promise<void>;
}

export default function Login({ loading, error, onLogin }: LoginProps) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const u = username.trim();
    if (!u || !password) return;
    try {
      await onLogin(u, password);
    } catch {
      // error displayed via prop
    }
  }

  return (
    <main className="login-shell">
      <section className="login-card">
        <div className="brand-row">
          <div className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">
              <path d="M9.5 4.5C5.36 4.5 2 7.46 2 11.1c0 2.05 1.06 3.88 2.74 5.1l-.66 2.05a.4.4 0 0 0 .61.45l2.4-1.45c.78.2 1.6.3 2.41.3.27 0 .54-.01.8-.03A6.5 6.5 0 0 1 9 14.1c0-3.36 3.13-6.1 7-6.1.41 0 .82.03 1.21.1C16.39 5.62 13.21 4.5 9.5 4.5Zm-2.6 4.7a.95.95 0 1 1 0 1.9.95.95 0 0 1 0-1.9Zm5.2 0a.95.95 0 1 1 0 1.9.95.95 0 0 1 0-1.9ZM16 9.6c-3.31 0-6 2.46-6 5.5 0 1.7.85 3.22 2.18 4.23l-.5 1.6a.34.34 0 0 0 .52.39l1.95-1.18c.59.15 1.21.23 1.85.23 3.31 0 6-2.46 6-5.5s-2.69-5.27-6-5.27Zm-2 4.05a.8.8 0 1 1 0 1.6.8.8 0 0 1 0-1.6Zm4 0a.8.8 0 1 1 0 1.6.8.8 0 0 1 0-1.6Z" />
            </svg>
          </div>
          <div>
            <p className="eyebrow">CHAT</p>
            <h1>登录到本地沙盒</h1>
          </div>
        </div>
        <p className="muted">
          每个账号都是一个独立的微信式沙盒。联系人只属于当前账号，互不影响。
        </p>
        <form onSubmit={handleSubmit} className="stack">
          <label>
            <span>用户名</span>
            <input
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoFocus
              autoComplete="username"
              spellCheck={false}
              placeholder="例如 demo"
            />
          </label>
          <label>
            <span>密码</span>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
            />
          </label>
          <button className="primary" disabled={loading || !username.trim() || !password}>
            {loading ? '登录中…' : '登录'}
          </button>
        </form>
        {error && <div className="error">{error}</div>}
      </section>
    </main>
  );
}
