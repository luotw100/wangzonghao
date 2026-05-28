import { useEffect, useState } from 'react';
import * as api from '../api.ts';
import { LlmTraceDrawer } from './LlmTraceDrawer.tsx';

export function PersonaTimelinePage() {
  const [personas, setPersonas] = useState<api.PersonaListItem[]>([]);
  const [personaId, setPersonaId] = useState('');
  const [entries, setEntries] = useState<api.PersonaTimelineEntry[]>([]);
  const [error, setError] = useState('');
  const [drawerLog, setDrawerLog] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    api.getPersonas().then(setPersonas).catch(e => setError(e.message));
  }, []);

  useEffect(() => {
    if (!personaId) return;
    api.getPersonaTimeline(personaId).then(setEntries).catch(e => setError(e.message));
  }, [personaId]);

  return (
    <div>
      <h1 style={{ margin: 0, fontSize: 18, fontWeight: 600, marginBottom: 16 }}>Persona Timeline</h1>

      <div style={{ marginBottom: 12 }}>
        <select className="input" value={personaId} onChange={e => setPersonaId(e.target.value)} style={{ minWidth: 320 }}>
          <option value="">— 选择 persona —</option>
          {personas.map(p => (
            <option key={p.id} value={p.id}>{p.account_username} / {p.name}</option>
          ))}
        </select>
      </div>

      {error && <div style={{ color: 'var(--danger)', marginBottom: 8, fontSize: 12 }}>{error}</div>}

      {!personaId ? (
        <div style={{ color: 'var(--ink-4)' }}>选个 persona 看它怎么被一步步蒸馏成现在这样</div>
      ) : entries.length === 0 ? (
        <div style={{ color: 'var(--ink-4)' }}>这个 persona 还没有蒸馏记录</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {entries.map(e => (
            <div key={e.log_id} style={{ border: '1px solid var(--line-subtle)', borderRadius: 6, background: 'var(--bg-base)' }}>
              <div
                onClick={() => setExpanded(expanded === e.log_id ? null : e.log_id)}
                style={{ padding: '8px 12px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
              >
                <div style={{ fontSize: 12 }}>
                  <b>{new Date(e.created_at).toLocaleString()}</b>
                  <span style={{ color: 'var(--ink-3)', marginLeft: 8 }}>
                    来自 {e.conversation_peer_display || '(已删除会话)'} · w{e.window_index}/{e.windows_total}
                  </span>
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button className="btn btn-sm" onClick={(ev) => { ev.stopPropagation(); setDrawerLog(e.log_id); }}>查看 Trace</button>
                </div>
              </div>
              {expanded === e.log_id && (
                <div style={{ borderTop: '1px solid var(--line-subtle)', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, padding: 10 }}>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--ink-3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>之前</div>
                    <pre style={{ margin: 0, fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 320, overflow: 'auto', padding: 8, background: 'var(--bg-raised)', borderRadius: 4 }}>{e.persona_md_before || '(空)'}</pre>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: 'var(--ink-3)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>之后</div>
                    <pre style={{ margin: 0, fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 320, overflow: 'auto', padding: 8, background: 'var(--bg-raised)', borderRadius: 4 }}>{e.persona_md_after || '(空)'}</pre>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {drawerLog != null && <LlmTraceDrawer logId={drawerLog} onClose={() => setDrawerLog(null)} />}
    </div>
  );
}
