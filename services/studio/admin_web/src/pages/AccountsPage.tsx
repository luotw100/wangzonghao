import { useEffect, useState } from 'react';
import * as api from '../api.ts';

type Modal =
  | { kind: 'create' }
  | { kind: 'reset'; accountId: string; username: string }
  | { kind: 'distill'; accountId: string; username: string; currentProviderId: string };

export function AccountsPage() {
  const [accounts, setAccounts] = useState<api.Account[]>([]);
  const [providers, setProviders] = useState<api.Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [modal, setModal] = useState<Modal | null>(null);

  const load = () => {
    setLoading(true);
    Promise.all([api.getAccounts(), api.getProviders()])
      .then(([a, p]) => { setAccounts(a); setProviders(p); setError(''); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>Accounts</h1>
        <button className="btn btn-primary btn-sm" onClick={() => setModal({ kind: 'create' })}>
          + New Account
        </button>
      </div>

      {error && <div style={{ color: 'var(--danger)', marginBottom: 12, fontSize: 12 }}>{error}</div>}

      <div style={{ background: 'var(--bg-base)', border: '1px solid var(--line-subtle)', borderRadius: 'var(--r-lg)', overflow: 'hidden' }}>
        {loading ? (
          <div style={{ padding: 24, color: 'var(--ink-4)', textAlign: 'center' }}>Loading…</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Username</th>
                <th>Display Name</th>
                <th>Status</th>
                <th>Distill Provider</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {accounts.length === 0 && (
                <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--ink-4)', padding: 24 }}>No accounts</td></tr>
              )}
              {accounts.map(a => (
                <tr key={a.id}>
                  <td style={{ fontWeight: 500 }}>{a.username}</td>
                  <td style={{ color: 'var(--ink-2)' }}>{a.display_name}</td>
                  <td>
                    <span className={`chip ${a.status === 'active' ? 'active' : 'disabled'}`}>{a.status}</span>
                  </td>
                  <td style={{ color: 'var(--ink-2)' }}>{a.distill_provider_name}</td>
                  <td className="mono">{a.created_at.slice(0, 10)}</td>
                  <td>
                    <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                      <button className="btn btn-ghost btn-sm" onClick={() => setModal({ kind: 'reset', accountId: a.id, username: a.username })}>
                        Reset PW
                      </button>
                      <button className="btn btn-ghost btn-sm" onClick={() => setModal({ kind: 'distill', accountId: a.id, username: a.username, currentProviderId: a.distill_provider_id })}>
                        Set Provider
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {modal?.kind === 'create' && (
        <CreateAccountModal
          onClose={() => setModal(null)}
          onDone={() => { setModal(null); load(); }}
        />
      )}
      {modal?.kind === 'reset' && (
        <ResetPasswordModal
          accountId={modal.accountId}
          username={modal.username}
          onClose={() => setModal(null)}
          onDone={() => setModal(null)}
        />
      )}
      {modal?.kind === 'distill' && (
        <SetDistillProviderModal
          accountId={modal.accountId}
          username={modal.username}
          currentProviderId={modal.currentProviderId}
          providers={providers}
          onClose={() => setModal(null)}
          onDone={() => { setModal(null); load(); }}
        />
      )}
    </div>
  );
}

function CreateAccountModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const submit = () => {
    if (!username || !password || !displayName) { setErr('所有字段必填'); return; }
    setBusy(true);
    api.createAccount({ username, password, display_name: displayName })
      .then(onDone)
      .catch(e => { setErr(e.message); setBusy(false); });
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-title">New Account</div>
        <div className="form-row">
          <label className="form-label">Username</label>
          <input className="input" value={username} onChange={e => setUsername(e.target.value)} autoFocus />
        </div>
        <div className="form-row">
          <label className="form-label">Display Name</label>
          <input className="input" value={displayName} onChange={e => setDisplayName(e.target.value)} />
        </div>
        <div className="form-row">
          <label className="form-label">Password</label>
          <input className="input" type="password" value={password} onChange={e => setPassword(e.target.value)} />
        </div>
        {err && <div style={{ color: 'var(--danger)', fontSize: 12, marginTop: 4 }}>{err}</div>}
        <div className="form-actions">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={busy}>
            {busy ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}

function ResetPasswordModal({ accountId, username, onClose, onDone }: {
  accountId: string; username: string; onClose: () => void; onDone: () => void;
}) {
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const submit = () => {
    if (!password) { setErr('密码不能为空'); return; }
    setBusy(true);
    api.resetPassword(accountId, password)
      .then(onDone)
      .catch(e => { setErr(e.message); setBusy(false); });
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-title">Reset Password — {username}</div>
        <div className="form-row">
          <label className="form-label">New Password</label>
          <input className="input" type="password" value={password} onChange={e => setPassword(e.target.value)} autoFocus />
        </div>
        {err && <div style={{ color: 'var(--danger)', fontSize: 12, marginTop: 4 }}>{err}</div>}
        <div className="form-actions">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={busy}>
            {busy ? 'Saving…' : 'Reset'}
          </button>
        </div>
      </div>
    </div>
  );
}

function SetDistillProviderModal({ accountId, username, currentProviderId, providers, onClose, onDone }: {
  accountId: string; username: string; currentProviderId: string;
  providers: api.Provider[]; onClose: () => void; onDone: () => void;
}) {
  const [selected, setSelected] = useState(currentProviderId);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const submit = () => {
    setBusy(true);
    api.setDistillProvider(accountId, selected)
      .then(onDone)
      .catch(e => { setErr(e.message); setBusy(false); });
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-title">Set Distill Provider — {username}</div>
        <div className="form-row">
          <label className="form-label">Provider</label>
          <select className="select" value={selected} onChange={e => setSelected(e.target.value)}>
            {providers.map(p => (
              <option key={p.id} value={p.id}>{p.name} ({p.model})</option>
            ))}
          </select>
        </div>
        {err && <div style={{ color: 'var(--danger)', fontSize: 12, marginTop: 4 }}>{err}</div>}
        <div className="form-actions">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
