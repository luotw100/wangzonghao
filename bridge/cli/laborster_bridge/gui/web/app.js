"use strict";

// =====================================================================
// Laborster Bridge — single-page GUI.
//
// Layout:
//   header (brand + account menu)
//   status strip  (only when logged in)
//   view: login | empty | channels  (picked from `account()` state)
//   log drawer
//   toast + modal overlays
//
// Polling: status + accounts every 2s, channels every 2s (cheap — pure
// store + snapshot reads). Logs are pushed (no poll) via window.pushLog.
// =====================================================================

const $ = (id) => document.getElementById(id);
const api = () => window.pywebview.api;

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}
function timeAgo(iso) {
  if (!iso) return "-";
  const d = (Date.now() - Date.parse(iso)) / 1000;
  if (Number.isNaN(d)) return "-";
  if (d < 60) return `${Math.floor(d)} 秒前`;
  if (d < 3600) return `${Math.floor(d / 60)} 分钟前`;
  if (d < 86400) return `${Math.floor(d / 3600)} 小时前`;
  return `${Math.floor(d / 86400)} 天前`;
}

// ---------------------------------------------------------------------
// toast
// ---------------------------------------------------------------------
let toastTimer = null;
function toast(text, cls = "") {
  const el = $("toast");
  el.textContent = text;
  el.className = cls;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 4000);
}
function renderResult(r, okFallback = "") {
  if (!r) return;
  if (r.error) { toast("✗ " + r.error, "err"); return false; }
  const msg = (r.lines && r.lines[0]) || okFallback;
  if (msg) toast(msg, "ok");
  return true;
}

// ---------------------------------------------------------------------
// state
// ---------------------------------------------------------------------
const state = {
  account: null,        // result of api.account()
  accounts: [],         // api.accounts()
  status: null,         // api.status()
  channels: [],         // api.channels()
  platforms: [],        // api.platforms()
};
const drawerState = {
  filters: { err: true, warn: true, ok: true, info: true },
  follow: true,
  newSinceCollapsed: 0,
};

// ---------------------------------------------------------------------
// log stream
// ---------------------------------------------------------------------
const MAX_LOG = 800;
function appendLog(ln) {
  const box = $("log");
  if (!box) return;
  if (!drawerState.filters[ln.level]) {
    // Always count toward the unread badge regardless of filter so the
    // user knows *something* arrived.
    if ($("drawer").classList.contains("collapsed")) bumpBadge();
    return;
  }
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
  const div = document.createElement("div");
  const lvl = ["err", "warn", "ok", "info"].includes(ln.level) ? "lvl-" + ln.level : "";
  div.innerHTML =
    `<span class="t">${esc(ln.t)}</span> ` +
    `<span class="src">[${esc(ln.src)}/</span>` +
    `<span class="${lvl}">${esc(ln.level)}]</span> ` +
    `<span class="${lvl}">${esc(ln.msg)}</span>`;
  box.appendChild(div);
  while (box.childElementCount > MAX_LOG) box.removeChild(box.firstChild);
  if (drawerState.follow && atBottom) box.scrollTop = box.scrollHeight;
  if ($("drawer").classList.contains("collapsed")) bumpBadge();
}
window.pushLog = appendLog;

function bumpBadge() {
  drawerState.newSinceCollapsed += 1;
  const b = $("drawer-badge");
  b.hidden = false;
  b.textContent = drawerState.newSinceCollapsed;
}
function clearBadge() {
  drawerState.newSinceCollapsed = 0;
  $("drawer-badge").hidden = true;
}

