import { useEffect, useMemo, useState } from 'react';
import * as api from '../api.ts';
import { LlmTraceDrawer } from './LlmTraceDrawer.tsx';

export function ChatsPage() {
  const [accounts, setAccounts] = useState<api.Account[]>([]);
  const [accountId, setAccountId] = useState<string>('');
  const [convs, setConvs] = useState<api.ChatConversation[]>([]);
  const [activeConv, setActiveConv] = useState<api.ChatConversation | null>(null);
  const [messages, setMessages] = useState<api.ChatMessage[]>([]);
  const [error, setError] = useState('');
  const [drawerLog, setDrawerLog] = useState<number | null>(null);

  useEffect(() => {
    api.getAccounts().then(setAccounts).catch(e => setError(e.message));
  }, []);

  useEffect(() => {
    setActiveConv(null);
    setMessages([]);
    if (!accountId) { setConvs([]); return; }
    api.getChats(accountId).then(setConvs).catch(e => setError(e.message));
  }, [accountId]);

  useEffect(() => {
    if (!activeConv) { setMessages([]); return; }
    api.getChatMessages(activeConv.id, { limit: 300 })
      .then(setMessages)
      .catch(e => setError(e.message));
  }, [activeConv?.id]);

  const convsByInbox = useMemo(() => {
    const groups: Record<string, api.ChatConversation[]> = {};
    for (const c of convs) {
      const key = `${c.inbox_display_name} [${c.inbox_platform}]`;
      (groups[key] ||= []).push(c);
    }
    return groups;
  }, [convs]);

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 56px)', gap: 16 }}>
      {/* Left: account picker + conv list */}
      <div style={{ width: 320, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h1 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>Chats</h1>
        <select
          className="input"
          value={accountId}
          onChange={e => setAccountId(e.target.value)}
        >
          <option value="">— 选择账号 —</option>
          {accounts.map(a => (
            <option key={a.id} value={a.id}>{a.username} ({a.display_name})</option>
          ))}
        </select>

        <div style={{ flex: 1, overflow: 'auto', border: '1px solid var(--line-subtle)', borderRadius: 'var(--r-lg)', background: 'var(--bg-base)' }}>
          {Object.keys(convsByInbox).length === 0 && (
            <div style={{ padding: 16, color: 'var(--ink-4)', fontSize: 12 }}>选个账号看看吧</div>
          )}
          {Object.entries(convsByInbox).map(([inbox, list]) => (
            <div key={inbox}>
              <div style={{ padding: '8px 12px', fontSize: 11, color: 'var(--ink-3)', textTransform: 'uppercase', letterSpacing: '0.05em', background: 'var(--bg-raised)' }}>{inbox}</div>
              {list.map(c => (
                <button
                  key={c.id}
                  onClick={() => setActiveConv(c)}
                  style={{
                    display: 'block', width: '100%', textAlign: 'left',
                    padding: '8px 12px',
                    border: 'none',
                    background: activeConv?.id === c.id ? 'var(--bg-raised)' : 'transparent',
                    borderLeft: activeConv?.id === c.id ? '2px solid var(--brass)' : '2px solid transparent',
                    cursor: 'pointer', fontSize: 13,
                  }}
                >
                  <div style={{ fontWeight: 500 }}>{c.peer_display}</div>
                  <div style={{ fontSize: 11, color: 'var(--ink-3)' }}>
                    {c.kind === 'group' ? '群' : 'DM'} · {c.persona_name || '无人设'} · {c.takeover ? '已接管' : '未接管'}
                  </div>
                </button>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Right: messages */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {error && <div style={{ color: 'var(--danger)', marginBottom: 8, fontSize: 12 }}>{error}</div>}
        {!activeConv ? (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-4)' }}>
            选个会话查看消息
          </div>
        ) : (
          <>
            <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--line-subtle)', fontSize: 13 }}>
              <b>{activeConv.peer_display}</b>
              <span style={{ color: 'var(--ink-3)', marginLeft: 8 }}>
                · {activeConv.inbox_display_name} [{activeConv.inbox_platform}] · 人设 {activeConv.persona_name || '-'}
              </span>
            </div>
            <div style={{ flex: 1, overflow: 'auto', padding: 12, background: 'var(--bg-base)', border: '1px solid var(--line-subtle)', borderTop: 'none' }}>
              {messages.length === 0 && (
                <div style={{ color: 'var(--ink-4)', fontSize: 12 }}>没有消息</div>
              )}
              {messages.map(m => (
                <div key={m.id} style={{
                  display: 'flex', flexDirection: m.direction === 'self' ? 'row-reverse' : 'row',
                  marginBottom: 4, alignItems: 'flex-start', gap: 6,
                }}>
                  <div style={{
                    maxWidth: '72%',
                    padding: '4px 8px',
                    borderRadius: 6,
                    background: m.direction === 'self' ? 'var(--brass-soft, #f6edd6)' : 'var(--bg-raised)',
                    fontSize: 13, lineHeight: 1.45,
                  }}>
                    <div style={{ fontSize: 10, color: 'var(--ink-4)', marginBottom: 2 }}>
                      {m.sender_display} · {fmtTs(m.ts)}
                    </div>
                    <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                      {m.msg_type === 'text' ? m.content : `[${m.msg_type}]`}
                    </div>
                  </div>
                  {m.direction === 'self' && m.llm_log_id != null && (
                    <button
                      className="btn btn-sm"
                      onClick={() => setDrawerLog(m.llm_log_id!)}
                      title="查看 LLM 调用"
                      style={{ padding: '2px 6px', fontSize: 11 }}
                    >
                      🧠
                    </button>
                  )}
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {drawerLog != null && <LlmTraceDrawer logId={drawerLog} onClose={() => setDrawerLog(null)} />}
    </div>
  );
}

function fmtTs(iso: string): string {
  const d = new Date(iso);
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function pad(n: number): string { return String(n).padStart(2, '0'); }
