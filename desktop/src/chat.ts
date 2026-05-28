// Chat sandbox client (route 2). Messages/contacts go through the sidecar's
// /studio/chat/* JSON proxy; media is served by the sidecar's binary proxy
// with the local token in the query; uploads are proxied through the sidecar
// to S3 (never directly from the renderer). Nothing is cached to disk — the
// UI holds everything in React state only.

function base(): string {
  const b = window.bridge;
  if (!b) throw new Error("bridge preload missing");
  return b.baseUrl;
}
function token(): string {
  return window.bridge?.token ?? "";
}

function creq<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Authorization: `Bearer ${token()}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  return fetch(base() + "/studio/chat" + path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }).then(async (res) => {
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const j = await res.json();
        if (j?.error) detail = typeof j.error === "string" ? j.error : JSON.stringify(j.error);
      } catch {
        /* keep status */
      }
      throw new Error(detail);
    }
    const t = await res.text();
    return (t ? JSON.parse(t) : null) as T;
  });
}

// ---- types -----------------------------------------------------------

export interface Account {
  id: string;
  username: string;
  nickname: string;
}

export interface Contact {
  id: string;
  account_id: string;
  username: string;
  nickname: string;
  remark_name: string | null;
}

export interface Conversation {
  id: string;
  account_id: string;
  contact_id: string;
  title: string;
  updated_at: string;
  contact: Contact;
}

export type MessageType = "text" | "image" | "audio" | "video" | "file";

export interface Message {
  id: number;
  conversation_id: string;
  sender_id: string | null; // null = self (the account); else the contact
  msg_type: MessageType;
  content: string;
  created_at: string;
}

export function contactName(c: Contact): string {
  return c.remark_name || c.nickname;
}

export function inferMediaType(mime: string): MessageType {
  if (mime.startsWith("image/")) return "image";
  if (mime.startsWith("audio/")) return "audio";
  if (mime.startsWith("video/")) return "video";
  return "file";
}

// ---- calls -----------------------------------------------------------

export const listConversations = () => creq<Conversation[]>("GET", "/conversations");

export const createContact = (p: { nickname: string; remark_name?: string }) =>
  creq<Contact>("POST", "/contacts", p);

export const updateContact = (id: string, p: { remark_name?: string }) =>
  creq<Contact>("PUT", `/contacts/${id}`, p);

export const sendMessage = (
  conversationId: string,
  p: { sender_id: string | null; msg_type: MessageType; content: string },
) =>
  creq<{ status: string; count: number }>("POST", `/conversations/${conversationId}/messages`, {
    messages: [p],
  });

export async function getMessagesBefore(
  conversationId: string,
  beforeId: number | undefined,
  limit: number,
): Promise<Message[]> {
  const q = new URLSearchParams({ limit: String(limit) });
  if (beforeId !== undefined) q.set("before_id", String(beforeId));
  const data = await creq<{ messages: Message[] }>("GET", `/conversations/${conversationId}/messages/before?${q}`);
  return data?.messages ?? [];
}

// Long-poll: blocks server-side up to `serverTimeout`s waiting for messages
// newer than lastId. The sidecar passes the timeout upstream with slack.
export async function getMessagesAfter(
  conversationId: string,
  lastId: number,
  serverTimeout = 30,
): Promise<Message[]> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), serverTimeout * 1000 + 8000);
  const q = new URLSearchParams({ last_id: String(lastId), timeout: String(serverTimeout) });
  try {
    const res = await fetch(base() + `/studio/chat/conversations/${conversationId}/messages/after?${q}`, {
      headers: { Authorization: `Bearer ${token()}` },
      signal: controller.signal,
    });
    clearTimeout(id);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return data?.messages ?? [];
  } catch (err) {
    clearTimeout(id);
    if (err instanceof DOMException && err.name === "AbortError") return [];
    throw err;
  }
}

// Media: <img src> can't carry an auth header, so the local token rides in
// the query; the sidecar validates it and streams bytes from Studio.
export function mediaUrl(storageKey: string): string {
  return `${base()}/studio/chat/media/${storageKey}?token=${encodeURIComponent(token())}`;
}

// Upload goes renderer → sidecar → S3 (route 2; the renderer never touches
// the external S3 URL, so the CSP can stay locked to 127.0.0.1).
export async function uploadFile(file: File): Promise<string> {
  const q = new URLSearchParams({
    filename: file.name,
    mime: file.type || "application/octet-stream",
  });
  const res = await fetch(base() + `/local/chat_upload?${q}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token()}`, "Content-Type": "application/octet-stream" },
    body: file,
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      if (j?.error) detail = String(j.error);
    } catch {
      /* keep */
    }
    throw new Error(detail);
  }
  const data = await res.json();
  return data.storage_key as string;
}