// ---------------------------------------------------------------------
// header / account menu
// ---------------------------------------------------------------------
function renderHeader() {
  const menu = $("acc-menu");
  if (!state.account) { menu.hidden = true; return; }
  menu.hidden = false;
  $("acc-trigger-label").textContent =
    state.account.display_name || state.account.account_id || "未登录";

  // dropdown body
  const list = $("acc-list");
  list.innerHTML = "";
  if (state.accounts.length === 0) {
    const empty = document.createElement("div");
    empty.className = "menu-item small";
    empty.textContent = "（暂无本机账号）";
    list.appendChild(empty);
  }
  for (const a of state.accounts) {
    const row = document.createElement("div");
    row.className = "acc-item";
    row.innerHTML =
      `<span class="check">${a.active ? "✓" : ""}</span>` +
      `<div class="info">` +
        `<div class="name">${esc(a.display_name || a.account_id)}</div>` +
        `<div class="sub">${esc(a.account_id)} · channels ${a.channel_count} · ${a.has_token ? "已登录" : "未登录"}</div>` +
      `</div>` +
      `<button class="rm">删除</button>`;
    row.onclick = async (ev) => {
      if (ev.target.classList.contains("rm")) return;
      if (a.active) return;
      closeAccountMenu();
      renderResult(await api().use_account(a.account_id), `已切换到 ${a.display_name || a.account_id}`);
      await refreshAll();
    };
    row.querySelector(".rm").onclick = async (ev) => {
      ev.stopPropagation();
      if (!confirm(`删除本机账号 ${a.display_name || a.account_id}？\n会清掉该账号的所有 channel 凭据与本地消息。`)) return;
      renderResult(await api().remove_account(a.account_id), "已删除");
      await refreshAll();
    };
    list.appendChild(row);
  }

  $("acc-studio").textContent = state.account.studio_url || "-";
  $("acc-machine").textContent = state.account.machine_id || "-";
  $("mi-studio-reset").hidden = !state.account.studio_url_overridden;
  $("mi-logout").hidden = !state.account.logged_in;
}

let menuOpen = false;
function openAccountMenu() {
  $("acc-dropdown").hidden = false;
  menuOpen = true;
}
function closeAccountMenu() {
  $("acc-dropdown").hidden = true;
  menuOpen = false;
}

// ---------------------------------------------------------------------
// status strip
// ---------------------------------------------------------------------
const STATUS_LABEL = {
  idle: { text: "空闲", dot: "" },
  connecting: { text: "连接中…", dot: "connecting" },
  online: { text: "桥接运行中", dot: "ok" },
  degraded: { text: "部分 channel 离线", dot: "warn" },
  needs_login: { text: "全部 channel 凭据失效", dot: "warn" },
  error401: { text: "Studio 会话失效，请重新登录", dot: "err" },
};
function renderStrip() {
  const strip = $("strip");
  const errRow = $("strip-err");
  if (!state.account || !state.account.logged_in) {
    strip.hidden = true;
    errRow.hidden = true;
    return;
  }
  strip.hidden = false;
  const s = state.status || {};
  const meta = STATUS_LABEL[s.status] || { text: s.status || "-", dot: "" };

  const dot = $("strip-dot");
  dot.className = "dot " + (meta.dot || (s.running ? "ok" : ""));
  $("strip-label").textContent = meta.text;

  const studio = $("strip-studio");
  studio.textContent = s.studio_url || "-";
  studio.className = "strip-studio" + (s.studio_url_overridden ? " override" : "");

  $("strip-in").textContent = s.in_count_5m || 0;
  $("strip-unsent").textContent = s.outbound_pending || 0;

  if (s.last_error) {
    errRow.hidden = false;
    errRow.textContent = s.last_error;
    if (s.status === "error401") {
      errRow.classList.add("clickable");
      errRow.onclick = () => openLoginModal();
    } else {
      errRow.classList.remove("clickable");
      errRow.onclick = null;
    }
  } else {
    errRow.hidden = true;
  }
}

// ---------------------------------------------------------------------
// views
// ---------------------------------------------------------------------
function showView(name) {
  for (const id of ["view-login", "view-empty", "view-channels"]) {
    $(id).hidden = id !== `view-${name}`;
  }
}
function pickView() {
  if (!state.account || !state.account.logged_in) return showView("login");
  if (!state.account.has_channels) return showView("empty");
  return showView("channels");
}

