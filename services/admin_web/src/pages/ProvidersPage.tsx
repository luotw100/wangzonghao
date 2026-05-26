import { useEffect, useState } from 'react';
import * as api from '../api.ts';

type Modal =
  | { kind: 'create' }
  | { kind: 'edit'; provider: api.Provider }
  | { kind: 'delete'; provider: api.Provider };

export function ProvidersPage() {
  const [providers, setProviders] = useState<api.Provider[]>([]);
  const [allowedUrls, setAllowedUrls] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [modal, setModal] = useState<Modal | null>(null);

  const load = () => {
    setLoading(true);
    Promise.all([api.getProviders(), api.getAllowedBaseUrls()])
      .then(([p, urls]) => { setProviders(p); setAllowedUrls(urls); setError(''); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>Providers</h1>
        <button className="btn btn-primary btn-sm" onClick={() => setModal({ kind: 'create' })}>
          + New Provider
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
                <th>Name</th>
                <th>Base URL</th>
                <th>Model</th>
                <th>API Key</th>
                <th>Updated</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {providers.length === 0 && (
                <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--ink-4)', padding: 24 }}>No providers</td></tr>
              )}
              {providers.map(p => (
                <tr key={p.id}>
                  <td style={{ fontWeight: 500 }}>{p.name}</td>
                  <td className="mono" style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {p.base_url}
                  </td>
                  <td className="mono">{p.model}</td>
                  <td className="mono">{p.api_key_masked || <span style={{ color: 'var(--ink-4)' }}>—</span>}</td>
                  <td className="mono">{p.updated_at.slice(0, 10)}</td>
                  <td>
                    <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                      <button className="btn btn-ghost btn-sm" onClick={() => setModal({ kind: 'edit', provider: p })}>
                        Edit
                      </button>
                      <button className="btn btn-danger btn-sm" onClick={() => setModal({ kind: 'delete', provider: p })}>
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {(modal?.kind === 'create' || modal?.kind === 'edit') && (
        <ProviderFormModal
          provider={modal.kind === 'edit' ? modal.provider : null}
          allowedUrls={allowedUrls}
          onClose={() => setModal(null)}
          onDone={() => { setModal(null); load(); }}
        />
      )}
      {modal?.kind === 'delete' && (
        <DeleteProviderModal
          provider={modal.provider}
          onClose={() => setModal(null)}
          onDone={() => { setModal(null); load(); }}
        />
      )}
    </div>
  );
}

function ProviderFormModal({ provider, allowedUrls, onClose, onDone }: {
  provider: api.Provider | null;
  allowedUrls: string[];
  onClose: () => void;
  onDone: () => void;
}) {
  const editing = provider !== null;
  const [name, setName] = useState(provider?.name ?? '');
  const [baseUrl, setBaseUrl] = useState(provider?.base_url ?? (allowedUrls[0] ?? ''));
  const [model, setModel] = useState(provider?.model ?? '');
  const [apiKey, setApiKey] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const submit = () => {
    if (!name || !baseUrl || !model) { setErr('Name、Base URL、Model 必填'); return; }
    setBusy(true);
    const p = editing
      ? api.updateProvider(provider.id, { name, base_url: baseUrl, model, ...(apiKey ? { api_key: apiKey } : {}) })
      : api.createProvider({ name, base_url: baseUrl, model, ...(apiKey ? { api_key: apiKey } : {}) });
    p.then(onDone).catch(e => { setErr(e.message); setBusy(false); });
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-title">{editing ? `Edit Provider — ${provider.name}` : 'New Provider'}</div>
        <div className="form-row">
          <label className="form-label">Name</label>
          <input className="input" value={name} onChange={e => setName(e.target.value)} autoFocus />
        </div>
        <div className="form-row">
          <label className="form-label">Base URL</label>
          <select className="select" value={baseUrl} onChange={e => setBaseUrl(e.target.value)}>
            {allowedUrls.map(u => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
        <div className="form-row">
          <label className="form-label">Model</label>
          <input className="input" value={model} onChange={e => setModel(e.target.value)} placeholder="e.g. gpt-4o" />
        </div>
        <div className="form-row">
          <label className="form-label">
            API Key{editing && <span style={{ color: 'var(--ink-4)', fontWeight: 400, marginLeft: 6 }}>(留空保持不变)</span>}
          </label>
          <input className="input" type="password" value={apiKey} onChange={e => setApiKey(e.target.value)}
            placeholder={editing ? provider.api_key_masked || '—' : ''} />
        </div>
        {err && <div style={{ color: 'var(--danger)', fontSize: 12, marginTop: 4 }}>{err}</div>}
        <div className="form-actions">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={busy}>
            {busy ? 'Saving…' : editing ? 'Save' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}

function DeleteProviderModal({ provider, onClose, onDone }: {
  provider: api.Provider; onClose: () => void; onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const confirm = () => {
    setBusy(true);
    api.deleteProvider(provider.id)
      .then(onDone)
      .catch(e => { setErr(e.message); setBusy(false); });
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-title">Delete Provider</div>
        <p style={{ color: 'var(--ink-2)', margin: '0 0 8px', lineHeight: 1.6 }}>
          Delete <strong style={{ color: 'var(--ink-1)' }}>{provider.name}</strong>?
        </p>
        <p style={{ color: 'var(--ink-3)', margin: 0, fontSize: 12, lineHeight: 1.6 }}>
          If any accounts or conversations still reference this provider, the operation will be rejected.
        </p>
        {err && <div style={{ color: 'var(--danger)', fontSize: 12, marginTop: 8 }}>{err}</div>}
        <div className="form-actions">
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-danger" onClick={confirm} disabled={busy}>
            {busy ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  );
}
