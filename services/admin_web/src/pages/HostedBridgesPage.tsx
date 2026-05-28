import { useEffect, useState } from 'react';
import * as api from '../api.ts';

const STATUS_CHIP: Record<api.HostedBridge['status'], string> = {
  running: 'active',
  starting: 'brass',
  stopped: 'disabled',
  auth_error: 'danger',
  crashed: 'danger',
};

export function HostedBridgesPage() {
  const [rows, setRows] = useState<api.HostedBridge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const fetchData = () =>
    api.getHostedBridges()
      .then(r => { setRows(r); setError(''); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));

  const load = () => { setLoading(true); fetchData(); };

  useEffect(() => { fetchData(); }, []);

  const act = async (accountId: string, op: 'start' | 'stop') => {
    setBusy(b => ({ ...b, [accountId]: true }));
    setError('');
    try {
      const fn = op === 'start' ? api.startHostedBridge : api.stopHostedBridge;
      const updated = await fn(accountId);
      setRows(rs => rs.map(r => r.account_id === accountId ? updated : r));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(b => ({ ...b, [accountId]: false }));
    }
  };

  const restart = async (accountId: string) => {
    setBusy(b => ({ ...b, [accountId]: true }));
    setError('');
    try {
      await api.stopHostedBridge(accountId);
      const updated = await api.startHostedBridge(accountId);
      setRows(rs => rs.map(r => r.account_id === accountId ? updated : r));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(b => ({ ...b, [accountId]: false }));
    }
  };

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>Hosted Bridges</h1>
          <div style={{ marginTop: 4, fontSize: 12, color: 'var(--ink-4)' }}>
            Cloud-hosted chat-only bridges for dogfood. Lifecycle is fully manual — start / stop / restart at will.
          </div>
        </div>
        <button className="btn btn-ghost btn-sm" onClick={load}>Refresh</button>
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
                <th>Machine ID</th>
                <th>Last Started</th>
                <th>Last Error</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr><td colSpan={7} style={{ textAlign: 'center', color: 'var(--ink-4)', padding: 24 }}>No accounts</td></tr>
              )}
              {rows.map(r => {
                const isBusy = !!busy[r.account_id];
                const running = r.status === 'running' || r.status === 'starting';
                return (
                  <tr key={r.account_id}>
                    <td style={{ fontWeight: 500 }}>{r.username}</td>
                    <td style={{ color: 'var(--ink-2)' }}>{r.display_name}</td>
                    <td><span className={`chip ${STATUS_CHIP[r.status]}`}>{r.status}</span></td>
                    <td className="mono">{r.machine_id || '—'}</td>
                    <td className="mono" style={{ color: 'var(--ink-3)' }}>
                      {r.last_started_at ? r.last_started_at.replace('T', ' ').slice(0, 19) : '—'}
                    </td>
                    <td style={{ color: r.last_error ? 'var(--danger)' : 'var(--ink-4)', fontSize: 12, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.last_error}>
                      {r.last_error || '—'}
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                        {running ? (
                          <>
                            <button className="btn btn-ghost btn-sm" disabled={isBusy} onClick={() => restart(r.account_id)}>
                              Restart
                            </button>
                            <button className="btn btn-ghost btn-sm" disabled={isBusy} onClick={() => act(r.account_id, 'stop')}>
                              Stop
                            </button>
                          </>
                        ) : (
                          <button className="btn btn-primary btn-sm" disabled={isBusy} onClick={() => act(r.account_id, 'start')}>
                            Start
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