// ---------------------------------------------------------------------
// channel cards
// ---------------------------------------------------------------------
const CHAN_STATE = {
  online:      { dot: "ok",         label: "online" },
  connecting:  { dot: "connecting", label: "连接中…" },
  backoff:     { dot: "warn",       label: "退避重试中" },
  needs_login: { dot: "err",        label: "凭据失效" },
  removed:     { dot: "",           label: "已移除" },
  idle:        { dot: "",           label: "等待启动" },
};
function renderChannels() {
  const wrap = $("ch-list");
  wrap.innerHTML = "";
  $("ch-count").textContent = state.channels.length;
  for (const c of state.channels) {
    const meta = CHAN_STATE[c.state] || CHAN_STATE.idle;
    const card = document.createElement("div");
    card.className = "chan";

    const ident = c.self_id ? `${c.platform_label} · ${c.self_id}` : c.platform_label;
    const subBits = [];
    if (c.state === "online") subBits.push(`${c.conv_count} 会话 · ${meta.label}`);
    else subBits.push(meta.label);
    if (c.last_error) subBits.push(`<span class="err">${esc(c.last_error)}</span>`);

    card.innerHTML =
      `<span class="dot ${meta.dot}"></span>` +
      `<div class="info">` +
        `<div class="name">${esc(ident)}</div>` +
        `<div class="meta">${subBits.join(" · ")}</div>` +
      `</div>` +
      `<div class="actions"></div>`;

    const actions = card.querySelector(".actions");

    const reloginBtn = document.createElement("button");
    reloginBtn.className = "sm";
    reloginBtn.textContent = "重新登录";
    reloginBtn.onclick = () => openFlowModal(c.platform, { channelId: c.channel_id });
    actions.appendChild(reloginBtn);

    const rmBtn = document.createElement("button");
    rmBtn.className = "sm danger";
    rmBtn.textContent = "删除";
    rmBtn.onclick = async () => {
      if (!confirm(`删除 channel：${ident}？`)) return;
      rmBtn.disabled = true;
      renderResult(await api().channel_rm(c.channel_id), "已删除");
      await refreshAll();
    };
    actions.appendChild(rmBtn);

    wrap.appendChild(card);
  }
}

// ---------------------------------------------------------------------
// modals
// ---------------------------------------------------------------------
const modal = {
  open(title, contentEl, footEl) {
    $("modal-title").textContent = title;
    const c = $("modal-content"); c.innerHTML = ""; c.appendChild(contentEl);
    const f = $("modal-foot"); f.innerHTML = ""; if (footEl) f.appendChild(footEl);
    $("modal").hidden = false;
  },
  close() {
    $("modal").hidden = true;
    if (currentFlow.id) {
      // Best-effort cancel — server prunes anyway.
      api().flow_cancel(currentFlow.id).catch(() => {});
      currentFlow.id = null;
    }
    if (currentFlow.pollTimer) {
      clearTimeout(currentFlow.pollTimer);
      currentFlow.pollTimer = null;
    }
  },
};
$("modal-close").onclick = () => modal.close();
$("modal").querySelector(".modal-bg").onclick = () => modal.close();

// ---- Studio login modal -----
function openLoginModal() {
  const wrap = document.createElement("div");
  wrap.innerHTML = `
    <p class="hint" style="margin-bottom:14px">登录另一个 Studio 账号，或在 session 失效后重新登录。</p>
    <div class="field"><label>用户名</label><input id="m-login-user" type="text"></div>
    <div class="field"><label>密码</label><input id="m-login-pass" type="password"></div>
    <div id="m-login-err" class="flow-err" hidden></div>
  `;
  const foot = document.createElement("div");
  foot.innerHTML = `<button class="ghost" id="m-cancel">取消</button><button class="primary" id="m-submit">登录</button>`;
  modal.open("登录 Studio", wrap, foot);

  const onSubmit = async () => {
    const u = wrap.querySelector("#m-login-user").value.trim();
    const p = wrap.querySelector("#m-login-pass").value;
    if (!u || !p) return showFlowErr(wrap, "用户名和密码不能为空");
    const btn = foot.querySelector("#m-submit");
    btn.disabled = true; btn.textContent = "登录中…";
    const r = await api().login(u, p);
    if (r.error) {
      showFlowErr(wrap, r.error);
      btn.disabled = false; btn.textContent = "登录";
      return;
    }
    modal.close();
    toast(r.lines?.[0] || "登录成功", "ok");
    await refreshAll();
  };
  foot.querySelector("#m-cancel").onclick = () => modal.close();
  foot.querySelector("#m-submit").onclick = onSubmit;
  wrap.querySelector("#m-login-user").focus();
}

