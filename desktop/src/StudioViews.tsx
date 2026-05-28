import { useEffect, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import * as studio from "./studio";
import {
  invalidateBridges,
  invalidateConversations,
  invalidatePersonas,
  qk,
  useBridges,
  useConversation,
  useConversationMessages,
  useConversations,
  useInboxes,
  usePersonas,
} from "./queries";
import {
  Card,
  DANGER_BTN,
  Empty,
  FormField,
  GHOST_BTN,
  INPUT_CLS,
  ModalActions,
  ModalShell,
  PRIMARY_BTN,
  SM_GHOST_BTN,
  SectionHeader,
} from "./ui";

type Notify = (text: string, kind?: "ok" | "err") => void;

// =====================================================================
// Takeover (home)
// =====================================================================

export function TakeoverView({ notify }: { notify: Notify }) {
  const qc = useQueryClient();
  const items = useConversations().data ?? [];
  const inboxes = useInboxes().data ?? [];
  const bridges = useBridges().data ?? [];
  const personas = usePersonas().data ?? [];
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const messages = useConversationMessages(selectedId).data ?? [];

  useEffect(() => {
    if (items.length === 0) return;
    if (!selectedId || !items.some((i) => i.conversation.id === selectedId)) {
      setSelectedId(items[0].conversation.id);
    }
  }, [items, selectedId]);

  const selected = items.find((i) => i.conversation.id === selectedId) ?? null;
  const selectedInbox = selected
    ? inboxes.find((i) => i.id === selected.inbox.id) ?? selected.inbox
    : null;
  const selectedBridge = selectedInbox
    ? bridges.find((b) => b.id === selectedInbox.bridge_id) ?? null
    : null;

  const patch = async (id: string, p: Parameters<typeof studio.updateConversation>[1]) => {
    try {
      await studio.updateConversation(id, p);
      invalidateConversations(qc);
      qc.invalidateQueries({ queryKey: qk.conversation(id) });
      qc.invalidateQueries({ queryKey: qk.messages(id) });
    } catch (e) {
      notify(String(e), "err");
    }
  };

  const taken = items.filter((i) => i.conversation.takeover);
  const available = items.filter((i) => !i.conversation.takeover);
  const inboxName = (id: string) => inboxes.find((i) => i.id === id)?.display_name ?? "未知账号";

  return (
    <>
      <SectionHeader title="接管" subtitle={`已接管 ${taken.length} · 未接管 ${available.length}`} />
      {items.length === 0 ? (
        <Empty>还没有任何会话。先在「设备」页把渠道接进来，收到消息后这里会自动出现。</Empty>
      ) : (
        <div className="grid grid-cols-[minmax(0,360px)_1fr] gap-4">
          <div className="flex flex-col gap-4">
            <ConvGroup title="已接管" count={taken.length}>
              {taken.length === 0 ? (
                <div className="px-1 py-1 text-[12px] text-[var(--color-ink-3)]">
                  还没接管任何会话，去下面「未接管」点接管。
                </div>
              ) : (
                taken.map((it) => (
                  <ConvRow
                    key={it.conversation.id}
                    item={it}
                    inboxName={inboxName(it.inbox.id)}
                    active={selectedId === it.conversation.id}
                    onSelect={() => setSelectedId(it.conversation.id)}
                  />
                ))
              )}
            </ConvGroup>
            <ConvGroup title="未接管" count={available.length}>
              {available.length === 0 ? (
                <div className="px-1 py-1 text-[12px] text-[var(--color-ink-3)]">暂无未接管会话。</div>
              ) : (
                available.map((it) => (
                  <div key={it.conversation.id} className="flex items-center gap-2">
                    <div className="min-w-0 flex-1">
                      <ConvRow
                        item={it}
                        inboxName={inboxName(it.inbox.id)}
                        active={selectedId === it.conversation.id}
                        onSelect={() => setSelectedId(it.conversation.id)}
                      />
                    </div>
                    <button className={PRIMARY_BTN} onClick={() => patch(it.conversation.id, { takeover: true })}>
                      接管
                    </button>
                  </div>
                ))
              )}
            </ConvGroup>
          </div>

          <Card className="min-h-[420px]">
            {!selected || !selectedInbox ? (
              <Empty>从左侧选择一个会话。</Empty>
            ) : (
              <ConversationDetail
                conversation={selected.conversation}
                inbox={selectedInbox}
                bridge={selectedBridge}
                messages={messages}
                personas={personas}
                onPatch={patch}
                notify={notify}
              />
            )}
          </Card>
        </div>
      )}
    </>
  );
}

function ConvGroup({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  const [open, setOpen] = useState(true);
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-md border border-[var(--color-line-soft)] bg-[var(--color-bg-raised)] px-3 py-2 text-left"
      >
        <span className={`text-[11px] text-[var(--color-ink-3)] transition-transform ${open ? "rotate-90" : ""}`}>▶</span>
        <span className="text-[13px] font-medium text-[var(--color-ink-1)]">{title}</span>
        <span className="ml-auto rounded-full bg-[var(--color-bg-elev)] px-2 py-0.5 text-[11px] text-[var(--color-ink-3)]">
          {count}
        </span>
      </button>
      {open && <div className="mt-2 flex flex-col gap-2">{children}</div>}
    </div>
  );
}

function ConvRow({
  item,
  inboxName,
  active,
  onSelect,
}: {
  item: studio.ConversationListItem;
  inboxName: string;
  active: boolean;
  onSelect: () => void;
}) {
  const c = item.conversation;
  return (
    <button
      onClick={onSelect}
      className={`w-full rounded-lg border px-3 py-2.5 text-left transition-colors ${
        active
          ? "border-[var(--color-brass)]/50 bg-[var(--color-brass)]/10"
          : "border-[var(--color-line-soft)] bg-[var(--color-bg-base)] hover:bg-[var(--color-bg-raised)]"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[13.5px] text-[var(--color-ink-1)]">{c.display_name}</span>
        {c.reply_policy === "autoreply" ? (
          <span className="shrink-0 rounded-full bg-[var(--color-ok)]/20 px-2 py-0.5 text-[10.5px] text-[var(--color-ok)]">
            自动回复
          </span>
        ) : (
          <span className="shrink-0 text-[11px] text-[var(--color-ink-4)]">{item.message_count}</span>
        )}
      </div>
      <div className="mt-1 truncate text-[12px] text-[var(--color-ink-3)]">
        {item.latest_message
          ? `${item.latest_message.from_self ? "我" : "对方"}：${item.latest_message.content}`
          : "暂无消息"}
      </div>
      <div className="mt-1 text-[10.5px] text-[var(--color-ink-4)]">{inboxName}</div>
    </button>
  );
}

function ConversationDetail({
  conversation,
  inbox,
  bridge,
  messages,
  personas,
  onPatch,
  notify,
}: {
  conversation: studio.ConversationSummary;
  inbox: studio.Inbox;
  bridge: studio.Bridge | null;
  messages: studio.Message[];
  personas: studio.PersonaSummary[];
  onPatch: (id: string, p: Parameters<typeof studio.updateConversation>[1]) => Promise<void>;
  notify: Notify;
}) {
  // card_md is per-selection detail with an edit draft, so it stays a plain
  // fetch (refetched whenever the selection changes), not a polled query.
  const { data: full } = useConversation(conversation.id);
  const [draftCard, setDraftCard] = useState("");
  const [savingCard, setSavingCard] = useState(false);
  const [cardJobBusy, setCardJobBusy] = useState(false);

  useEffect(() => {
    setDraftCard(full?.card_md ?? "");
  }, [conversation.id, full]);

  const currentCard = full?.card_md ?? "";
  const online = Boolean(bridge && bridge.status === "online");
  const canAutoreply = online && Boolean(conversation.persona_id);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3 border-b border-[var(--color-line-soft)] pb-3">
        <div className="min-w-0 flex-1">
          <div className="text-[16px] font-medium text-[var(--color-ink-1)]">{conversation.display_name}</div>
          <div className="mt-1 text-[11px] text-[var(--color-ink-3)]">
            来自 {inbox.display_name}（{inbox.platform}）
          </div>
        </div>
        {conversation.takeover ? (
          <button
            className={SM_GHOST_BTN}
            onClick={() => {
              if (!confirm(`取消接管「${conversation.display_name}」？取消后停止自动回复。`)) return;
              onPatch(conversation.id, { takeover: false });
            }}
          >
            取消接管
          </button>
        ) : (
          <button className={PRIMARY_BTN} onClick={() => onPatch(conversation.id, { takeover: true })}>
            接管
          </button>
        )}
      </div>

      {conversation.takeover && (
        <div className="flex flex-col gap-3 rounded-lg border border-[var(--color-line-soft)] bg-[var(--color-bg-raised)] p-3">
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2 text-[12px] text-[var(--color-ink-3)]">
              人设
              <select
                className={`${INPUT_CLS} w-auto py-1`}
                value={conversation.persona_id ?? ""}
                onChange={(e) => e.target.value && onPatch(conversation.id, { persona_id: e.target.value })}
              >
                <option value="">（未选）</option>
                {personas.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-[12px] text-[var(--color-ink-3)]">
              回复方式
              <select
                className={`${INPUT_CLS} w-auto py-1`}
                value={conversation.reply_policy}
                disabled={!canAutoreply && conversation.reply_policy !== "autoreply"}
                onChange={(e) => {
                  const next = e.target.value as "disabled" | "autoreply";
                  if (next === "autoreply") {
                    const hasCard = Boolean(currentCard.trim());
                    if (!conversation.persona_id || !hasCard) {
                      const missing = [conversation.persona_id ? null : "人设", hasCard ? null : "关系备注"]
                        .filter(Boolean)
                        .join(" 和 ");
                      if (!confirm(`还缺${missing}（两样都要才能自动回复）。仍开启吗？`)) return;
                    }
                  }
                  onPatch(conversation.id, { reply_policy: next });
                }}
              >
                <option value="disabled">我自己回</option>
                <option value="autoreply">自动回复</option>
              </select>
            </label>
          </div>
          {!canAutoreply && (
            <div className="text-[11px] text-[var(--color-warn)]">
              {!bridge && "— 该账号没有在线设备；"}
              {bridge && bridge.status !== "online" && `— 设备「${bridge.machine_id}」离线；`}
              {!conversation.persona_id && "— 还没选人设；"}
              当前无法自动回复。
            </div>
          )}

          <div>
            <div className="text-[12px] font-medium text-[var(--color-ink-2)]">关系备注</div>
            <div className="text-[11px] text-[var(--color-ink-3)]">简单写下你和这个人的关系，回复时会参考。</div>
          </div>
          <textarea
            className={`${INPUT_CLS} min-h-[90px] font-mono text-[12px]`}
            value={draftCard}
            onChange={(e) => setDraftCard(e.target.value)}
            placeholder={full ? "例如：去年送过我一袋茶叶，平时叫我「姐」" : "加载中…"}
            disabled={!full}
          />
          <div className="flex items-center justify-between gap-2">
            <button
              className={SM_GHOST_BTN}
              disabled={cardJobBusy}
              onClick={async () => {
                setCardJobBusy(true);
                try {
                  await studio.createDistillJob({ conversation_ids: [conversation.id], target_persona_id: null });
                  notify("已开始后台整理关系备注，稍后自动刷新。", "ok");
                } catch (e) {
                  notify(String(e), "err");
                } finally {
                  setCardJobBusy(false);
                }
              }}
            >
              {cardJobBusy ? "处理中…" : "自动整理关系备注"}
            </button>
            <button
              className={PRIMARY_BTN}
              disabled={!full || savingCard || draftCard === currentCard}
              onClick={async () => {
                setSavingCard(true);
                try {
                  await onPatch(conversation.id, { card_md: draftCard });
                } finally {
                  setSavingCard(false);
                }
              }}
            >
              {savingCard ? "保存中…" : "保存关系备注"}
            </button>
          </div>
        </div>
      )}

      {messages.length === 0 ? (
        <Empty>暂无消息。</Empty>
      ) : (
        <div className="flex max-h-[52vh] flex-col gap-2 overflow-auto pr-1">
          {messages.map((m) => (
            <div key={m.id} className={`flex ${m.from_self ? "justify-end" : "justify-start"}`}>
              <div className="max-w-[76%]">
                <div className={`mb-1 text-[10px] text-[var(--color-ink-4)] ${m.from_self ? "text-right" : ""}`}>
                  {m.from_self ? "我" : conversation.display_name} · {studio.formatDateTime(m.timestamp)}
                </div>
                <div
                  className={`whitespace-pre-wrap break-words rounded-xl border border-[var(--color-line-soft)] px-3 py-2 text-[13px] leading-relaxed ${
                    m.from_self ? "bg-[var(--color-brass)]/10" : "bg-[var(--color-bg-raised)]"
                  } text-[var(--color-ink-1)]`}
                >
                  {m.content}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// =====================================================================
// Personas
// =====================================================================

export function PersonasView({ notify }: { notify: Notify }) {
  const qc = useQueryClient();
  const personas = usePersonas().data ?? [];
  const [showCreate, setShowCreate] = useState(false);
  const [showAuto, setShowAuto] = useState(false);
  const [editing, setEditing] = useState<studio.PersonaSummary | null>(null);
  const done = () => invalidatePersonas(qc);

  return (
    <>
      <SectionHeader
        title="人设"
        subtitle="你可以扮演的人设"
        action={
          <div className="flex gap-2">
            <button className={PRIMARY_BTN} onClick={() => setShowAuto(true)}>
              ✶ 自动创建
            </button>
            <button className={GHOST_BTN} onClick={() => setShowCreate(true)}>
              + 手动新建
            </button>
          </div>
        }
      />
      {personas.length === 0 ? (
        <Empty>还没有人设。</Empty>
      ) : (
        <div className="flex flex-col gap-2.5">
          {personas.map((p) => (
            <div
              key={p.id}
              className="flex items-center justify-between gap-3 rounded-xl border border-[var(--color-line-soft)] bg-[var(--color-bg-base)] px-5 py-3.5"
            >
              <div>
                <div className="text-[14px] font-medium text-[var(--color-ink-1)]">{p.name}</div>
                <div className="mt-1 text-[11px] text-[var(--color-ink-3)]">{p.timezone}</div>
              </div>
              <div className="flex gap-2">
                <button className={SM_GHOST_BTN} onClick={() => setEditing(p)}>
                  编辑
                </button>
                <button
                  className={DANGER_BTN}
                  onClick={async () => {
                    if (!confirm("删除这个人设？如果还有会话在用，会删除失败。")) return;
                    try {
                      await studio.deletePersona(p.id);
                      done();
                    } catch (e) {
                      notify(String(e), "err");
                    }
                  }}
                >
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showCreate && (
        <CreatePersonaModal
          onClose={() => setShowCreate(false)}
          onSwitchToAuto={() => {
            setShowCreate(false);
            setShowAuto(true);
          }}
          onCreated={() => {
            setShowCreate(false);
            done();
          }}
          notify={notify}
        />
      )}
      {showAuto && (
        <AutoCreatePersonaModal
          onClose={() => setShowAuto(false)}
          onSubmitted={() => {
            setShowAuto(false);
            done();
            notify("已开始后台生成人设。", "ok");
          }}
          notify={notify}
        />
      )}
      {editing && (
        <EditPersonaModal
          persona={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            done();
          }}
          notify={notify}
        />
      )}
    </>
  );
}

function CreatePersonaModal({
  onClose,
  onCreated,
  onSwitchToAuto,
  notify,
}: {
  onClose: () => void;
  onCreated: () => void;
  onSwitchToAuto: () => void;
  notify: Notify;
}) {
  const [name, setName] = useState("");
  const [md, setMd] = useState("");
  const [tz, setTz] = useState("Asia/Shanghai");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await studio.createPersona({ name: name.trim(), persona_md: md || null, timezone: tz.trim() || "UTC" });
      onCreated();
    } catch (e) {
      notify(String(e), "err");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell title="新建人设" onClose={onClose}>
      <div className="mb-4 rounded-lg border border-[var(--color-brass)]/40 bg-[var(--color-brass)]/10 p-3">
        <div className="text-[13px] font-medium text-[var(--color-ink-1)]">不想自己写？可以从聊天记录自动创建</div>
        <button className={`${PRIMARY_BTN} mt-2`} onClick={onSwitchToAuto}>
          ✶ 用聊天记录自动创建
        </button>
      </div>
      <FormField label="名称">
        <input className={INPUT_CLS} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      </FormField>
      <FormField label="时区">
        <input className={INPUT_CLS} value={tz} onChange={(e) => setTz(e.target.value)} placeholder="Asia/Shanghai" />
      </FormField>
      <FormField label="人设描述（可不填）">
        <textarea className={`${INPUT_CLS} min-h-[200px] font-mono`} value={md} onChange={(e) => setMd(e.target.value)} />
      </FormField>
      <ModalActions onCancel={onClose} onConfirm={submit} confirmLabel={busy ? "创建中…" : "创建"} disabled={busy || !name.trim()} />
    </ModalShell>
  );
}

function AutoCreatePersonaModal({
  onClose,
  onSubmitted,
  notify,
}: {
  onClose: () => void;
  onSubmitted: () => void;
  notify: Notify;
}) {
  const [name, setName] = useState("");
  const [tz, setTz] = useState("Asia/Shanghai");
  const [items, setItems] = useState<studio.ConversationListItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    studio
      .getConversations()
      .then((next) => {
        const taken = next.filter((i) => i.conversation.takeover);
        setItems(taken);
        setSelected(new Set(taken.map((i) => i.conversation.id)));
      })
      .catch((e) => notify(String(e), "err"))
      .finally(() => setLoading(false));
  }, [notify]);

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const submit = async () => {
    if (!name.trim() || selected.size === 0) return;
    setBusy(true);
    try {
      const persona = await studio.createPersona({ name: name.trim(), persona_md: null, timezone: tz.trim() || "UTC" });
      await studio.createDistillJob({ conversation_ids: Array.from(selected), target_persona_id: persona.id });
      onSubmitted();
    } catch (e) {
      notify(String(e), "err");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell title="✶ 自动创建人设" onClose={onClose}>
      <div className="mb-3 text-[12px] text-[var(--color-ink-3)]">
        起个名字，选几段真实对话。AI 在后台读完后自动写出人设，并顺手生成每个被选中会话的关系备注。关掉窗口也没关系。
      </div>
      <FormField label="人设名称">
        <input className={INPUT_CLS} value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="例如：阿言" />
      </FormField>
      <FormField label="时区">
        <input className={INPUT_CLS} value={tz} onChange={(e) => setTz(e.target.value)} />
      </FormField>
      <div className="mb-1.5 text-[11px] text-[var(--color-ink-3)]">
        从这些对话里学习（已选 {selected.size} / {items.length}）
      </div>
      {loading ? (
        <Empty>正在加载已接管的会话…</Empty>
      ) : items.length === 0 ? (
        <Empty>还没有接管任何会话。先去「接管」页接管一些。</Empty>
      ) : (
        <div className="mb-2 flex max-h-[40vh] flex-col gap-1.5 overflow-auto">
          {items.map((it) => (
            <label
              key={it.conversation.id}
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-[13px] hover:bg-[var(--color-bg-raised)]"
            >
              <input type="checkbox" checked={selected.has(it.conversation.id)} onChange={() => toggle(it.conversation.id)} />
              <span className="flex-1 text-[var(--color-ink-1)]">{it.conversation.display_name}</span>
              <span className="font-mono text-[11px] text-[var(--color-ink-4)]">{it.message_count} 条</span>
            </label>
          ))}
        </div>
      )}
      <ModalActions
        onCancel={onClose}
        onConfirm={submit}
        confirmLabel={busy ? "提交中…" : `开始自动创建（${selected.size}）`}
        disabled={busy || loading || !name.trim() || selected.size === 0}
      />
    </ModalShell>
  );
}

function EditPersonaModal({
  persona,
  onClose,
  onSaved,
  notify,
}: {
  persona: studio.PersonaSummary;
  onClose: () => void;
  onSaved: () => void;
  notify: Notify;
}) {
  const [name, setName] = useState(persona.name);
  const [md, setMd] = useState("");
  const [tz, setTz] = useState(persona.timezone ?? "UTC");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    studio
      .getPersona(persona.id)
      .then((full) => {
        if (!alive) return;
        setMd(full.persona_md ?? "");
        setLoaded(true);
      })
      .catch((e) => notify(String(e), "err"));
    return () => {
      alive = false;
    };
  }, [persona.id, notify]);

  const submit = async () => {
    setBusy(true);
    try {
      await studio.updatePersona(persona.id, { name, persona_md: md, timezone: tz.trim() || "UTC" });
      onSaved();
    } catch (e) {
      notify(String(e), "err");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell title={`编辑人设 · ${persona.name}`} onClose={onClose}>
      <FormField label="名称">
        <input className={INPUT_CLS} value={name} onChange={(e) => setName(e.target.value)} />
      </FormField>
      <FormField label="时区">
        <input className={INPUT_CLS} value={tz} onChange={(e) => setTz(e.target.value)} />
      </FormField>
      <FormField label="人设描述">
        <textarea
          className={`${INPUT_CLS} min-h-[320px] font-mono`}
          value={md}
          onChange={(e) => setMd(e.target.value)}
          placeholder={loaded ? "" : "加载中…"}
          disabled={!loaded}
        />
      </FormField>
      <ModalActions onCancel={onClose} onConfirm={submit} confirmLabel={busy ? "保存中…" : "保存"} disabled={busy || !loaded} />
    </ModalShell>
  );
}

// =====================================================================
// Devices — local machine pinned + highlighted, others read-only
// =====================================================================

export function DevicesView({
  localMachineId,
  localSlot,
  notify,
}: {
  localMachineId: string | null;
  localSlot: ReactNode;
  notify: Notify;
}) {
  const qc = useQueryClient();
  const bridges = useBridges().data ?? [];
  const inboxes = useInboxes().data ?? [];

  const inboxesOf = (bridgeId: string) => inboxes.filter((i) => i.bridge_id === bridgeId);
  const others = bridges.filter((b) => b.machine_id !== localMachineId);

  return (
    <>
      <SectionHeader title="设备" subtitle="本机置顶，其余设备只读展示。" />

      <h2 className="mb-2 text-[13px] font-medium text-[var(--color-ink-2)]">本机</h2>
      <div className="mb-8 rounded-xl border border-[var(--color-brass)]/40 bg-[var(--color-brass)]/[0.06] p-5">
        {localSlot}
      </div>

      <h2 className="mb-2 text-[13px] font-medium text-[var(--color-ink-2)]">其他设备</h2>
      {others.length === 0 ? (
        <Empty>账号下没有其他设备。</Empty>
      ) : (
        <div className="flex flex-col gap-2.5">
          {others.map((b) => {
            const online = b.status === "online";
            return (
              <div key={b.id} className="rounded-xl border border-[var(--color-line-soft)] bg-[var(--color-bg-base)] p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${online ? "bg-[var(--color-ok)]" : "bg-[var(--color-ink-4)]"}`} />
                    <span className="text-[14px] font-medium text-[var(--color-ink-1)]">{b.machine_id}</span>
                    <span className="text-[11px] text-[var(--color-ink-4)]">{online ? "在线" : "离线"}</span>
                  </div>
                  <button
                    className={DANGER_BTN}
                    onClick={async () => {
                      if (!confirm(`移除设备「${b.machine_id}」？这台机器上的渠道会停止收发，需要重新接入。`)) return;
                      try {
                        await studio.deleteBridge(b.id);
                        invalidateBridges(qc);
                      } catch (e) {
                        notify(String(e), "err");
                      }
                    }}
                  >
                    移除
                  </button>
                </div>
                <div className="mt-1 text-[11px] text-[var(--color-ink-3)]">
                  最后在线 {studio.formatDateTime(b.last_seen_at)} · 接入 {inboxesOf(b.id).length} 个账号
                </div>
                {inboxesOf(b.id).length > 0 && (
                  <div className="mt-2.5 flex flex-col gap-1 border-t border-[var(--color-line-soft)] pt-2.5">
                    {inboxesOf(b.id).map((i) => (
                      <div key={i.id} className="text-[11px] text-[var(--color-ink-2)]">
                        {i.display_name}（{i.platform}）
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

// =====================================================================
// Change password (settings)
// =====================================================================

export function ChangePasswordModal({ onClose, notify }: { onClose: () => void; notify: Notify }) {
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [confirm2, setConfirm2] = useState("");
  const [busy, setBusy] = useState(false);
  const mismatch = confirm2.length > 0 && next !== confirm2;
  const canSubmit = Boolean(cur && next && next === confirm2);

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    try {
      await studio.changeOwnPassword({ current_password: cur, new_password: next });
      notify("密码已修改，请用新密码重新登录。", "ok");
      onClose();
    } catch (e) {
      notify(String(e), "err");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell title="修改密码" onClose={onClose} width="w-[420px]">
      <FormField label="当前密码">
        <input className={INPUT_CLS} type="password" value={cur} onChange={(e) => setCur(e.target.value)} autoFocus />
      </FormField>
      <FormField label="新密码">
        <input className={INPUT_CLS} type="password" value={next} onChange={(e) => setNext(e.target.value)} />
      </FormField>
      <FormField label="再输一次新密码">
        <input className={INPUT_CLS} type="password" value={confirm2} onChange={(e) => setConfirm2(e.target.value)} />
      </FormField>
      {mismatch && <div className="mb-2 text-[11px] text-[var(--color-danger)]">两次输入的新密码不一致</div>}
      <ModalActions onCancel={onClose} onConfirm={submit} confirmLabel={busy ? "保存中…" : "修改密码"} disabled={busy || !canSubmit} />
    </ModalShell>
  );
}
