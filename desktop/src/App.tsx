import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, bridgeReady } from "./bridge";

type Status = {
  running: boolean;
  status: string;
  in_count_5m: number;
  outbound_pending: number;
  last_error: string | null;
};

type Account = {
  logged_in: boolean;
  account_id: string | null;
  display_name: string | null;
  machine_id: string | null;
};

type Channel = {
  channel_id: number;
  platform: string;
  platform_label: string;
  self_id: string | null;
  state: string;
  online: boolean;
  conv_count: number;
  last_error: string | null;
};

// Shape proxied from Studio /api/conversations (ConversationListItem).
type ConversationItem = {
  conversation: { id: string; display_name: string; updated_at: string };
  message_count: number;
};

type Section = "overview" | "channels" | "conversations" | "settings";

export function App() {
  const [section, setSection] = useState<Section>("overview");
  const [account, setAccount] = useState<Account | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    // Local runtime data always resolves (logged-out = empty state).
    try {
      const [acc, st, chs] = await Promise.all([
        api<Account>("/local/account"),
        api<Status>("/local/status"),
        api<Channel[]>("/local/channels"),
      ]);
      setAccount(acc);
      setStatus(st);
      setChannels(chs);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
    // Studio data is best-effort: 401 until login, or offline in dev.
    try {
      setConversations(await api<ConversationItem[]>("/studio/conversations"));
    } catch {
      setConversations([]);
    }
  }, []);

  useEffect(() => {
    if (!bridgeReady) return;
    load();
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [load]);

  if (!bridgeReady) {
    return (
      <div className="flex h-screen items-center justify-center text-[var(--color-ink-2)]">
        <div className="text-center">
          <div className="text-lg font-medium text-[var(--color-ink-1)]">连接本地 bridge…</div>
          <div className="mt-2 text-sm text-[var(--color-ink-3)]">preload 注入失败时会卡在这里</div>
        </div>
      </div>
    );
  }

  // account === null → first load still in flight; don't flash the login
  // screen before we know the real auth state.
  if (account && !account.logged_in) {
    return <LoginView onLoggedIn={load} />;
  }

  return (
    <div className="grid h-screen grid-cols-[240px_1fr] bg-[var(--color-bg-deep)]">
      <Sidebar section={section} onSelect={setSection} status={status} account={account} />
      <main className="overflow-y-auto">
        <div className="mx-auto max-w-5xl px-10 py-9">
          {error && <ErrorBanner message={error} />}
          {section === "overview" && (
            <Overview status={status} account={account} channels={channels} />
          )}
          {section === "channels" && <ChannelsView channels={channels} />}
          {section === "conversations" && <ConversationsView items={conversations} />}
          {section === "settings" && <SettingsView account={account} onLogout={load} />}
        </div>
      </main>
    </div>
  );
}