// ---- Studio URL override -----
function openStudioOverride() {
  const cur = state.account?.studio_url || "";
  const wrap = document.createElement("div");
  wrap.innerHTML = `
    <p class="hint" style="margin-bottom:12px">仅本次进程生效，重启恢复默认。切换后需要重新登录该地址的账号。</p>
    <div class="field"><label>Studio 地址</label>
      <input id="m-studio-url" type="text" placeholder="https://studio.example.com">
    </div>
    <div id="m-err" class="flow-err" hidden></div>
  `;
  wrap.querySelector("#m-studio-url").value = cur;
  const foot = document.createElement("div");
  foot.innerHTML = `<button class="ghost" id="m-cancel">取消</button><button class="primary" id="m-submit">应用</button>`;
  modal.open("覆盖 Studio 地址", wrap, foot);
  foot.querySelector("#m-cancel").onclick = () => modal.close();
  foot.querySelector("#m-submit").onclick = async () => {
    const v = wrap.querySelector("#m-studio-url").value.trim();
    if (!v) return showFlowErr(wrap, "地址不能为空");
    const r = await api().set_studio_url(v);
    if (r.error) return showFlowErr(wrap, r.error);
    modal.close();
    toast(r.lines?.[0] || "已切换", "ok");
    await refreshAll();
  };
}

function showFlowErr(wrap, msg) {
  const el = wrap.querySelector("#m-login-err") || wrap.querySelector("#m-err") || wrap.querySelector(".flow-err");
  if (!el) return;
  el.textContent = msg;
  el.hidden = false;
}

// ---- Flow modal: drives adapters.LoginFlow generically --------------
const currentFlow = { id: null, pollTimer: null };

async function openFlowModal(platform, opts = {}) {
  // For NEW channel: opts = {} → user picks platform first.
  // For RELOGIN: opts = { channelId } → platform fixed by caller.
  const isRelogin = opts.channelId != null;

  if (!platform) {
    // Show a platform picker first
    const wrap = document.createElement("div");
    const platOptions = state.platforms.map((p) =>
      `<option value="${esc(p.id)}">${esc(p.label)}</option>`).join("");
    wrap.innerHTML = `
      <div class="field"><label>平台</label>
        <select id="m-platform">${platOptions}</select>
      </div>
      <details class="advanced" id="m-adv" hidden>
        <summary>高级</summary>
        <div class="field"><label>base_url (可选 — chat 沙箱开发态用)</label>
          <input id="m-base-url" type="text" placeholder="留空则用默认地址">
        </div>
      </details>
      <div id="m-err" class="flow-err" hidden></div>
    `;
    const foot = document.createElement("div");
    foot.innerHTML = `<button class="ghost" id="m-cancel">取消</button><button class="primary" id="m-next">下一步</button>`;
    modal.open("绑定 channel — 选择平台", wrap, foot);

    const sel = wrap.querySelector("#m-platform");
    const adv = wrap.querySelector("#m-adv");
    const syncAdv = () => { adv.hidden = sel.value !== "chat"; };
    sel.onchange = syncAdv;
    syncAdv();

    foot.querySelector("#m-cancel").onclick = () => modal.close();
    foot.querySelector("#m-next").onclick = () => {
      const p = sel.value;
      const extras = {};
      const url = wrap.querySelector("#m-base-url").value.trim();
      if (url) extras.base_url = url;
      startFlow(p, extras, null);
    };
    return;
  }

  // Direct flow start (relogin) — base_url is pre-filled server-side.
  await startFlow(platform, {}, opts.channelId ?? null);
}

async function startFlow(platform, extras, channelId) {
  const r = await api().flow_begin(platform, extras, channelId);
  if (r.error) {
    toast("✗ " + r.error, "err");
    return;
  }
  currentFlow.id = r.flow_id;
  renderFlowStep(r.step, platform, r.channel_id);
}

