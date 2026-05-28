import { useEffect, useState } from 'react';
import * as api from '../api.ts';

type Modal = { kind: 'setProvider'; conv: api.Conversation };

export function ConversationsPage() {
  const [conversations, setConversations] = useState<api.Conversation[]>([]);
  const [accounts, setAccounts] = useState<api.Account[]>([]);
  const [providers, setProviders] = useState<api.Provider[]>([]);
  const [filterAccount, setFilterAccount] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [modal, setModal] = useState<Modal | null>(null);

  const loadMeta = () =>
    Promise.all([api.getAccounts(), api.getProviders()])
      .then(([a, p]) => { setAccounts(a); setProviders(p); });

  const fetchConvs = (acct: string) =>
    api.getConversations(acct || undefined)
      .then(c => { setConversations(c); setError(''); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));

  const loadConvs = (acct: string) => { setLoading(true); fetchConvs(acct); };

  useEffect(() => {
    loadMeta().catch(e => setError(e.message));
    fetchConvs('');
  }, []);

  const applyFilter = (v: string) => {
    setFilterAccount(v);
    loadConvs(v);
  };

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>Conversations</h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <label style={{ color: 'var(--ink-3)', fontSize: 12 }}>Account</label>
          <select
            className="select"
            style={{ width: 180 }}
            value={filterAccount}
            onChange={e => applyFilter(e.target.value)}
          >
            <option value="">All</option>
            {accounts.map(a => <option key={a.id} value={a.username}>{a.username}</option>)}
          </select>
        </div>
      </div>

      {error && <div style={{ color: 'var(--danger)', marginBottom: 12, fontSize: 12 }}>{error}</div>}

      <div style={{ background: 'var(--bg-base)', border: '1px solid var(--line-subtle)', borderRadius: 'var(--r-lg)', overflow: 'hidden' }}>
        {loading ? (
          <div style={{ padding: 24, color: 'var(--ink-4)', textAlign: 'center' }}>Loading…</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Account / Inbox</th>
                <th>Kind</th>
                <th>Name</th>
                <th>Persona</th>
                <th>Provider</th>
                <th>Policy</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {conversations.length === 0 && (
                <tr><td colSpan={8} style={{ textAlign: 'center', color: 'var(--ink-4)', padding: 24 }}>No conversations</td></tr>
              )}
              {conversations.map(c => (
                <tr key={c.id}>
                  <td>
                    <div style={{ fontWeight: 500 }}>{c.account_username}</div>
                    <div className="mono" style={{ color: 'var(--ink-4)', marginTop: 2 }}>
                      {c.inbox_platform}:{c.inbox_display_name}
                    </div>
                  </td>
                  <td><span className="chip">{c.kind}</span></td>
                  <td style={{ color: 'var(--ink-2)', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {c.display_name}
                  </td>
                  <td style={{ color: 'var(--ink-3)', fontSize: 12 }}>
                    {c.persona_name ?? <span style={{ color: 'var(--ink-4)' }}>—</span>}
                  </td>
                  <td style={{ color: 'var(--ink-2)', fontSize: 12 }}>{c.provider_name}</td>
                  <td>
                    <span className={`chip ${c.reply_policy === 'autoreply' ? 'active' : ''}`}>
                      {c.reply_policy}
                    </span>
                  </td>
                  <td>
                    <span className={`chip ${c.status === 'active' ? 'active' : ''}`}>{c.status}</span>
                  </td>
                  <td>
                    <button className="btn btn-ghost btn-sm" onClick={() => setModal({ kind: 'setProvider', conv: c })}>
                      Set Provider
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {modal?.kind === 'setProvider' && (
        <SetProviderModal
          conv={modal.conv}
          providers={providers}
          onClose={() => setModal(null)}
          onDone={() => { setModal(null); loadConvs(filterAccount); }}
        />
      )}
    </div>
  );
}

function SetProviderModal({ conv, providers, onClose, onDone }: {
  conv: api.Conversation;
  providers: api.Provider[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [selected, setSelected] = useState(conv.provider_id);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const submit = () => {
    setBusy(true);
    api.setConversationProvider(conv.id, selected)
      .then(onDone)
      .catch(e => { setErr(e.message); setBusy(false); });
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-title">Set Provider</div>
        <p style={{ color: 'var(--ink-3)', margin: '0 0 16px', fontSize: 12 }}>
          {conv.account_username} / {conv.inbox_platform}:{conv.inbox_display_name} / {conv.display_name}
        </p>
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
