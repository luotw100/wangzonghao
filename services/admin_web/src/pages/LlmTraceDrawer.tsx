import { useEffect, useState } from 'react';
import * as api from '../api.ts';

/** A right-side drawer that loads + shows one LlmLog row.
 *
 * Used from ChatsPage (click on a self message), LlmLogsPage (click row),
 * DistillJobsPage (click fold row), PersonaTimelinePage (click revision).
 */
export function LlmTraceDrawer({ logId, onClose }: { logId: number; onClose: () => void }) {
  const [log, setLog] = useState<api.LlmLogDetail | null>(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<'request' | 'snapshot' | 'response' | 'meta'>('request');

  useEffect(() => {
    // Reset stale detail while the new logId loads so prior content doesn't flash.
    /* eslint-disable react-hooks/set-state-in-effect */
    setLog(null);
    setError('');
    /* eslint-enable react-hooks/set-state-in-effect */
    api.getLlmLog(logId).then(setLog).catch(e => setError(e.message));
  }, [logId]);

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.32)',
        zIndex: 1000, display: 'flex', justifyContent: 'flex-end',
      }}
      onClick={onClose}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: 'min(880px, 96vw)', height: '100vh', background: 'var(--bg-base)',
          borderLeft: '1px solid var(--line-subtle)', display: 'flex', flexDirection: 'column',
        }}
      >
        <div style={{
          padding: '14px 20px', borderBottom: '1px solid var(--line-subtle)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>LLM Trace #{logId}</div>
          <button className="btn btn-sm" onClick={onClose}>Close</button>
        </div>

        {error && <div style={{ color: 'var(--danger)', padding: 16, fontSize: 12 }}>{error}</div>}
        {!log && !error && <div style={{ padding: 24, color: 'var(--ink-4)' }}>Loading…</div>}

        {log && (
          <>
            <div style={{ padding: '12px 20px', borderBottom: '1px solid var(--line-subtle)', fontSize: 12, color: 'var(--ink-3)', lineHeight: 1.7 }}>
              <div><b style={{ color: 'var(--ink-1)' }}>Purpose</b> {log.purpose}{log.is_error ? ' · ⚠ ERROR' : ''}</div>
              <div><b style={{ color: 'var(--ink-1)' }}>Account</b> {log.account_username || '-'} · <b>Inbox</b> {log.inbox_display_name || '-'}</div>
              <div><b style={{ color: 'var(--ink-1)' }}>Persona</b> {log.persona_name || '-'} · <b>Peer</b> {log.conversation_peer_display || '-'}</div>
              <div>
                <b style={{ color: 'var(--ink-1)' }}>Model</b> {log.model || '-'}
                {' · '}
                <b>Latency</b> {log.latency_ms != null ? `${log.latency_ms} ms` : '-'}
                {' · '}
                <b>Tokens</b> {log.prompt_tokens ?? '-'} / {log.completion_tokens ?? '-'}
                {log.window_index != null && (<> {' · '}<b>Window</b> {log.window_index}/{log.windows_total ?? '?'}</>)}
              </div>
              <div><b style={{ color: 'var(--ink-1)' }}>Time</b> {new Date(log.created_at).toLocaleString()}</div>
            </div>

            <div style={{ display: 'flex', gap: 4, padding: '8px 20px 0', borderBottom: '1px solid var(--line-subtle)' }}>
              {(['request', 'snapshot', 'response', 'meta'] as const).map(t => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className="btn btn-sm"
                  style={{
                    background: tab === t ? 'var(--bg-raised)' : 'transparent',
                    borderColor: tab === t ? 'var(--brass)' : 'transparent',
                  }}
                >
                  {t === 'request' ? 'Request' : t === 'snapshot' ? 'Persona / Card 快照' : t === 'response' ? 'Response' : 'IDs'}
                </button>
              ))}
            </div>

            <div style={{ flex: 1, overflow: 'auto', padding: 20 }}>
              {tab === 'request' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {log.request_messages.map((m, i) => (
                    <div key={i} style={{ border: '1px solid var(--line-subtle)', borderRadius: 6 }}>
                      <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--line-subtle)', fontSize: 11, color: 'var(--ink-3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                        {m.role}
                      </div>
                      <pre style={{ margin: 0, padding: 10, fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 320, overflow: 'auto' }}>{m.content}</pre>
                    </div>
                  ))}
                </div>
              )}
              {tab === 'snapshot' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  <SnapshotBlock title="Persona md (输入)" content={log.persona_md_snapshot} />
                  {log.persona_md_after != null && (
                    <SnapshotBlock title="Persona md (fold 后)" content={log.persona_md_after} highlight />
                  )}
                  <SnapshotBlock title="Card md (输入)" content={log.card_md_snapshot} />
                  {log.card_md_after != null && (
                    <SnapshotBlock title="Card md (fold 后)" content={log.card_md_after} highlight />
                  )}
                </div>
              )}
              {tab === 'response' && (
                <pre style={{ margin: 0, fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{log.response_raw}</pre>
              )}
              {tab === 'meta' && (
                <div style={{ fontSize: 12, color: 'var(--ink-3)', lineHeight: 1.8, fontFamily: 'var(--f-mono, monospace)' }}>
                  <div>log_id: {log.id}</div>
                  <div>conversation_id: {log.conversation_id || '-'}</div>
                  <div>distill_job_id: {log.distill_job_id || '-'}</div>
                  <div>outbound_message_id: {log.outbound_message_id ?? '-'}</div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function SnapshotBlock({ title, content, highlight }: { title: string; content: string | null; highlight?: boolean }) {
  return (
    <div style={{ border: '1px solid var(--line-subtle)', borderRadius: 6, background: highlight ? 'var(--bg-raised)' : undefined }}>
      <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--line-subtle)', fontSize: 11, color: 'var(--ink-3)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        {title}
      </div>
      <pre style={{ margin: 0, padding: 10, fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 360, overflow: 'auto' }}>
        {content == null || content === '' ? '(空)' : content}
      </pre>
    </div>
  );
}
