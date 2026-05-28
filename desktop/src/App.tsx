import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { api, post, bridgeReady } from "./bridge";

// ---- types -----------------------------------------------------------

type Status = {
  running: boolean;
  status: string;
  in_count_5m: number;
  outbound_pending: number;
  last_error: string | null;
  studio_url?: string;
};

type Account = {
  logged_in: boolean;
  account_id: string | null;
  display_name: string | null;
  machine_id: string | null;
  studio_url?: string;
  has_channels?: boolean;
};

type AccountListItem = {
  account_id: string;
  display_name: string | null;
  active: boolean;
  channel_count: number;
  has_token: boolean;
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

type Platform = { id: string; label: string };

type LogLine = { t: string; src: string; level: string; msg: string };

type Result = { lines?: string[]; error?: string };

// Step payloads mirror gui.bridge_api._step_payload.
type Field = { name: string; label: string; secret: boolean; placeholder: string };
type Step =
  | { kind: "prompt"; title: string; error: string | null; fields: Field[] }
  | {
      kind: "wait";
      title: string;
      poll_after_ms: number;
      qr_png_b64: string | null;
      open_url: string | null;
      hint: string | null;
    }
  | { kind: "done" }
  | { kind: "failed"; reason: string };

type Section = "overview" | "channels" | "logs" | "settings";

type Toast = { text: string; kind: "ok" | "err" } | null;

// ---- toast hook ------------------------------------------------------

function useToast() {
  const [toast, setToast] = useState<Toast>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const notify = useCallback((text: string, kind: "ok" | "err" = "ok") => {
    setToast({ text, kind });
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast(null), 4000);
  }, []);
  // Returns true on success, false on {error}, for chaining.
  const notifyResult = useCallback(
    (r: Result | undefined, okFallback = "") => {
      if (!r) return true;
      if (r.error) {
        notify(r.error, "err");
        return false;
      }
      const msg = r.lines?.[0] || okFallback;
      if (msg) notify(msg, "ok");
      return true;
    },
    [notify],
  );
  return { toast, notify, notifyResult };
}

// ---- root ------------------------------------------------------------

export function App() {
  const [section, setSection] = useState<Section>("overview");
  const [account, setAccount] = useState<Account | null>(null);
  const [accounts, setAccounts] = useState<AccountListItem[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [flow, setFlow] = useState<{ platform: string | null; channelId: number | null } | null>(
    null,
  );
  const { toast, notify, notifyResult } = useToast();

  const refresh = useCallback(async () => {
    try {
      const [acc, accs, st, chs] = await Promise.all([
        api<Account>("/local/account"),
        api<AccountListItem[]>("/local/accounts"),
        api<Status>("/local/status"),
        api<Channel[]>("/local/channels"),
      ]);
      setAccount(acc);
      setAccounts(accs);
      setStatus(st);
      setChannels(chs);
    } catch {
      /* window closing / transient */
    }
  }, []);

  useEffect(() => {
    if (!bridgeReady) return;
    api<Platform[]>("/local/platforms").then(setPlatforms).catch(() => {});
    refresh();
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [refresh]);

  if (!bridgeReady) {
    return (
      <Centered>
        <div className="text-lg font-medium text-[var(--color-ink-1)]">连接本地 bridge…</div>
        <div className="mt-2 text-sm text-[var(--color-ink-3)]">preload 注入失败时会卡在这里</div>
      </Centered>
    );
  }

  if (account && !account.logged_in) {
    return (
      <>
        <LoginView onDone={refresh} notify={notify} />
        <ToastView toast={toast} />
      </>
    );
  }

  return (
    <div className="grid h-screen grid-cols-[240px_1fr] bg-[var(--color-bg-deep)]">
      <Sidebar section={section} onSelect={setSection} status={status} account={account} />
      <main className="overflow-y-auto">
        <div className="mx-auto max-w-5xl px-10 py-9">
          {status?.last_error && <ErrorBanner message={status.last_error} />}
          {section === "overview" && <Overview status={status} account={account} channels={channels} />}
          {section === "channels" && (
            <ChannelsView
              channels={channels}
              onBind={() => setFlow({ platform: null, channelId: null })}
              onRelogin={(c) => setFlow({ platform: c.platform, channelId: c.channel_id })}
              onChanged={refresh}
              notifyResult={notifyResult}
            />
          )}
          {section === "logs" && <LogsView notify={notify} />}
          {section === "settings" && (
            <SettingsView
              account={account}
              accounts={accounts}
              onChanged={refresh}
              onAddAccount={() => setFlow(null)}
              notify={notify}
              notifyResult={notifyResult}
            />
          )}
        </div>
      </main>

      {flow && (
        <FlowModal
          platform={flow.platform}
          channelId={flow.channelId}
          platforms={platforms}
          onClose={() => setFlow(null)}
          onDone={() => {
            setFlow(null);
            refresh();
          }}
          notify={notify}
        />
      )}
      <ToastView toast={toast} />
    </div>
  );
}

// ---- shared presentational ------------------------------------------

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-screen items-center justify-center bg-[var(--color-bg-deep)] text-center text-[var(--color-ink-2)]">
      <div>{children}</div>
    </div>
  );
}

function SectionHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: ReactNode }) {
  return (
    <header className="mb-7 flex items-end justify-between">
      <div>
        <h1 className="text-[22px] font-medium tracking-tight text-[var(--color-ink-1)]">{title}</h1>
        {subtitle && <p className="mt-1 text-[13px] text-[var(--color-ink-3)]">{subtitle}</p>}
      </div>
      {action}
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

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="mb-6 rounded-md border border-[var(--color-danger)]/40 bg-[var(--color-danger)]/10 px-4 py-3 text-sm text-[var(--color-danger)]">
      {message}
    </div>
  );
}

const PRIMARY_BTN =
  "rounded-md bg-[var(--color-brass)] px-4 py-2 text-[13px] font-medium text-[#1b1d23] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40";
const GHOST_BTN =
  "rounded-md border border-[var(--color-line)] px-4 py-2 text-[13px] text-[var(--color-ink-2)] transition-colors hover:bg-[var(--color-bg-raised)] disabled:opacity-40";
const INPUT_CLS =
  "w-full rounded-md border border-[var(--color-line)] bg-[var(--color-bg-raised)] px-3 py-2 text-[14px] text-[var(--color-ink-1)] outline-none focus:border-[var(--color-brass)]";

function ToastView({ toast }: { toast: Toast }) {
  if (!toast) return null;
  const tone =
    toast.kind === "err"
      ? "border-[var(--color-danger)]/50 text-[var(--color-danger)]"
      : "border-[var(--color-ok)]/50 text-[var(--color-ok)]";
  return (
    <div
      className={`fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-md border bg-[var(--color-bg-elev)] px-4 py-2.5 text-[13px] shadow-lg ${tone}`}
    >
      {toast.text}
    </div>
  );
}

// ---- sidebar ---------------------------------------------------------

const STATUS_LABEL: Record<string, string> = {
  idle: "空闲",
  connecting: "连接中…",
  online: "桥接运行中",
  degraded: "部分渠道离线",
  needs_login: "渠道凭据失效",
  error401: "Studio 会话失效",
};

function Sidebar(props: {
  section: Section;
  onSelect: (s: Section) => void;
  status: Status | null;
  account: Account | null;
}) {
  const items: { key: Section; label: string }[] = [
    { key: "overview", label: "总览" },
    { key: "channels", label: "渠道" },
    { key: "logs", label: "日志" },
    { key: "settings", label: "设置" },
  ];
  const dot = props.status?.running ? "bg-[var(--color-ok)]" : "bg-[var(--color-ink-4)]";
  return (
    <aside className="flex flex-col border-r border-[var(--color-line-soft)] bg-[var(--color-bg-base)] px-5 py-6">
      <div className="mb-8 flex items-center gap-3">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--color-brass)]/15 font-serif text-lg text-[var(--color-brass)]">
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
          <span className={`h-2 w-2 rounded-full ${dot}`} />
          <span className="text-[12.5px] text-[var(--color-ink-2)]">
            {props.status ? STATUS_LABEL[props.status.status] ?? props.status.status : "—"}
          </span>
        </div>
        <div className="mt-1 truncate text-[11.5px] text-[var(--color-ink-3)]">
          {props.account?.display_name ?? "未登录"}
        </div>
      </div>
    </aside>
  );
}

