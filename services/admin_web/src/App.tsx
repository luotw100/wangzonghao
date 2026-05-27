import { useState } from 'react';
import { AccountsPage } from './pages/AccountsPage.tsx';
import { ProvidersPage } from './pages/ProvidersPage.tsx';
import { ConversationsPage } from './pages/ConversationsPage.tsx';
import { HostedBridgesPage } from './pages/HostedBridgesPage.tsx';

type Page = 'accounts' | 'providers' | 'conversations' | 'hosted-bridges';

const NAV: { id: Page; label: string }[] = [
  { id: 'accounts', label: 'Accounts' },
  { id: 'providers', label: 'Providers' },
  { id: 'conversations', label: 'Conversations' },
  { id: 'hosted-bridges', label: 'Hosted Bridges' },
];

export default function App() {
  const [page, setPage] = useState<Page>('accounts');

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
          <button
            key={id}
            onClick={() => setPage(id)}
            style={{
              display: 'block',
              width: '100%',
              textAlign: 'left',
              padding: '8px 20px',
              background: page === id ? 'var(--bg-raised)' : 'transparent',
              border: 'none',
              borderLeft: page === id ? '2px solid var(--brass)' : '2px solid transparent',
              color: page === id ? 'var(--ink-1)' : 'var(--ink-3)',
              fontFamily: 'var(--f-ui)',
              fontSize: 13,
              fontWeight: page === id ? 500 : 400,
              cursor: 'pointer',
              transition: 'all .12s',
            }}
          >
            {label}
          </button>
        ))}
      </nav>

      {/* Main content */}
      <main style={{ flex: 1, overflow: 'auto', padding: 28 }}>
        {page === 'accounts' && <AccountsPage />}
        {page === 'providers' && <ProvidersPage />}
        {page === 'conversations' && <ConversationsPage />}
        {page === 'hosted-bridges' && <HostedBridgesPage />}
      </main>
    </div>
  );
}
