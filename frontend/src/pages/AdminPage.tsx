import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import * as api from '../lib/api';
import type { Account, Character } from '../lib/api';
import { LaborsterLogo } from '../components/Icons';
import { cn, formatDate } from '../lib/utils';

type Tab = 'pending' | 'all' | 'characters';

const TABS: { key: Tab; label: string }[] = [
  { key: 'pending', label: '待审批' },
  { key: 'all', label: '全部账号' },
  { key: 'characters', label: '全局 Character' },
];

export function AdminPage() {
  const navigate = useNavigate();
  const [me, setMe] = useState<Account | null>(null);
  const [tab, setTab] = useState<Tab>('pending');
  const [error, setError] = useState('');

  useEffect(() => {
    api.authMe()
      .then(acc => {
        if (acc.role !== 'admin') {
          navigate('/robot', { replace: true });
        } else {
          setMe(acc);
        }
      })
      .catch(() => navigate('/login', { replace: true }));
  }, [navigate]);

  const handleLogout = async () => {
    await api.authLogout().catch(() => {});
    navigate('/login', { replace: true });
  };

  if (!me) return null;

  return (
    <div className="w-full h-dvh flex flex-col bg-bg-primary text-text-primary tech-grid">
      <header className="h-14 flex items-center justify-between px-4 md:px-6 border-b border-border-glow/30 shrink-0 bg-bg-secondary/80 backdrop-blur-sm">
        <div className="flex items-center gap-3 min-w-0">
          <LaborsterLogo size={20} />
          <span className="font-brand font-medium tracking-wider text-sm text-accent">Admin</span>
        </div>
        <div className="flex items-center gap-3 text-xs text-text-secondary">
          <span>{me.email}</span>
          <span className="text-text-tertiary">·</span>
          <button onClick={handleLogout} className="hover:text-accent">退出</button>
        </div>
      </header>

      <div className="flex border-b border-border-glow/20 bg-bg-secondary/40 shrink-0">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cn(
              'px-5 py-2.5 text-sm transition-all',
              tab === t.key ? 'text-accent border-b-2 border-accent font-medium' : 'text-text-secondary hover:text-text-primary border-b-2 border-transparent'
            )}
          >{t.label}</button>
        ))}
      </div>

      {error && (
        <div className="mx-4 mt-3 px-4 py-3 bg-danger-bg rounded-xl text-sm text-danger flex items-center justify-between shrink-0">
          <span className="break-all">{error}</span>
          <button onClick={() => setError('')} className="ml-2 text-danger hover:opacity-70">&times;</button>
        </div>
      )}

      <main className="flex-1 overflow-y-auto min-h-0">
        <div className="max-w-5xl mx-auto p-4 md:p-6">
          {tab === 'pending' && <AccountsPanel filter="pending" setError={setError} />}
          {tab === 'all' && <AccountsPanel filter="all" setError={setError} />}
          {tab === 'characters' && <CharactersPanel setError={setError} />}
        </div>
      </main>
    </div>
  );
}


function AccountsPanel({
  filter, setError,
}: { filter: 'pending' | 'all'; setError: (s: string) => void }) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [working, setWorking] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const list = filter === 'pending'
        ? await api.adminListAccounts('pending')
        : await api.adminListAccounts();
      setAccounts(list);
    } catch (e) { setError(String(e)); }
  }, [filter, setError]);

  useEffect(() => { load(); }, [load]);

  const handleApprove = async (id: string) => {
    setWorking(id);
    try { await api.adminApproveAccount(id); await load(); }
    catch (e) { setError(String(e)); }
    finally { setWorking(null); }
  };
  const handleReject = async (id: string) => {
    if (!confirm('确认拒绝该账号？拒绝后该账号将被停用。')) return;
    setWorking(id);
    try { await api.adminRejectAccount(id); await load(); }
    catch (e) { setError(String(e)); }
    finally { setWorking(null); }
  };
  const handleDisable = async (id: string) => {
    if (!confirm('确认停用该账号？该账号将无法登录。')) return;
    setWorking(id);
    try { await api.adminDisableAccount(id); await load(); }
    catch (e) { setError(String(e)); }
    finally { setWorking(null); }
  };

  if (accounts.length === 0) {
    return (
      <div className="text-sm text-text-secondary py-12 text-center border border-border-glow/20 rounded-xl">
        {filter === 'pending' ? '没有待审批账号' : '没有账号'}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {accounts.map(a => (
        <div key={a.id} className="border border-border-glow/20 rounded-xl bg-bg-secondary/50 px-4 py-3">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="min-w-0">
              <div className="text-sm font-medium truncate">
                {a.email}
                <span className={cn(
                  'ml-3 text-xs px-2 py-0.5 rounded',
                  a.status === 'pending' && 'bg-yellow-500/20 text-yellow-300',
                  a.status === 'active' && 'bg-success/20 text-success',
                  a.status === 'disabled' && 'bg-danger/20 text-danger',
                )}>{a.status}</span>
                <span className="ml-2 text-xs text-text-tertiary">{a.role}</span>
              </div>
              <div className="text-xs text-text-tertiary mt-0.5">
                {a.id} · 注册 {formatDate(a.created_at)} · 最近登录 {a.last_login_at ? formatDate(a.last_login_at) : '—'}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {a.status === 'pending' && a.role === 'operator_owner' && (
                <>
                  <button
                    onClick={() => handleApprove(a.id)}
                    disabled={working === a.id}
                    className="px-3 py-1.5 text-xs rounded-lg bg-success/20 text-success border border-success/40 hover:bg-success/30 disabled:opacity-30"
                  >{working === a.id ? '...' : '通过'}</button>
                  <button
                    onClick={() => handleReject(a.id)}
                    disabled={working === a.id}
                    className="px-3 py-1.5 text-xs rounded-lg bg-danger/20 text-danger border border-danger/40 hover:bg-danger/30 disabled:opacity-30"
                  >{working === a.id ? '...' : '拒绝'}</button>
                </>
              )}
              {a.status === 'active' && a.role === 'operator_owner' && (
                <button
                  onClick={() => handleDisable(a.id)}
                  disabled={working === a.id}
                  className="px-3 py-1.5 text-xs rounded-lg text-danger hover:bg-danger/10"
                >{working === a.id ? '...' : '停用'}</button>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}


function CharactersPanel({ setError }: { setError: (s: string) => void }) {
  const [list, setList] = useState<Character[]>([]);
  useEffect(() => {
    api.adminListCharacters()
      .then(setList)
      .catch(e => setError(String(e)));
  }, [setError]);

  if (list.length === 0) {
    return (
      <div className="text-sm text-text-secondary py-12 text-center border border-border-glow/20 rounded-xl">
        还没有 Character。
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {list.map(c => (
        <div key={c.id} className="border border-border-glow/20 rounded-xl bg-bg-secondary/50 px-4 py-3">
          <div className="text-sm font-medium truncate">
            {c.name}
            <span className="ml-3 text-xs text-text-tertiary">{c.id}</span>
          </div>
          <div className="text-xs text-text-tertiary mt-0.5">
            account: <code>{c.account_id}</code> · provider: {c.provider_config?.name || '未绑定'} · {c.persona_md ? '已蒸馏' : '未蒸馏'}
          </div>
        </div>
      ))}
    </div>
  );
}