function renderFlowStep(step, platform, channelId) {
  const isRelogin = channelId != null;
  const wrap = document.createElement("div");
  const foot = document.createElement("div");
  const title = isRelogin
    ? `重新登录 — ${labelOfPlatform(platform)}`
    : `绑定 channel — ${labelOfPlatform(platform)}`;

  if (step.kind === "prompt") {
    wrap.innerHTML = (step.error ? `<div class="flow-err">${esc(step.error)}</div>` : "") +
      step.fields.map((f) => `
        <div class="field">
          <label>${esc(f.label)}</label>
          <input data-name="${esc(f.name)}" type="${f.secret ? "password" : "text"}"
                 placeholder="${esc(f.placeholder)}" autocomplete="off">
        </div>`).join("") +
      `<div id="m-flow-err" class="flow-err" hidden></div>`;

    foot.innerHTML =
      `<button class="ghost" id="m-cancel">取消</button>` +
      `<button class="primary" id="m-submit">提交</button>`;

    modal.open(title, wrap, foot);
    const firstInput = wrap.querySelector("input"); if (firstInput) firstInput.focus();

    foot.querySelector("#m-cancel").onclick = () => modal.close();
    foot.querySelector("#m-submit").onclick = async () => {
      const answers = {};
      for (const inp of wrap.querySelectorAll("input[data-name]")) {
        answers[inp.dataset.name] = inp.value;
      }
      const btn = foot.querySelector("#m-submit");
      btn.disabled = true; btn.textContent = "提交中…";
      const r = await api().flow_submit(currentFlow.id, answers);
      if (r.error) {
        showFlowErr(wrap, r.error);
        btn.disabled = false; btn.textContent = "提交";
        return;
      }
      handleStep(r.step, platform, channelId);
    };
    return;
  }

  if (step.kind === "wait") {
    const qrHtml = step.qr_png_b64
      ? `<img class="qr" src="data:image/png;base64,${step.qr_png_b64}" alt="二维码">`
      : "";
    const linkHtml = step.open_url
      ? `<div class="qr-hint"><a href="${esc(step.open_url)}" target="_blank">${esc(step.open_url)}</a></div>` : "";
    const hintHtml = step.hint ? `<p class="qr-hint">${esc(step.hint)}</p>` : "";
    wrap.innerHTML = qrHtml + linkHtml + hintHtml +
      `<p class="qr-hint" style="margin-top:14px">等待确认…</p>`;
    foot.innerHTML = `<button class="ghost" id="m-cancel">取消</button>`;
    modal.open(title, wrap, foot);
    foot.querySelector("#m-cancel").onclick = () => modal.close();

    const delay = Math.max(500, step.poll_after_ms || 1500);
    currentFlow.pollTimer = setTimeout(async () => {
      if (!currentFlow.id) return;
      const r = await api().flow_poll(currentFlow.id);
      if (r.error) { toast("✗ " + r.error, "err"); modal.close(); return; }
      handleStep(r.step, platform, channelId);
    }, delay);
    return;
  }

  if (step.kind === "done") {
    // Finalize via persist
    persistFlow(platform, channelId);
    return;
  }

  if (step.kind === "failed") {
    toast("✗ " + (step.reason || "登录失败"), "err");
    modal.close();
    return;
  }
}

async function persistFlow(platform, channelId) {
  const r = await api().flow_persist(currentFlow.id, channelId);
  currentFlow.id = null;
  modal.close();
  if (r.error) { toast("✗ " + r.error, "err"); return; }
  toast(r.lines?.[0] || (channelId ? "已更新凭据" : "已绑定"), "ok");
  await refreshAll();
}

function handleStep(step, platform, channelId) {
  // The dispatcher: each step type either re-renders the modal, polls,
  // or terminates the flow.
  if (step.kind === "done") return persistFlow(platform, channelId);
  return renderFlowStep(step, platform, channelId);
}

function labelOfPlatform(id) {
  const p = state.platforms.find((p) => p.id === id);
  return p ? p.label : id;
}

