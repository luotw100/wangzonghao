import { NavLink, Navigate, Route, Routes } from 'react-router-dom';
import { AccountsPage } from './pages/AccountsPage.tsx';
import { ProvidersPage } from './pages/ProvidersPage.tsx';
import { ConversationsPage } from './pages/ConversationsPage.tsx';
import { HostedBridgesPage } from './pages/HostedBridgesPage.tsx';
import { ChatsPage } from './pages/ChatsPage.tsx';
import { LlmLogsPage } from './pages/LlmLogsPage.tsx';
import { DistillJobsPage } from './pages/DistillJobsPage.tsx';
import { PersonaTimelinePage } from './pages/PersonaTimelinePage.tsx';

type Page =
  | 'accounts' | 'providers' | 'conversations' | 'hosted-bridges'
  | 'chats' | 'llm-logs' | 'distill-jobs' | 'persona-timeline';

const NAV: { id: Page; label: string }[] = [
  { id: 'accounts', label: 'Accounts' },
  { id: 'providers', label: 'Providers' },
  { id: 'conversations', label: 'Conversations' },
  { id: 'hosted-bridges', label: 'Hosted Bridges' },
  { id: 'chats', label: 'Chats' },
  { id: 'llm-logs', label: 'LLM Logs' },
  { id: 'distill-jobs', label: 'Distill Jobs' },
  { id: 'persona-timeline', label: 'Persona Timeline' },
];

export default function App() {
  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      {/* Sidebar */}
      <nav style={{
        width: 200,
        flexShrink: 0,
        background: 'var(--bg-base)',
        borderRight: '1px solid var(--line-subtle)',
        display: 'flex',
        flexDirection: 'column',
        padding: '20px 0',
      }}>
        <div style={{ padding: '0 20px 24px', display: 'flex', alignItems: 'center', gap: 10 }}>
          <span className="lab-mark" style={{
            position: 'relative',
            display: 'inline-block',
            width: 20,
            height: 20,
            fontFamily: 'var(--f-serif)',
            fontWeight: 500,
            fontSize: 20,
            lineHeight: '20px',
            color: 'var(--ink-1)',
          }}>L</span>
          <span style={{ fontWeight: 600, fontSize: 13, color: 'var(--ink-2)', letterSpacing: '0.04em' }}>
            ADMIN
          </span>
        </div>

        <div style={{ height: 1, background: 'var(--line-subtle)', margin: '0 0 12px' }} />

        {NAV.map(({ id, label }) => (
          <NavLink
            key={id}
            to={`/${id}`}
            style={({ isActive }) => ({
              display: 'block',
              width: '100%',
              textAlign: 'left',
              padding: '8px 20px',
              background: isActive ? 'var(--bg-raised)' : 'transparent',
              border: 'none',
              borderLeft: isActive ? '2px solid var(--brass)' : '2px solid transparent',
              color: isActive ? 'var(--ink-1)' : 'var(--ink-3)',
              fontFamily: 'var(--f-ui)',
              fontSize: 13,
              fontWeight: isActive ? 500 : 400,
              cursor: 'pointer',
              textDecoration: 'none',
              transition: 'all .12s',
            })}
          >
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Main content */}
      <main style={{ flex: 1, overflow: 'auto', padding: 28 }}>
        <Routes>
          <Route path="/" element={<Navigate to="/accounts" replace />} />
          <Route path="/accounts" element={<AccountsPage />} />
          <Route path="/providers" element={<ProvidersPage />} />
          <Route path="/conversations" element={<ConversationsPage />} />
          <Route path="/hosted-bridges" element={<HostedBridgesPage />} />
          <Route path="/chats" element={<ChatsPage />} />
          <Route path="/chats/c/:conversationId" element={<ChatsPage />} />
          <Route path="/llm-logs" element={<LlmLogsPage />} />
          <Route path="/distill-jobs" element={<DistillJobsPage />} />
          <Route path="/persona-timeline" element={<PersonaTimelinePage />} />
          <Route path="*" element={<Navigate to="/accounts" replace />} />
        </Routes>
      </main>
    </div>
  );
}
