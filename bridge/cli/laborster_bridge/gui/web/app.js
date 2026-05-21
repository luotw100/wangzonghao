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

// ---- tab routing ----
function switchTab(name) {
  for (const b of document.querySelectorAll(".tab"))
    b.classList.toggle("active", b.dataset.tab === name);
  for (const p of document.querySelectorAll(".page"))
    p.classList.toggle("active", p.id === "page-" + name);
}

// ---- log stream ----
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

// ---- state shared across renders ----
let savedChannels = [];      // [{index, platform, self_id, label}]
let liveByKey = {};          // "platform/self_id" -> {online, conv_count}

function renderChannels() {
  const wrap = $("ch-list");
  wrap.innerHTML = "";
  $("ch-count").textContent = savedChannels.length;
  $("ch-empty").hidden = savedChannels.length > 0;

  for (const c of savedChannels) {
    const key = `${c.platform}/${c.self_id || "-"}`;
    const live = liveByKey[key] || {};
    const online = !!live.online;
    const card = document.createElement("div");
    card.className = "chan";
    card.innerHTML =
      `<span class="dot ${online ? "on" : "off"}"></span>` +
      `<div class="info">` +
        `<div class="name">${esc(c.label)}</div>` +
        `<div class="meta">convs ${live.conv_count || 0}</div>` +
      `</div>` +
      `<span class="badge ${online ? "on" : ""}">${online ? "online" : "offline"}</span>`;
    const del = document.createElement("button");
    del.className = "danger sm";
    del.textContent = "删除";
    del.onclick = async () => {
      if (!confirm(`删除 channel：${c.label}？`)) return;
      del.disabled = true;
      renderResult(await api().channel_rm(c.index));
      await refreshAll();
    };
    card.appendChild(del);
    wrap.appendChild(card);
  }
}

async function loadChannels() {
  savedChannels = await api().channel_list();
  renderChannels();
}

async function loadAccount() {
  const a = await api().account();
  $("account-out").hidden = a.logged_in;
  $("account-in").hidden = !a.logged_in;
  if (a.logged_in) {
    $("acc-user").textContent = a.username || "-";
    $("acc-bridge").textContent = a.bridge_id || "-";
    $("acc-machine").textContent = a.machine_id || "-";
  } else {
    $("login-user").value = "";
    $("login-pass").value = "";
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

  $("st-run").textContent = running ? "运行中" : "未运行";
  $("st-status").textContent = snap.status || "idle";
  $("st-in").textContent = snap.in_count_5m || 0;
  $("st-unsent").textContent = snap.outbound_pending || 0;
  $("st-studio").textContent = snap.studio_url || "-";
  const errRow = $("st-err-row");
  if (snap.last_error) { errRow.hidden = false; $("st-err").textContent = snap.last_error; }
  else errRow.hidden = true;

  liveByKey = {};
  for (const c of snap.channels || []) {
    liveByKey[`${c.platform}/${c.platform_self_id || "-"}`] = c;
  }
  renderChannels();
}

async function refreshAll() {
  await loadAccount();
  await loadChannels();
  await pollStatus();
}

function wire() {
  for (const b of document.querySelectorAll(".tab"))
    b.onclick = () => switchTab(b.dataset.tab);

  $("btn-ch-toggle").onclick = () => {
    const box = $("ch-add");
    box.hidden = !box.hidden;
    if (!box.hidden) $("ch-user").focus();
  };
  $("btn-ch-cancel").onclick = () => {
    $("ch-add").hidden = true;
    $("ch-user").value = ""; $("ch-pass").value = "";
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
      $("ch-add").hidden = true;
      await refreshAll();
    } finally { btn.disabled = false; btn.textContent = "添加"; }
  };

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