// ---- overview --------------------------------------------------------

function Overview(props: { status: Status | null; account: Account | null; channels: Channel[] }) {
  const onlineCount = props.channels.filter((c) => c.online).length;
  return (
    <>
      <SectionHeader
        title={props.account?.display_name ? `你好，${props.account.display_name}` : "总览"}
        subtitle="本地 bridge 的实时状态。"
      />
      <div className="grid grid-cols-3 gap-4">
        <Metric label="守护进程" value={props.status?.running ? "运行中" : "未启动"} hint={props.status?.status ?? "—"} />
        <Metric label="5 分钟新消息" value={props.status?.in_count_5m ?? 0} hint="入站消息（已入库）" />
        <Metric label="待发送" value={props.status?.outbound_pending ?? 0} hint="Studio → 渠道" />
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

const CHAN_STATE: Record<string, { dot: string; label: string }> = {
  online: { dot: "bg-[var(--color-ok)]", label: "online" },
  connecting: { dot: "bg-[var(--color-warn)]", label: "连接中…" },
  backoff: { dot: "bg-[var(--color-warn)]", label: "退避重试中" },
  needs_login: { dot: "bg-[var(--color-danger)]", label: "凭据失效" },
  removed: { dot: "bg-[var(--color-ink-4)]", label: "已移除" },
  idle: { dot: "bg-[var(--color-ink-4)]", label: "等待启动" },
};

function ChannelRow({ c }: { c: Channel }) {
  const meta = CHAN_STATE[c.state] ?? CHAN_STATE.idle;
  return (
    <li className="flex items-center gap-4 py-3 first:pt-1 last:pb-1">
      <span className={`h-2 w-2 shrink-0 rounded-full ${meta.dot}`} />
      <div className="min-w-0 flex-1">
        <div className="text-[14px] text-[var(--color-ink-1)]">
          {c.self_id ? `${c.platform_label} · ${c.self_id}` : c.platform_label}
        </div>
        <div className="truncate text-[12px] text-[var(--color-ink-3)]">
          {c.state === "online" ? `${c.conv_count} 会话 · ${meta.label}` : meta.label}
          {c.last_error ? ` · ${c.last_error}` : ""}
        </div>
      </div>
    </li>
  );
}

// ---- channels --------------------------------------------------------

function ChannelsView(props: {
  channels: Channel[];
  onBind: () => void;
  onRelogin: (c: Channel) => void;
  onChanged: () => void;
  notifyResult: (r: Result | undefined, okFallback?: string) => boolean;
}) {
  const [busyId, setBusyId] = useState<number | null>(null);

  const remove = async (c: Channel) => {
    const ident = c.self_id ? `${c.platform_label} · ${c.self_id}` : c.platform_label;
    if (!confirm(`删除渠道：${ident}？`)) return;
    setBusyId(c.channel_id);
    try {
      const r = await post<Result>("/local/channel_rm", { channel_id: c.channel_id });
      props.notifyResult(r, "已删除");
      props.onChanged();
    } finally {
      setBusyId(null);
    }
  };

  return (
    <>
      <SectionHeader
        title="渠道"
        subtitle="每条渠道由一个 ChannelWorker 维护，状态来自 sqlite 快照。"
        action={
          <button className={PRIMARY_BTN} onClick={props.onBind}>
            + 绑定渠道
          </button>
        }
      />
      {props.channels.length === 0 ? (
        <Card>
          <div className="py-8 text-center">
            <div className="text-[14px] text-[var(--color-ink-2)]">还没有绑定任何渠道</div>
            <button className={`${PRIMARY_BTN} mt-4`} onClick={props.onBind}>
              + 绑定第一个渠道
            </button>
          </div>
        </Card>
      ) : (
        <div className="flex flex-col gap-3">
          {props.channels.map((c) => {
            const meta = CHAN_STATE[c.state] ?? CHAN_STATE.idle;
            const ident = c.self_id ? `${c.platform_label} · ${c.self_id}` : c.platform_label;
            return (
              <div
                key={c.channel_id}
                className="flex items-center gap-4 rounded-xl border border-[var(--color-line-soft)] bg-[var(--color-bg-base)] px-5 py-4"
              >
                <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${meta.dot}`} />
                <div className="min-w-0 flex-1">
                  <div className="text-[14px] text-[var(--color-ink-1)]">{ident}</div>
                  <div className="truncate text-[12px] text-[var(--color-ink-3)]">
                    {c.state === "online" ? `${c.conv_count} 会话 · ${meta.label}` : meta.label}
                    {c.last_error ? (
                      <span className="text-[var(--color-danger)]"> · {c.last_error}</span>
                    ) : null}
                  </div>
                </div>
                <button className={GHOST_BTN} onClick={() => props.onRelogin(c)} disabled={busyId === c.channel_id}>
                  重新登录
                </button>
                <button
                  className="rounded-md border border-[var(--color-danger)]/40 px-3 py-2 text-[13px] text-[var(--color-danger)] transition-colors hover:bg-[var(--color-danger)]/10 disabled:opacity-40"
                  onClick={() => remove(c)}
                  disabled={busyId === c.channel_id}
                >
                  删除
                </button>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

// ---- logs ------------------------------------------------------------

const LOG_TONE: Record<string, string> = {
  err: "text-[var(--color-danger)]",
  warn: "text-[var(--color-warn)]",
  ok: "text-[var(--color-ok)]",
  info: "text-[var(--color-ink-2)]",
};

function LogsView({ notify }: { notify: (t: string, k?: "ok" | "err") => void }) {
  const [logs, setLogs] = useState<LogLine[]>([]);
  const boxRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    const pull = async () => {
      try {
        const lines = await api<LogLine[]>("/local/logs?n=400");
        if (!cancelled) setLogs(lines);
      } catch {
        /* transient */
      }
    };
    pull();
    const t = setInterval(pull, 2000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  useEffect(() => {
    const box = boxRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [logs]);

  const openDir = async () => {
    const r = await post<Result>("/local/open_data_dir");
    if (r?.error) notify(r.error, "err");
  };

  return (
    <>
      <SectionHeader
        title="日志"
        subtitle="守护进程事件流（每 2 秒拉取最近 400 行）。"
        action={
          <button className={GHOST_BTN} onClick={openDir}>
            打开数据目录
          </button>
        }
      />
      <div
        ref={boxRef}
        className="h-[calc(100vh-220px)] overflow-y-auto rounded-xl border border-[var(--color-line-soft)] bg-[var(--color-bg-deep)] p-4 font-mono text-[12px] leading-relaxed"
      >
        {logs.length === 0 ? (
          <div className="text-[var(--color-ink-4)]">暂无日志</div>
        ) : (
          logs.map((ln, i) => (
            <div key={i} className="whitespace-pre-wrap break-all">
              <span className="text-[var(--color-ink-4)]">{ln.t}</span>{" "}
              <span className="text-[var(--color-ink-3)]">[{ln.src}/</span>
              <span className={LOG_TONE[ln.level] ?? ""}>{ln.level}]</span>{" "}
              <span className={LOG_TONE[ln.level] ?? "text-[var(--color-ink-1)]"}>{ln.msg}</span>
            </div>
          ))
        )}
      </div>
    </>
  );
}

// ---- settings: accounts ---------------------------------------------

function SettingsView(props: {
  account: Account | null;
  accounts: AccountListItem[];
  onChanged: () => void;
  onAddAccount: () => void;
  notify: (t: string, k?: "ok" | "err") => void;
  notifyResult: (r: Result | undefined, okFallback?: string) => boolean;
}) {
  const [busy, setBusy] = useState(false);

  const wrap = async (fn: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  };

  const use = (a: AccountListItem) =>
    wrap(async () => {
      const r = await post<Result>("/local/use_account", { account_id: a.account_id });
      props.notifyResult(r, `已切换到 ${a.display_name || a.account_id}`);
      props.onChanged();
    });

  const removeAcc = (a: AccountListItem) =>
    wrap(async () => {
      if (!confirm(`删除本机账号 ${a.display_name || a.account_id}？\n会清掉该账号的所有渠道凭据与本地消息。`)) return;
      const r = await post<Result>("/local/remove_account", { account_id: a.account_id });
      props.notifyResult(r, "已删除");
      props.onChanged();
    });

  const logout = () =>
    wrap(async () => {
      const r = await post<Result>("/local/logout");
      props.notifyResult(r, "已登出");
      props.onChanged();
    });

  const rows: [string, string][] = [
    ["Studio", props.account?.studio_url ?? "—"],
    ["机器 ID", props.account?.machine_id ?? "—"],
    ["bridge 端点", window.bridge?.baseUrl ?? "—"],
  ];

  return (
    <>
      <SectionHeader
        title="设置"
        subtitle="账号与本地 bridge 的连接信息。"
        action={
          <button className={GHOST_BTN} onClick={props.onAddAccount}>
            + 添加 Studio 账号
          </button>
        }
      />

      <h2 className="mb-3 text-[14px] font-medium text-[var(--color-ink-2)]">本机账号</h2>
      <div className="mb-8 flex flex-col gap-2">
        {props.accounts.length === 0 && (
          <Card>
            <div className="text-[13px] text-[var(--color-ink-3)]">（暂无本机账号）</div>
          </Card>
        )}
        {props.accounts.map((a) => (
          <div
            key={a.account_id}
            className="flex items-center gap-4 rounded-xl border border-[var(--color-line-soft)] bg-[var(--color-bg-base)] px-5 py-3.5"
          >
            <span className="w-4 text-[var(--color-ok)]">{a.active ? "✓" : ""}</span>
            <div className="min-w-0 flex-1">
              <div className="text-[14px] text-[var(--color-ink-1)]">{a.display_name || a.account_id}</div>
              <div className="truncate text-[12px] text-[var(--color-ink-3)]">
                {a.account_id} · 渠道 {a.channel_count} · {a.has_token ? "已登录" : "未登录"}
              </div>
            </div>
            {!a.active && (
              <button className={GHOST_BTN} onClick={() => use(a)} disabled={busy}>
                切换
              </button>
            )}
            <button
              className="rounded-md border border-[var(--color-danger)]/40 px-3 py-2 text-[13px] text-[var(--color-danger)] transition-colors hover:bg-[var(--color-danger)]/10 disabled:opacity-40"
              onClick={() => removeAcc(a)}
              disabled={busy}
            >
              删除
            </button>
          </div>
        ))}
      </div>

      <Card>
        <dl className="grid grid-cols-[120px_1fr] gap-y-3 text-[13.5px]">
          {rows.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-[var(--color-ink-3)]">{k}</dt>
              <dd className="truncate font-mono text-[12.5px] text-[var(--color-ink-1)]">{v}</dd>
            </div>
          ))}
        </dl>
      </Card>

      {props.account?.logged_in && (
        <button
          onClick={logout}
          disabled={busy}
          className="mt-5 rounded-md border border-[var(--color-danger)]/40 px-4 py-2 text-[13px] text-[var(--color-danger)] transition-colors hover:bg-[var(--color-danger)]/10 disabled:opacity-40"
        >
          登出当前账号
        </button>
      )}
    </>
  );
}

// ---- first-time login ------------------------------------------------

function LoginView({
  onDone,
  notify,
}: {
  onDone: () => void;
  notify: (t: string, k?: "ok" | "err") => void;
}) {
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
      const r = await post<Result>("/local/login", { username, password });
      if (r?.error) {
        setError(r.error);
        return;
      }
      notify(r?.lines?.[0] || "登录成功", "ok");
      onDone();
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

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
        <input className={INPUT_CLS} value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        <label className="mb-1 mt-4 block text-[12px] text-[var(--color-ink-3)]">密码</label>
        <input
          className={INPUT_CLS}
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />

        <button type="submit" disabled={busy || !username || !password} className={`${PRIMARY_BTN} mt-6 w-full py-2.5`}>
          {busy ? "登录中…" : "登录"}
        </button>
      </form>
    </div>
  );
}

// ---- channel binding / relogin flow ----------------------------------

function FlowModal(props: {
  platform: string | null;
  channelId: number | null;
  platforms: Platform[];
  onClose: () => void;
  onDone: () => void;
  notify: (t: string, k?: "ok" | "err") => void;
}) {
  const { platforms, channelId, notify } = props;
  const isRelogin = channelId != null;

  // pick: choosing a platform (new channel). running: a flow is live.
  const [phase, setPhase] = useState<"pick" | "running">(props.platform ? "running" : "pick");
  const [platform, setPlatform] = useState<string>(props.platform ?? platforms[0]?.id ?? "");
  const [baseUrl, setBaseUrl] = useState("");
  const [flowId, setFlowId] = useState<string | null>(null);
  const [step, setStep] = useState<Step | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [stepError, setStepError] = useState<string | null>(null);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const flowIdRef = useRef<string | null>(null);

  const labelOf = (id: string) => platforms.find((p) => p.id === id)?.label ?? id;

  const clearPoll = () => {
    if (pollTimer.current) {
      clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  };

  const close = useCallback(() => {
    clearPoll();
    const id = flowIdRef.current;
    if (id) post("/local/flow_cancel", { flow_id: id }).catch(() => {});
    flowIdRef.current = null;
    props.onClose();
  }, [props]);

  // Drive a step result: terminal states persist or fail; otherwise render.
  const handleStep = useCallback(
    (s: Step, fid: string) => {
      setStepError(null);
      if (s.kind === "failed") {
        notify(s.reason || "登录失败", "err");
        close();
        return;
      }
      if (s.kind === "done") {
        post<Result>("/local/flow_persist", {
          flow_id: fid,
          channel_id: channelId,
        }).then((r) => {
          flowIdRef.current = null;
          if (r?.error) {
            notify(r.error, "err");
            props.onClose();
            return;
          }
          notify(r?.lines?.[0] || (isRelogin ? "已更新凭据" : "已绑定"), "ok");
          props.onDone();
        });
        return;
      }
      setStep(s);
      setAnswers({});
      if (s.kind === "wait") {
        const delay = Math.max(500, s.poll_after_ms || 1500);
        pollTimer.current = setTimeout(async () => {
          if (!flowIdRef.current) return;
          try {
            const r = await post<{ step?: Step; error?: string }>("/local/flow_poll", { flow_id: fid });
            if (r.error) {
              notify(r.error, "err");
              close();
              return;
            }
            if (r.step) handleStep(r.step, fid);
          } catch (e) {
            notify(String(e), "err");
            close();
          }
        }, delay);
      }
    },
    [channelId, isRelogin, notify, close, props],
  );

  const startFlow = useCallback(
    async (plat: string, extras: Record<string, unknown>) => {
      setBusy(true);
      try {
        const r = await post<{ flow_id?: string; step?: Step; error?: string }>("/local/flow_begin", {
          platform: plat,
          extras,
          channel_id: channelId,
        });
        if (r.error || !r.flow_id || !r.step) {
          notify(r.error || "启动登录失败", "err");
          props.onClose();
          return;
        }
        flowIdRef.current = r.flow_id;
        setFlowId(r.flow_id);
        setPhase("running");
        handleStep(r.step, r.flow_id);
      } finally {
        setBusy(false);
      }
    },
    [channelId, notify, handleStep, props],
  );

  // Relogin starts immediately (platform fixed by caller).
  useEffect(() => {
    if (props.platform) startFlow(props.platform, {});
    return clearPoll;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submitPrompt = async () => {
    if (!flowId) return;
    setBusy(true);
    setStepError(null);
    try {
      const r = await post<{ step?: Step; error?: string }>("/local/flow_submit", {
        flow_id: flowId,
        answers,
      });
      if (r.error) {
        setStepError(r.error);
        return;
      }
      if (r.step) handleStep(r.step, flowId);
    } finally {
      setBusy(false);
    }
  };

  const title =
    phase === "pick"
      ? "绑定渠道 — 选择平台"
      : `${isRelogin ? "重新登录" : "绑定渠道"} — ${labelOf(platform)}`;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/55" onClick={close} />
      <div className="relative w-[420px] rounded-xl border border-[var(--color-line)] bg-[var(--color-bg-base)] p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-[16px] font-medium text-[var(--color-ink-1)]">{title}</h3>
          <button className="text-[var(--color-ink-4)] hover:text-[var(--color-ink-1)]" onClick={close}>
            ✕
          </button>
        </div>

        {phase === "pick" && (
          <>
            <label className="mb-1 block text-[12px] text-[var(--color-ink-3)]">平台</label>
            <select className={INPUT_CLS} value={platform} onChange={(e) => setPlatform(e.target.value)}>
              {platforms.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
            {platform === "chat" && (
              <div className="mt-4">
                <label className="mb-1 block text-[12px] text-[var(--color-ink-3)]">
                  base_url（可选 — chat 沙箱开发态用）
                </label>
                <input
                  className={INPUT_CLS}
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder="留空则用默认地址"
                />
              </div>
            )}
            <div className="mt-6 flex justify-end gap-3">
              <button className={GHOST_BTN} onClick={close}>
                取消
              </button>
              <button
                className={PRIMARY_BTN}
                disabled={busy || !platform}
                onClick={() => startFlow(platform, baseUrl.trim() ? { base_url: baseUrl.trim() } : {})}
              >
                下一步
              </button>
            </div>
          </>
        )}

        {phase === "running" && step?.kind === "prompt" && (
          <>
            {stepError && (
              <div className="mb-3 rounded-md border border-[var(--color-danger)]/40 bg-[var(--color-danger)]/10 px-3 py-2 text-[12.5px] text-[var(--color-danger)]">
                {stepError}
              </div>
            )}
            {step.fields.map((f) => (
              <div key={f.name} className="mb-3">
                <label className="mb-1 block text-[12px] text-[var(--color-ink-3)]">{f.label}</label>
                <input
                  className={INPUT_CLS}
                  type={f.secret ? "password" : "text"}
                  placeholder={f.placeholder}
                  value={answers[f.name] ?? ""}
                  onChange={(e) => setAnswers((a) => ({ ...a, [f.name]: e.target.value }))}
                />
              </div>
            ))}
            <div className="mt-6 flex justify-end gap-3">
              <button className={GHOST_BTN} onClick={close}>
                取消
              </button>
              <button className={PRIMARY_BTN} disabled={busy} onClick={submitPrompt}>
                {busy ? "提交中…" : "提交"}
              </button>
            </div>
          </>
        )}

        {phase === "running" && step?.kind === "wait" && (
          <div className="text-center">
            {step.qr_png_b64 && (
              <img
                className="mx-auto mb-3 h-48 w-48 rounded-md bg-white p-2"
                src={`data:image/png;base64,${step.qr_png_b64}`}
                alt="二维码"
              />
            )}
            {step.open_url && (
              <a
                className="block break-all text-[12.5px] text-[var(--color-brass)] underline"
                href={step.open_url}
                target="_blank"
                rel="noreferrer"
              >
                {step.open_url}
              </a>
            )}
            {step.hint && <p className="mt-2 text-[12.5px] text-[var(--color-ink-3)]">{step.hint}</p>}
            <p className="mt-4 text-[12.5px] text-[var(--color-ink-3)]">等待确认…</p>
            <div className="mt-6 flex justify-center">
              <button className={GHOST_BTN} onClick={close}>
                取消
              </button>
            </div>
          </div>
        )}

        {phase === "running" && !step && (
          <div className="py-8 text-center text-[13px] text-[var(--color-ink-3)]">启动中…</div>
        )}
      </div>
    </div>
  );
}
