import { useEffect, useState } from 'react';
import * as api from '../api.ts';
import { LlmTraceDrawer } from './LlmTraceDrawer.tsx';

export function LlmLogsPage() {
  const [accounts, setAccounts] = useState<api.Account[]>([]);
  const [logs, setLogs] = useState<api.LlmLogSummary[]>([]);
  const [accountId, setAccountId] = useState('');
  const [purpose, setPurpose] = useState('');
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [drawerLog, setDrawerLog] = useState<number | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api.getAccounts().then(setAccounts).catch(e => setError(e.message));
  }, []);

  const load = () => {
    api.getLlmLogs({
      account_id: accountId || undefined,
      purpose: purpose || undefined,
      is_error: errorsOnly ? true : undefined,
      limit: 200,
    }).then(setLogs).catch(e => setError(e.message));
  };

  useEffect(load, [accountId, purpose, errorsOnly]);

  return (
    <div>
      <h1 style={{ margin: 0, fontSize: 18, fontWeight: 600, marginBottom: 16 }}>LLM Logs</h1>

      <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
        <select className="input" value={accountId} onChange={e => setAccountId(e.target.value)}>
          <option value="">所有账号</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{a.username}</option>)}
        </select>
        <select className="input" value={purpose} onChange={e => setPurpose(e.target.value)}>
          <option value="">所有 purpose</option>
          <option value="reply">reply</option>
          <option value="distill">distill</option>
        </select>
        <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
          <input type="checkbox" checked={errorsOnly} onChange={e => setErrorsOnly(e.target.checked)} />
          仅看错误
        </label>
        <button className="btn btn-sm" onClick={load}>Refresh</button>
      </div>

      {error && <div style={{ color: 'var(--danger)', marginBottom: 8, fontSize: 12 }}>{error}</div>}

      <div style={{ background: 'var(--bg-base)', border: '1px solid var(--line-subtle)', borderRadius: 'var(--r-lg)', overflow: 'hidden' }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>用途</th>
              <th>账号</th>
              <th>人设</th>
              <th>对端</th>
              <th>模型</th>
              <th>延迟</th>
              <th>Tokens (in/out)</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {logs.length === 0 && (
              <tr><td colSpan={9} style={{ textAlign: 'center', color: 'var(--ink-4)', padding: 24 }}>无记录</td></tr>
            )}
            {logs.map(l => (
              <tr key={l.id} style={{ background: l.is_error ? 'rgba(220, 60, 60, 0.05)' : undefined }}>
                <td style={{ fontSize: 11 }}>{new Date(l.created_at).toLocaleString()}</td>
                <td>
                  {l.purpose}
                  {l.purpose === 'distill' && l.window_index != null && (
                    <span style={{ color: 'var(--ink-4)', fontSize: 11 }}> · w{l.window_index}/{l.windows_total ?? '?'}</span>
                  )}
                  {l.is_error && <span style={{ color: 'var(--danger)', marginLeft: 6 }}>✗</span>}
                </td>
                <td>{l.account_username || '-'}</td>
                <td>{l.persona_name || '-'}</td>
                <td>{l.conversation_peer_display || '-'}</td>
                <td style={{ fontSize: 11 }}>{l.model || '-'}</td>
                <td>{l.latency_ms != null ? `${l.latency_ms}ms` : '-'}</td>
                <td style={{ fontSize: 11 }}>{l.prompt_tokens ?? '-'} / {l.completion_tokens ?? '-'}</td>
                <td><button className="btn btn-sm" onClick={() => setDrawerLog(l.id)}>查看</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {drawerLog != null && <LlmTraceDrawer logId={drawerLog} onClose={() => setDrawerLog(null)} />}
    </div>
  );
}
