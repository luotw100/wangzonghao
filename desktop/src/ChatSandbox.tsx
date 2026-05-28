import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import * as chat from "./chat";
import { authMe } from "./studio";
import { GHOST_BTN, INPUT_CLS, ModalShell, PRIMARY_BTN, SM_GHOST_BTN } from "./ui";

const INITIAL_LIMIT = 50;
type Notify = (text: string, kind?: "ok" | "err") => void;
type Perspective = "self" | "contact";

// Global in-memory cache (NOT disk): switching conversations seeds instantly
// from here and the long-poll resumes from the cached lastId instead of
// refetching the whole window. Lives at module scope so it survives the
// ChatThread unmount/remount that a tab switch causes.
const msgCache = new Map<string, chat.Message[]>();
const lastIdCache = new Map<string, number>();

function maxId(items: chat.Message[]): number {
  return items.reduce((m, x) => (x.id > m ? x.id : m), 0);
}

function previewText(m: chat.Message | undefined): string {
  if (!m) return "暂无消息";
  if (m.msg_type === "text") return m.content;
  return { image: "[图片]", audio: "[语音]", video: "[视频]", file: "[文件]" }[m.msg_type] ?? "";
}

function useChatMessages(conversationId: string, onLatest: (convId: string, m: chat.Message | undefined) => void) {
  const [messages, setMessages] = useState<chat.Message[]>(() => msgCache.get(conversationId) ?? []);
  const [hasMore, setHasMore] = useState(false);
  const oldestId = useRef<number | null>(null);

  const write = useCallback(
    (next: chat.Message[]) => {
      msgCache.set(conversationId, next);
      lastIdCache.set(conversationId, maxId(next));
      onLatest(conversationId, next[next.length - 1]);
    },
    [conversationId, onLatest],
  );

  const loadOlder = useCallback(async () => {
    if (oldestId.current == null) return;
    const older = await chat.getMessagesBefore(conversationId, oldestId.current, INITIAL_LIMIT);
    if (older.length > 0) {
      oldestId.current = older[0].id;
      setMessages((prev) => {
        const seen = new Set(prev.map((m) => m.id));
        const fresh = older.filter((m) => !seen.has(m.id));
        const next = fresh.length ? [...fresh, ...prev] : prev;
        msgCache.set(conversationId, next);
        return next;
      });
    }
    setHasMore(older.length === INITIAL_LIMIT);
  }, [conversationId]);

  useEffect(() => {
    let cancelled = false;
    const ctrl = new AbortController();

    const seed = msgCache.get(conversationId) ?? [];
    setMessages(seed);
    oldestId.current = seed.length ? seed[0].id : null;
    setHasMore(seed.length >= INITIAL_LIMIT);

    (async () => {
      if (seed.length === 0) {
        try {
          const initial = await chat.getMessagesBefore(conversationId, undefined, INITIAL_LIMIT);
          if (cancelled) return;
          setMessages(initial);
          oldestId.current = initial.length ? initial[0].id : null;
          setHasMore(initial.length === INITIAL_LIMIT);
          write(initial);
        } catch {
          return;
        }
      }
      while (!cancelled) {
        try {
          const from = lastIdCache.get(conversationId) ?? 0;
          const incoming = await chat.getMessagesAfter(conversationId, from, ctrl.signal);
          if (cancelled) return;
          if (incoming.length) {
            setMessages((prev) => {
              const seen = new Set(prev.map((m) => m.id));
              const fresh = incoming.filter((m) => !seen.has(m.id));
              if (!fresh.length) return prev;
              const next = [...prev, ...fresh].sort((a, b) => a.id - b.id);
              write(next);
              return next;
            });
          }
        } catch {
          await new Promise((r) => setTimeout(r, 1500));
        }
      }
    })();

    return () => {
      cancelled = true;
      ctrl.abort(); // kill the in-flight long-poll immediately on switch
    };
  }, [conversationId, write]);

  return { messages, hasMore, loadOlder };
}