function LoginView({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api<{ error?: string }>("/local/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (res?.error) {
        setError(res.error);
        return;
      }
      onLoggedIn();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  const inputCls =
    "w-full rounded-md border border-[var(--color-line)] bg-[var(--color-bg-raised)] px-3 py-2 text-[14px] text-[var(--color-ink-1)] outline-none focus:border-[var(--color-brass)]";

  return (
    <div className="flex h-screen items-center justify-center bg-[var(--color-bg-deep)]">
      <form onSubmit={submit} className="w-[340px]">
        <div className="mb-7 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--color-brass)]/15 font-serif text-2xl text-[var(--color-brass)]">
            L
          </div>
          <h1 className="text-[19px] font-medium text-[var(--color-ink-1)]">登录 Laborster</h1>
          <p className="mt-1 text-[12.5px] text-[var(--color-ink-3)]">使用你的 Studio 账号</p>
        </div>

        {error && (
          <div className="mb-4 rounded-md border border-[var(--color-danger)]/40 bg-[var(--color-danger)]/10 px-3 py-2 text-[12.5px] text-[var(--color-danger)]">
            {error}
          </div>
        )}

        <label className="mb-1 block text-[12px] text-[var(--color-ink-3)]">用户名</label>
        <input
          className={inputCls}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoFocus
        />
        <label className="mb-1 mt-4 block text-[12px] text-[var(--color-ink-3)]">密码</label>
        <input
          className={inputCls}
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />

        <button
          type="submit"
          disabled={busy || !username || !password}
          className="mt-6 w-full rounded-md bg-[var(--color-brass)] py-2.5 text-[14px] font-medium text-[#1b1d23] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? "登录中…" : "登录"}
        </button>
      </form>
    </div>
  );
}

function Sidebar(props: {
  section: Section;
  onSelect: (s: Section) => void;
  status: Status | null;
  account: Account | null;
}) {
  const items: { key: Section; label: string }[] = [
    { key: "overview", label: "总览" },
    { key: "channels", label: "渠道" },
    { key: "conversations", label: "对话" },
    { key: "settings", label: "设置" },
  ];
  const dotColor = props.status?.running ? "bg-[var(--color-ok)]" : "bg-[var(--color-ink-4)]";
  return (
    <aside className="flex flex-col border-r border-[var(--color-line-soft)] bg-[var(--color-bg-base)] px-5 py-6">
      <div className="mb-8 flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--color-brass)]/15 text-[var(--color-brass)] font-serif text-lg">
          L
        </div>
        <div>
          <div className="text-[15px] font-medium tracking-wide text-[var(--color-ink-1)]">Laborster</div>
          <div className="text-[11px] uppercase tracking-widest text-[var(--color-ink-4)]">Desktop</div>
        </div>
      </div>

      <nav className="flex flex-col gap-1">
        {items.map((it) => {
          const active = it.key === props.section;
          return (
            <button
              key={it.key}
              onClick={() => props.onSelect(it.key)}
              className={`rounded-md px-3 py-2 text-left text-[13.5px] transition-colors ${
                active
                  ? "bg-[var(--color-bg-elev)] text-[var(--color-ink-1)]"
                  : "text-[var(--color-ink-2)] hover:bg-[var(--color-bg-raised)] hover:text-[var(--color-ink-1)]"
              }`}
            >
              {it.label}
            </button>
          );
        })}
      </nav>

      <div className="mt-auto rounded-lg border border-[var(--color-line-soft)] bg-[var(--color-bg-raised)] px-3 py-3">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${dotColor}`} />
          <span className="text-[12.5px] text-[var(--color-ink-2)]">
            {props.status?.running ? "守护进程运行中" : "未启动"}
          </span>
        </div>
        <div className="mt-1 truncate text-[11.5px] text-[var(--color-ink-3)]">
          {props.account?.display_name ?? "未登录"}
        </div>
      </div>
    </aside>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="mb-6 rounded-md border border-[var(--color-danger)]/40 bg-[var(--color-danger)]/10 px-4 py-3 text-sm text-[var(--color-danger)]">
      {message}
    </div>
  );
}

function SectionHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <header className="mb-7">
      <h1 className="text-[22px] font-medium tracking-tight text-[var(--color-ink-1)]">{title}</h1>
      {subtitle && <p className="mt-1 text-[13px] text-[var(--color-ink-3)]">{subtitle}</p>}
    </header>
  );
}

function Card({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-[var(--color-line-soft)] bg-[var(--color-bg-base)] p-5">
      {children}
    </div>
  );
}

function Metric({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <Card>
      <div className="text-[11.5px] uppercase tracking-wider text-[var(--color-ink-4)]">{label}</div>
      <div className="mt-2 text-[26px] font-medium text-[var(--color-ink-1)]">{value}</div>
      {hint && <div className="mt-1 text-[12px] text-[var(--color-ink-3)]">{hint}</div>}
    </Card>
  );
}

function Overview(props: { status: Status | null; account: Account | null; channels: Channel[] }) {
  const onlineCount = props.channels.filter((c) => c.online).length;
  return (
    <>
      <SectionHeader
        title={props.account?.display_name ? `早上好，${props.account.display_name}` : "总览"}
        subtitle="本地 bridge 与远端 Studio 的实时状态。"
      />
      <div className="grid grid-cols-3 gap-4">
        <Metric
          label="守护进程"
          value={props.status?.running ? "运行中" : "未启动"}
          hint={props.status?.status ?? "—"}
        />
        <Metric
          label="5 分钟新消息"
          value={props.status?.in_count_5m ?? 0}
          hint="入站消息（已入库）"
        />
        <Metric
          label="待发送"
          value={props.status?.outbound_pending ?? 0}
          hint="Studio → 渠道"
        />
      </div>

      <div className="mt-8">
        <h2 className="mb-3 text-[14px] font-medium text-[var(--color-ink-2)]">
          渠道 · 在线 {onlineCount} / {props.channels.length}
        </h2>
        <Card>
          {props.channels.length === 0 ? (
            <div className="py-4 text-center text-[13px] text-[var(--color-ink-3)]">还没有绑定任何渠道</div>
          ) : (
            <ul className="divide-y divide-[var(--color-line-soft)]">
              {props.channels.map((c) => (
                <ChannelRow key={c.channel_id} c={c} />
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}

function ChannelRow({ c }: { c: Channel }) {
  const dot = c.online ? "bg-[var(--color-ok)]" : "bg-[var(--color-ink-4)]";
  return (
    <li className="flex items-center gap-4 py-3 first:pt-1 last:pb-1">
      <span className={`h-2 w-2 shrink-0 rounded-full ${dot}`} />
      <div className="min-w-0 flex-1">
        <div className="text-[14px] text-[var(--color-ink-1)]">{c.platform_label}</div>
        <div className="truncate text-[12px] text-[var(--color-ink-3)]">
          {c.self_id ?? "未识别"} · {c.state}
        </div>
      </div>
      <div className="text-[12.5px] text-[var(--color-ink-3)]">{c.conv_count} 会话</div>
    </li>
  );
}

function ChannelsView({ channels }: { channels: Channel[] }) {
  return (
    <>
      <SectionHeader title="渠道" subtitle="每条渠道由一个 ChannelWorker 维护，状态来自 sqlite 快照。" />
      <Card>
        <ul className="divide-y divide-[var(--color-line-soft)]">
          {channels.map((c) => (
            <ChannelRow key={c.channel_id} c={c} />
          ))}
        </ul>
      </Card>
    </>
  );
}

function ConversationsView({ items }: { items: ConversationItem[] }) {
  return (
    <>
      <SectionHeader title="对话" subtitle="从 Studio 拉取的会话列表 · 走 /studio/* 代理。" />
      <Card>
        {items.length === 0 ? (
          <div className="py-4 text-center text-[13px] text-[var(--color-ink-3)]">
            暂无会话（需先登录 Studio，且本地能连通）
          </div>
        ) : (
          <ul className="divide-y divide-[var(--color-line-soft)]">
            {items.map(({ conversation: c, message_count }) => (
              <li key={c.id} className="flex items-center justify-between py-3">
                <div>
                  <div className="text-[14px] text-[var(--color-ink-1)]">{c.display_name}</div>
                  <div className="text-[12px] text-[var(--color-ink-3)]">更新于 {c.updated_at}</div>
                </div>
                <span className="text-[12.5px] text-[var(--color-ink-3)]">{message_count} 条</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

function SettingsView({ account, onLogout }: { account: Account | null; onLogout: () => void }) {
  const [busy, setBusy] = useState(false);
  const rows: [string, string][] = [
    ["账号 ID", account?.account_id ?? "—"],
    ["显示名", account?.display_name ?? "—"],
    ["机器 ID", account?.machine_id ?? "—"],
    ["bridge 端点", window.bridge?.baseUrl ?? "—"],
  ];

  const logout = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api("/local/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      onLogout();
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <SectionHeader title="设置" subtitle="账号与本地 bridge 的连接信息。" />
      <Card>
        <dl className="grid grid-cols-[140px_1fr] gap-y-3 text-[13.5px]">
          {rows.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-[var(--color-ink-3)]">{k}</dt>
              <dd className="font-mono text-[12.5px] text-[var(--color-ink-1)]">{v}</dd>
            </div>
          ))}
        </dl>
      </Card>
      <button
        onClick={logout}
        disabled={busy}
        className="mt-5 rounded-md border border-[var(--color-danger)]/40 px-4 py-2 text-[13px] text-[var(--color-danger)] transition-colors hover:bg-[var(--color-danger)]/10 disabled:opacity-40"
      >
        {busy ? "退出中…" : "退出登录"}
      </button>
    </>
  );
}
