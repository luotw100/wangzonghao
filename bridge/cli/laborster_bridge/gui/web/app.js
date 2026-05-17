"use strict";

const $ = (id) => document.getElementById(id);
const api = () => window.pywebview.api;

function esc(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

let msgTimer = null;
function showMsg(text, cls) {
  const el = $("msg");
  el.textContent = text || "";
  el.className = cls || "";
  if (msgTimer) clearTimeout(msgTimer);
  if (text) msgTimer = setTimeout(() => { el.textContent = ""; el.className = ""; }, 6000);
}

function renderResult(r) {
  if (!r) return;
  if (r.error) { showMsg("✗ " + r.error, "err"); return; }
  const lines = r.lines || [];
  if (lines.length) showMsg(lines[0], "ok");
}

// --- log stream (pushed from Python) ---
const MAX_LOG = 500;
function appendLog(ln) {
  const box = $("log");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 24;
  const div = document.createElement("div");
  const lvl = ["err", "warn", "ok"].includes(ln.level) ? "lvl-" + ln.level : "";
  div.innerHTML =
    `<span class="t">${esc(ln.t)}</span> ` +
    `<span class="src">[${esc(ln.src)}/</span>` +
    `<span class="${lvl}">${esc(ln.level)}]</span> ` +
    `<span class="${lvl}">${esc(ln.msg)}</span>`;
  box.appendChild(div);
  while (box.childElementCount > MAX_LOG) box.removeChild(box.firstChild);
  if (atBottom) box.scrollTop = box.scrollHeight;
}
window.pushLog = appendLog;

// --- views ---
async function loadAccount() {
  const a = await api().account();
  $("account-logged-out").hidden = a.logged_in;
  $("account-logged-in").hidden = !a.logged_in;
  if (a.logged_in) {
    $("acc-user").textContent = a.username || "-";
    $("acc-bridge").textContent = a.bridge_id || "-";
    $("acc-machine").textContent = a.machine_id || "-";
  } else {
    $("login-user").value = "";
    $("login-pass").value = "";
  }
}

async function loadChannels() {
  const list = await api().channel_list();
  const ul = $("channel-list");
  ul.innerHTML = "";
  if (!list.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "（无 channel）";
    ul.appendChild(li);
    return;
  }
  for (const c of list) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = c.username;
    const btn = document.createElement("button");
    btn.textContent = "删除";
    btn.onclick = async () => {
      if (!confirm(`删除 channel：${c.username}？`)) return;
      btn.disabled = true;
      renderResult(await api().channel_rm(c.index));
      await refreshAll();
    };
    li.appendChild(name);
    li.appendChild(btn);
    ul.appendChild(li);
  }
}

async function pollStatus() {
  let s;
  try { s = await api().status(); } catch (e) { return; }
  const snap = s.snapshot || {};
  const running = s.running;
  const pill = $("pill");
  pill.textContent = running ? "运行中" : "未运行";
  pill.className = "pill " + (running ? "on" : "off");
  $("st-status").textContent = (snap.status || "idle") + (running ? "" : "（daemon 未运行）");
  $("st-studio").textContent = snap.studio_url || "-";
  $("st-in").textContent = snap.in_count_5m || 0;
  $("st-unsent").textContent = snap.outbound_pending || 0;
  const errRow = $("st-err-row");
  if (snap.last_error) { errRow.hidden = false; $("st-err").textContent = snap.last_error; }
  else errRow.hidden = true;
  const cc = $("st-channels");
  cc.innerHTML = "";
  for (const c of snap.channels || []) {
    const d = document.createElement("div");
    d.className = "chan-line";
    d.innerHTML =
      `<span class="dot ${c.online ? "on" : "off"}"></span>` +
      `${esc(c.handle)} · self=${esc(c.platform_self_id || "-")} · ` +
      `peers=${c.peers_count || 0} · ${c.online ? "online" : "offline"}`;
    cc.appendChild(d);
  }
}

async function refreshAll() {
  await loadAccount();
  await loadChannels();
  await pollStatus();
}

// --- actions ---
function wire() {
  $("btn-login").onclick = async () => {
    const u = $("login-user").value.trim();
    const p = $("login-pass").value;
    if (!u || !p) { showMsg("用户名和密码不能为空", "err"); return; }
    const btn = $("btn-login");
    btn.disabled = true; btn.textContent = "登录中…";
    try {
      renderResult(await api().login(u, p));
      $("login-pass").value = "";
      await refreshAll();
    } finally { btn.disabled = false; btn.textContent = "登录"; }
  };

  $("btn-logout").onclick = async () => {
    renderResult(await api().logout());
    await refreshAll();
  };

  $("btn-ch-add").onclick = async () => {
    const u = $("ch-user").value.trim();
    const p = $("ch-pass").value;
    if (!u || !p) { showMsg("用户名和密码不能为空", "err"); return; }
    const btn = $("btn-ch-add");
    btn.disabled = true; btn.textContent = "添加中…";
    try {
      renderResult(await api().channel_add(u, p));
      $("ch-user").value = ""; $("ch-pass").value = "";
      await refreshAll();
    } finally { btn.disabled = false; btn.textContent = "添加 channel"; }
  };

  $("btn-opendir").onclick = async () => { await api().open_data_dir(); };
}

async function boot() {
  wire();
  try {
    for (const ln of await api().logs(200)) appendLog(ln);
  } catch (e) { /* stream will catch up */ }
  await refreshAll();
  setInterval(pollStatus, 2000);
}

window.addEventListener("pywebviewready", boot);