export function ChatSandbox({ notify }: { notify: Notify }) {
  const [account, setAccount] = useState<chat.Account | null>(null);
  const [conversations, setConversations] = useState<chat.Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [previews, setPreviews] = useState<Record<string, chat.Message | undefined>>({});
  const primed = useRef<Set<string>>(new Set());

  const setPreview = useCallback((convId: string, m: chat.Message | undefined) => {
    setPreviews((prev) => (prev[convId] === m ? prev : { ...prev, [convId]: m }));
  }, []);

  useEffect(() => {
    authMe()
      .then((a) => setAccount({ id: a.id, username: a.username, nickname: a.display_name || a.username }))
      .catch((e) => notify(String(e), "err"));
  }, [notify]);

  const reload = useCallback(async () => {
    try {
      setConversations(await chat.listConversations());
    } catch (e) {
      notify(String(e), "err");
    }
  }, [notify]);

  useEffect(() => {
    reload();
    const t = setInterval(reload, 5000);
    return () => clearInterval(t);
  }, [reload]);

  // Prime each conversation's last-message preview exactly once (cheap 1-row
  // fetch), so the sidebar shows previews without visiting every tab.
  useEffect(() => {
    for (const c of conversations) {
      if (primed.current.has(c.id)) continue;
      primed.current.add(c.id);
      const cached = msgCache.get(c.id);
      if (cached && cached.length) {
        setPreview(c.id, cached[cached.length - 1]);
        continue;
      }
      chat
        .getMessagesBefore(c.id, undefined, 1)
        .then((ms) => setPreview(c.id, ms[ms.length - 1]))
        .catch(() => {});
    }
  }, [conversations, setPreview]);

  useEffect(() => {
    if (!activeId && conversations.length) setActiveId(conversations[0].id);
  }, [conversations, activeId]);

  const active = conversations.find((c) => c.id === activeId) ?? null;

  return (
    <div className="grid h-screen grid-cols-[280px_1fr] bg-[var(--color-bg-deep)]">
      <aside className="flex flex-col border-r border-[var(--color-line-soft)] bg-[var(--color-bg-base)]">
        <div className="flex items-center justify-between border-b border-[var(--color-line-soft)] px-4 py-3.5">
          <div>
            <div className="text-[14px] font-medium text-[var(--color-ink-1)]">聊天沙箱</div>
            <div className="text-[11px] text-[var(--color-ink-4)]">内存态 · 重启后重新拉取</div>
          </div>
          <button className={SM_GHOST_BTN} onClick={() => setShowNew(true)}>
            + 联系人
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {conversations.length === 0 ? (
            <div className="px-4 py-6 text-center text-[12.5px] text-[var(--color-ink-3)]">
              还没有联系人，点右上「+ 联系人」新建。
            </div>
          ) : (
            conversations.map((c) => {
              const activeRow = c.id === activeId;
              const remark = c.contact.remark_name;
              const nickname = c.contact.nickname;
              return (
                <button
                  key={c.id}
                  onClick={() => setActiveId(c.id)}
                  className={`flex w-full items-center gap-3 px-4 py-3 text-left transition-colors ${
                    activeRow ? "bg-[var(--color-bg-elev)]" : "hover:bg-[var(--color-bg-raised)]"
                  }`}
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--color-brass)]/15 text-[13px] font-medium text-[var(--color-brass)]">
                    {(remark || nickname).slice(0, 1)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline gap-1.5">
                      <span className="truncate text-[13.5px] text-[var(--color-ink-1)]">{remark || nickname}</span>
                      {remark && remark !== nickname && (
                        <span className="shrink-0 text-[11px] text-[var(--color-ink-4)]">（{nickname}）</span>
                      )}
                    </div>
                    <div className="truncate text-[11.5px] text-[var(--color-ink-4)]">{previewText(previews[c.id])}</div>
                  </div>
                </button>
              );
            })
          )}
        </div>
      </aside>

      {active && account ? (
        <ChatThread account={account} conversation={active} notify={notify} onLatest={setPreview} />
      ) : (
        <div className="flex items-center justify-center text-[13px] text-[var(--color-ink-3)]">
          {account ? "从左侧选择一个联系人" : "加载账号中…"}
        </div>
      )}

      {showNew && account && (
        <NewContactModal
          onClose={() => setShowNew(false)}
          onCreated={async (contactId) => {
            setShowNew(false);
            const convs = await chat.listConversations();
            setConversations(convs);
            const conv = convs.find((c) => c.contact_id === contactId);
            if (conv) setActiveId(conv.id);
          }}
          notify={notify}
        />
      )}
    </div>
  );
}

