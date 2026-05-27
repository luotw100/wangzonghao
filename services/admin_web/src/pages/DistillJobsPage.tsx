import { useEffect, useMemo, useState } from 'react';
import * as api from '../api.ts';
import { LlmTraceDrawer } from './LlmTraceDrawer.tsx';

export function DistillJobsPage() {
  const [accounts, setAccounts] = useState<api.Account[]>([]);
  const [jobs, setJobs] = useState<api.DistillJobSummary[]>([]);
  const [accountId, setAccountId] = useState('');
  const [activeJob, setActiveJob] = useState<api.DistillJobDetail | null>(null);
  const [error, setError] = useState('');
  const [drawerLog, setDrawerLog] = useState<number | null>(null);

  useEffect(() => {
    api.getAccounts().then(setAccounts).catch(e => setError(e.message));
  }, []);

  useEffect(() => {
    api.getDistillJobs(accountId || undefined).then(setJobs).catch(e => setError(e.message));
  }, [accountId]);

  const openJob = (id: string) => {
    api.getDistillJob(id).then(setActiveJob).catch(e => setError(e.message));
  };

  const foldsByConv = useMemo(() => {
    if (!activeJob) return [];
    const groups = new Map<string, api.DistillFoldRow[]>();
    for (const f of activeJob.folds) {
      const key = `${f.conversation_id}::${f.conversation_peer_display}`;
      const arr = groups.get(key) || [];
      arr.push(f);
      groups.set(key, arr);
    }
    return Array.from(groups.entries()).map(([k, v]) => ({ key: k, peer: v[0].conversation_peer_display, folds: v }));
  }, [activeJob]);

  return (
    <div>
      <h1 style={{ margin: 0, fontSize: 18, fontWeight: 600, marginBottom: 16 }}>Distill Jobs</h1>

      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <select className="input" value={accountId} onChange={e => setAccountId(e.target.value)}>
          <option value="">所有账号</option>
          {accounts.map(a => <option key={a.id} value={a.id}>{a.username}</option>)}
        </select>
      </div>

      {error && <div style={{ color: 'var(--danger)', marginBottom: 8, fontSize: 12 }}>{error}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.5fr', gap: 16 }}>
        <div style={{ background: 'var(--bg-base)', border: '1px solid var(--line-subtle)', borderRadius: 'var(--r-lg)', overflow: 'hidden' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>账号</th>
                <th>目标人设</th>
                <th>对话数</th>
                <th>Provider</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {jobs.length === 0 && <tr><td colSpan={6} style={{ textAlign: 'center', color: 'var(--ink-4)', padding: 16 }}>无任务</td></tr>}
              {jobs.map(j => (
                <tr key={j.id} onClick={() => openJob(j.id)} style={{ cursor: 'pointer', background: activeJob?.id === j.id ? 'var(--bg-raised)' : undefined }}>
                  <td style={{ fontSize: 11 }}>{new Date(j.created_at).toLocaleString()}</td>
                  <td>{j.account_username}</td>
                  <td>{j.persona_name || <i style={{ color: 'var(--ink-4)' }}>预览（不写回）</i>}</td>
                  <td>{j.conversation_count}</td>
                  <td style={{ fontSize: 11 }}>{j.provider_name}</td>
                  <td>{j.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div style={{ background: 'var(--bg-base)', border: '1px solid var(--line-subtle)', borderRadius: 'var(--r-lg)', padding: 12, minHeight: 200 }}>
          {!activeJob ? (
            <div style={{ color: 'var(--ink-4)', textAlign: 'center', padding: 24 }}>点击左侧任务查看 fold 详情</div>
          ) : (
            <>
              <div style={{ fontSize: 13, marginBottom: 8 }}>
                <b>{activeJob.account_username}</b> → {activeJob.persona_name || '(预览)'} · {activeJob.status}
                {activeJob.error_message && (
                  <div style={{ color: 'var(--danger)', fontSize: 12, marginTop: 4 }}>{activeJob.error_message}</div>
                )}
              </div>
              {foldsByConv.map(group => (
                <div key={group.key} style={{ marginBottom: 12, border: '1px solid var(--line-subtle)', borderRadius: 6 }}>
                  <div style={{ padding: '6px 10px', background: 'var(--bg-raised)', fontSize: 12, fontWeight: 500 }}>
                    {group.peer}
                  </div>
                  <table className="data-table" style={{ margin: 0 }}>
                    <thead>
                      <tr>
                        <th>Window</th>
                        <th>延迟</th>
                        <th>Persona 改？</th>
                        <th>Card 改？</th>
                        <th>状态</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.folds.map(f => (
                        <tr key={f.log_id}>
                          <td>{f.window_index}/{f.windows_total}</td>
                          <td>{f.latency_ms != null ? `${f.latency_ms}ms` : '-'}</td>
                          <td>{f.persona_changed ? '✓' : '·'}</td>
                          <td>{f.card_changed ? '✓' : '·'}</td>
                          <td>{f.is_error ? <span style={{ color: 'var(--danger)' }}>✗</span> : 'ok'}</td>
                          <td><button className="btn btn-sm" onClick={() => setDrawerLog(f.log_id)}>查看</button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </>
          )}
        </div>
      </div>

      {drawerLog != null && <LlmTraceDrawer logId={drawerLog} onClose={() => setDrawerLog(null)} />}
    </div>
  );
}