// ---------------------------------------------------------------------
// data refresh
// ---------------------------------------------------------------------
async function refreshAll() {
  await Promise.all([
    api().account().then((a) => { state.account = a; }),
    api().accounts().then((a) => { state.accounts = a; }),
    api().status().then((s) => { state.status = s; }),
    api().channels().then((c) => { state.channels = c; }),
  ]);
  renderHeader();
  renderStrip();
  renderChannels();
  pickView();
}

async function pollLight() {
  // Cheaper poll — just the rapidly-changing bits. Account list barely
  // changes; refreshed via refreshAll on user actions.
  try {
    const [s, c, a] = await Promise.all([
      api().status(),
      api().channels(),
      api().account(),
    ]);
    state.status = s;
    state.channels = c;
    state.account = a;
    renderStrip();
    renderChannels();
    renderHeader();
    pickView();
  } catch (_) { /* window closing */ }
}

// ---------------------------------------------------------------------
// wiring
// ---------------------------------------------------------------------
function wire() {
  // Account menu trigger
  $("acc-trigger").onclick = (ev) => {
    ev.stopPropagation();
    if (menuOpen) closeAccountMenu(); else openAccountMenu();
  };
  document.addEventListener("click", (ev) => {
    if (!menuOpen) return;
    if (!ev.target.closest("#acc-menu")) closeAccountMenu();
  });

  // Menu items
  $("mi-add-account").onclick = () => { closeAccountMenu(); openLoginModal(); };
  $("mi-logout").onclick = async () => {
    closeAccountMenu();
    renderResult(await api().logout(), "已登出");
    await refreshAll();
  };
  $("mi-studio-set").onclick = () => { closeAccountMenu(); openStudioOverride(); };
  $("mi-studio-reset").onclick = async () => {
    closeAccountMenu();
    renderResult(await api().reset_studio_url(), "已恢复默认");
    await refreshAll();
  };

  // First-time login (in-view, not modal)
  $("btn-login").onclick = async () => {
    const u = $("login-user").value.trim();
    const p = $("login-pass").value;
    if (!u || !p) { toast("用户名和密码不能为空", "err"); return; }
    const btn = $("btn-login");
    btn.disabled = true; btn.textContent = "登录中…";
    try {
      const r = await api().login(u, p);
      if (!renderResult(r, "登录成功")) return;
      $("login-pass").value = "";
      await refreshAll();
    } finally { btn.disabled = false; btn.textContent = "登录"; }
  };

  // + 绑定 channel (two entry points)
  $("btn-empty-add").onclick = () => openFlowModal(null);
  $("btn-ch-add").onclick = () => openFlowModal(null);

  // Drawer
  $("drawer-toggle").onclick = (ev) => {
    if (ev.target.closest("#btn-opendir")) return; // inner button
    const d = $("drawer");
    if (d.classList.contains("collapsed")) {
      d.classList.remove("collapsed"); d.classList.add("open");
      clearBadge();
      requestAnimationFrame(() => {
        const box = $("log"); box.scrollTop = box.scrollHeight;
      });
    } else {
      d.classList.remove("open"); d.classList.add("collapsed");
    }
  };
  for (const lvl of ["err", "warn", "ok", "info"]) {
    $("filt-" + lvl).onchange = (ev) => {
      drawerState.filters[lvl] = ev.target.checked;
    };
  }
  $("follow-end").onchange = (ev) => { drawerState.follow = ev.target.checked; };
  $("btn-clear").onclick = () => { $("log").innerHTML = ""; };
  $("btn-opendir").onclick = async (ev) => {
    ev.stopPropagation();
    await api().open_data_dir();
  };

  // Esc closes modal
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !$("modal").hidden) modal.close();
  });
}

// ---------------------------------------------------------------------
// boot
// ---------------------------------------------------------------------
async function boot() {
  wire();
  state.platforms = await api().platforms();
  try {
    for (const ln of await api().logs(200)) appendLog(ln);
  } catch (_) { /* stream will catch up */ }
  await refreshAll();
  setInterval(pollLight, 2000);
}

window.addEventListener("pywebviewready", boot);