function ChatThread({
  account,
  conversation,
  notify,
  onLatest,
}: {
  account: chat.Account;
  conversation: chat.Conversation;
  notify: Notify;
  onLatest: (convId: string, m: chat.Message | undefined) => void;
}) {
  const { messages, hasMore, loadOlder } = useChatMessages(conversation.id, onLatest);
  const [perspective, setPerspective] = useState<Perspective>("self");
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const atBottom = useRef(true);
  const prevHeight = useRef<number | null>(null); // set right before prepending older

  // Landing on a conversation should sit at the latest message.
  useEffect(() => {
    atBottom.current = true;
    prevHeight.current = null;
  }, [conversation.id]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  };

  // After messages change: if we just prepended older history, keep the
  // viewport anchored (no jump); otherwise only follow to the bottom when the
  // user was already there.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (prevHeight.current != null) {
      el.scrollTop += el.scrollHeight - prevHeight.current;
      prevHeight.current = null;
    } else if (atBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  const handleLoadOlder = () => {
    const el = scrollRef.current;
    prevHeight.current = el ? el.scrollHeight : null;
    loadOlder();
  };

  const senderId = () => (perspective === "self" ? null : conversation.contact_id);

  const send = async () => {
    const content = text.trim();
    if (!content || sending) return;
    setSending(true);
    try {
      await chat.sendMessage(conversation.id, { sender_id: senderId(), msg_type: "text", content });
      setText("");
    } catch (e) {
      notify(String(e), "err");
    } finally {
      setSending(false);
    }
  };

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setSending(true);
    try {
      const key = await chat.uploadFile(file);
      await chat.sendMessage(conversation.id, {
        sender_id: senderId(),
        msg_type: chat.inferMediaType(file.type || ""),
        content: key,
      });
    } catch (err) {
      notify(String(err), "err");
    } finally {
      setSending(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  };

  const speakingAs = perspective === "self" ? account.nickname : chat.contactName(conversation.contact);
  const c = conversation.contact;

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center gap-2 border-b border-[var(--color-line-soft)] px-6 py-3.5">
        <span className="text-[15px] font-medium text-[var(--color-ink-1)]">{c.remark_name || c.nickname}</span>
        {c.remark_name && c.remark_name !== c.nickname && (
          <span className="text-[12px] text-[var(--color-ink-4)]">网名：{c.nickname}</span>
        )}
      </header>

      <div ref={scrollRef} onScroll={onScroll} className="flex-1 overflow-y-auto px-6 py-4">
        {hasMore && (
          <div className="mb-3 text-center">
            <button className={SM_GHOST_BTN} onClick={handleLoadOlder}>
              查看更早消息
            </button>
          </div>
        )}
        <div className="flex flex-col gap-2">
          {messages.map((m) => {
            const isSelf = m.sender_id === null;
            const onRight = isSelf === (perspective === "self");
            return (
              <div key={m.id} className={`flex ${onRight ? "justify-end" : "justify-start"}`}>
                <div className="max-w-[70%]">
                  <div className={`mb-1 text-[10px] text-[var(--color-ink-4)] ${onRight ? "text-right" : ""}`}>
                    {isSelf ? account.nickname : chat.contactName(conversation.contact)}
                  </div>
                  <MessageBody message={m} onRight={onRight} />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <footer className="border-t border-[var(--color-line-soft)] px-6 py-3">
        <div className="mb-2 flex items-center gap-2">
          <span className="text-[11px] text-[var(--color-ink-4)]">以</span>
          <div className="flex overflow-hidden rounded-md border border-[var(--color-line)]">
            <button
              className={`px-3 py-1 text-[12px] ${perspective === "self" ? "bg-[var(--color-brass)] text-[#1b1d23]" : "text-[var(--color-ink-2)]"}`}
              onClick={() => setPerspective("self")}
            >
              我（{account.nickname}）
            </button>
            <button
              className={`px-3 py-1 text-[12px] ${perspective === "contact" ? "bg-[var(--color-brass)] text-[#1b1d23]" : "text-[var(--color-ink-2)]"}`}
              onClick={() => setPerspective("contact")}
            >
              对方（{chat.contactName(conversation.contact)}）
            </button>
          </div>
          <span className="text-[11px] text-[var(--color-ink-4)]">身份发送 · Enter 发送</span>
        </div>
        <div className="flex items-end gap-2">
          <input ref={fileRef} type="file" className="hidden" onChange={onFile} disabled={sending} />
          <button className={GHOST_BTN} onClick={() => fileRef.current?.click()} disabled={sending} title="发送媒体">
            📎
          </button>
          <textarea
            className={`${INPUT_CLS} max-h-32 min-h-[44px] flex-1 resize-none`}
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
            placeholder={`以 ${speakingAs} 的身份说点什么…`}
            disabled={sending}
          />
          <button className={PRIMARY_BTN} onClick={send} disabled={!text.trim() || sending}>
            {sending ? "…" : "发送"}
          </button>
        </div>
      </footer>
    </div>
  );
}

function MessageBody({ message: m, onRight }: { message: chat.Message; onRight: boolean }) {
  const bubble = `rounded-xl border border-[var(--color-line-soft)] px-3 py-2 text-[13px] leading-relaxed ${
    onRight ? "bg-[var(--color-brass)]/15" : "bg-[var(--color-bg-raised)]"
  } text-[var(--color-ink-1)]`;
  if (m.msg_type === "text") {
    return <div className={`${bubble} whitespace-pre-wrap break-words`}>{m.content}</div>;
  }
  if (m.msg_type === "image") {
    return <img src={chat.mediaUrl(m.content)} alt="图片" className="max-h-64 rounded-xl" loading="lazy" />;
  }
  if (m.msg_type === "audio") {
    return <audio src={chat.mediaUrl(m.content)} controls className="max-w-full" />;
  }
  if (m.msg_type === "video") {
    return <video src={chat.mediaUrl(m.content)} controls className="max-h-64 rounded-xl" />;
  }
  return (
    <a className={`${bubble} underline`} href={chat.mediaUrl(m.content)} target="_blank" rel="noreferrer">
      文件
    </a>
  );
}

function NewContactModal({
  onClose,
  onCreated,
  notify,
}: {
  onClose: () => void;
  onCreated: (contactId: string) => void;
  notify: Notify;
}) {
  const [nickname, setNickname] = useState("");
  const [remark, setRemark] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!nickname.trim() || busy) return;
    setBusy(true);
    try {
      const c = await chat.createContact({ nickname: nickname.trim(), remark_name: remark.trim() || undefined });
      onCreated(c.id);
    } catch (e) {
      notify(String(e), "err");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ModalShell title="新建联系人" onClose={onClose} width="w-[380px]">
      <label className="mb-1 block text-[12px] text-[var(--color-ink-3)]">网名</label>
      <input className={INPUT_CLS} value={nickname} onChange={(e) => setNickname(e.target.value)} autoFocus />
      <label className="mb-1 mt-4 block text-[12px] text-[var(--color-ink-3)]">备注名（可选）</label>
      <input className={INPUT_CLS} value={remark} onChange={(e) => setRemark(e.target.value)} />
      <div className="mt-5 flex justify-end gap-3">
        <button className={GHOST_BTN} onClick={onClose}>
          取消
        </button>
        <button className={PRIMARY_BTN} onClick={submit} disabled={busy || !nickname.trim()}>
          {busy ? "创建中…" : "创建"}
        </button>
      </div>
    </ModalShell>
  );
}
