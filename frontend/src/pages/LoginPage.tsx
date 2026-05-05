import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import * as api from '../lib/api';
import { LaborsterLogo } from '../components/Icons';

type Step = 'email' | 'code';

export function LoginPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>('email');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [resendIn, setResendIn] = useState(0);

  // Already logged in? redirect by role.
  useEffect(() => {
    api.authMe()
      .then(account => {
        if (account.role === 'admin') navigate('/admin', { replace: true });
        else navigate('/robot', { replace: true });
      })
      .catch(() => { /* not logged in, stay */ });
  }, [navigate]);

  useEffect(() => {
    if (resendIn <= 0) return;
    const t = setInterval(() => setResendIn(s => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, [resendIn]);

  const handleSendCode = async () => {
    const e = email.trim();
    if (!e || !/.+@.+\..+/.test(e)) {
      setError('请填写正确的邮箱');
      return;
    }
    setError('');
    setInfo('');
    setBusy(true);
    try {
      const r = await api.authRequestCode(e);
      setStep('code');
      setInfo(`验证码已发送，请查收邮件（${r.expires_in_seconds}s 内有效）`);
      setResendIn(60);
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    } finally {
      setBusy(false);
    }
  };

  const handleVerify = async () => {
    if (!code.trim()) {
      setError('请填写验证码');
      return;
    }
    setError('');
    setBusy(true);
    try {
      const r = await api.authVerifyCode(email.trim(), code.trim());
      if (r.account.role === 'admin') navigate('/admin', { replace: true });
      else navigate('/robot', { replace: true });
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
          <p className="text-text-secondary text-sm mt-2">Robot 后台</p>
        </div>

        <div className="bg-bg-secondary/50 border border-border-glow/20 rounded-2xl p-6">
          {step === 'email' ? (
            <>
              <label className="text-xs text-text-secondary mb-2 block">邮箱</label>
              <input
                type="email"
                value={email}
                autoFocus
                onChange={e => setEmail(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') handleSendCode(); }}
                placeholder="you@example.com"
                className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-sm outline-none focus:border-accent/50 mb-4"
              />
              <button
                onClick={handleSendCode}
                disabled={busy || !email.trim()}
                className="w-full px-4 py-3 rounded-xl bg-accent/20 text-accent border border-accent/40 hover:bg-accent/30 disabled:opacity-30 btn-neon text-sm"
              >{busy ? '发送中...' : '发送验证码'}</button>
            </>
          ) : (
            <>
              <div className="mb-4 text-xs text-text-secondary">
                验证码已发到 <span className="text-accent">{email}</span>
              </div>
              <label className="text-xs text-text-secondary mb-2 block">6 位验证码</label>
              <input
                inputMode="numeric"
                pattern="[0-9]*"
                value={code}
                autoFocus
                maxLength={6}
                onChange={e => setCode(e.target.value.replace(/\D/g, ''))}
                onKeyDown={e => { if (e.key === 'Enter') handleVerify(); }}
                placeholder="000000"
                className="w-full bg-bg-tertiary border border-border-glow/30 rounded-xl px-4 py-3 text-lg font-mono tracking-[0.5em] text-center outline-none focus:border-accent/50 mb-4"
              />
              <button
                onClick={handleVerify}
                disabled={busy || code.length < 6}
                className="w-full px-4 py-3 rounded-xl bg-accent/20 text-accent border border-accent/40 hover:bg-accent/30 disabled:opacity-30 btn-neon text-sm mb-2"
              >{busy ? '验证中...' : '登录'}</button>
              <div className="flex items-center justify-between text-xs text-text-secondary">
                <button
                  onClick={() => { setStep('email'); setCode(''); setError(''); setInfo(''); }}
                  className="hover:text-accent"
                >← 修改邮箱</button>
                <button
                  onClick={handleSendCode}
                  disabled={resendIn > 0 || busy}
                  className="hover:text-accent disabled:opacity-50"
                >{resendIn > 0 ? `重新发送 (${resendIn}s)` : '重新发送'}</button>
              </div>
            </>
          )}

          {error && (
            <div className="mt-4 px-3 py-2 bg-danger-bg rounded-lg text-xs text-danger break-all">{error}</div>
          )}
          {info && !error && (
            <div className="mt-4 px-3 py-2 bg-bg-tertiary rounded-lg text-xs text-text-secondary break-all">{info}</div>
          )}
        </div>

        <div className="text-center text-xs text-text-tertiary mt-6">
          首次登录会自动注册，等待管理员审批后可使用。
        </div>
      </div>
    </div>
  );
}
