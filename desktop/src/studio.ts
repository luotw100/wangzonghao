// Studio control-plane client. Every call goes through the local sidecar's
// /studio/* reverse proxy (route 2): the renderer sends the LOCAL bridge
// token; the sidecar swaps in the real Studio session token upstream.

function sreq<T>(method: string, path: string, body?: unknown): Promise<T> {
  const b = window.bridge;
  if (!b) return Promise.reject(new Error("bridge preload missing"));
  const headers: Record<string, string> = { Authorization: `Bearer ${b.token}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  return fetch(b.baseUrl + "/studio" + path, {
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

// ---- types (mirror services/user_web/src/lib/api.ts) -----------------

export type BridgeStatus = "online" | "offline";

export interface Bridge {
  id: string;
  account_id: string;
  machine_id: string;
  status: BridgeStatus;
  last_seen_at: string;
  created_at: string;
  updated_at: string;
}

export interface Inbox {
  id: string;
  account_id: string;
  bridge_id: string | null;
  platform: string;
  display_name: string;
  platform_self_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PersonaSummary {
  id: string;
  account_id: string;
  name: string;
  timezone: string;
  created_at: string;
  updated_at: string;
}

export interface Persona extends PersonaSummary {
  persona_md: string;
}

export type ConversationKind = "dm" | "group" | "unknown";

export interface ConversationSummary {
  id: string;
  inbox_id: string;
  platform_conversation_id: string;
  kind: ConversationKind;
  display_name: string;
  persona_id: string | null;
  takeover: boolean;
  reply_policy: "disabled" | "autoreply";
  status: "active" | "archived";
  last_reply_round_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Conversation extends ConversationSummary {
  card_md: string;
  members: { peer_platform_id: string; display_name: string; updated_at: string }[];
}

export interface Message {
  id: number;
  conversation_id: string;
  client_id: string;
  sender_id: string | null;
  msg_type: string;
  content: string;
  timestamp: string;
  created_at: string;
  from_self: boolean;
}

export interface ConversationListItem {
  conversation: ConversationSummary;
  inbox: Inbox;
  latest_message: Message | null;
  message_count: number;
  member_count: number;
}

export interface StudioAccount {
  id: string;
  username: string;
  display_name: string | null;
}

// ---- calls -----------------------------------------------------------

export const authMe = () => sreq<StudioAccount>("GET", "/auth/me");
export const changeOwnPassword = (d: { current_password: string; new_password: string }) =>
  sreq<null>("PUT", "/auth/password", d);

export const getBridges = () => sreq<Bridge[]>("GET", "/bridges");
export const deleteBridge = (id: string) => sreq<null>("DELETE", `/bridges/${id}`);

export const getInboxes = () => sreq<Inbox[]>("GET", "/inboxes");

export const getPersonas = () => sreq<PersonaSummary[]>("GET", "/personas");
export const getPersona = (id: string) => sreq<Persona>("GET", `/personas/${id}`);
export const createPersona = (d: { name: string; persona_md: string | null; timezone?: string }) =>
  sreq<Persona>("POST", "/personas", d);
export const updatePersona = (
  id: string,
  d: { name?: string; persona_md?: string; timezone?: string },
) => sreq<Persona>("PATCH", `/personas/${id}`, d);
export const deletePersona = (id: string) => sreq<null>("DELETE", `/personas/${id}`);

export const getConversations = () => sreq<ConversationListItem[]>("GET", "/conversations");
export const getConversation = (id: string) => sreq<Conversation>("GET", `/conversations/${id}`);
export const getConversationMessages = (id: string, limit = 200) =>
  sreq<Message[]>("GET", `/conversations/${id}/messages?limit=${limit}`);
export const updateConversation = (
  id: string,
  d: {
    display_name?: string;
    card_md?: string;
    persona_id?: string | null;
    takeover?: boolean;
    reply_policy?: "disabled" | "autoreply";
    status?: "active" | "archived";
  },
) => sreq<Conversation>("PATCH", `/conversations/${id}`, d);

export const createDistillJob = (d: { conversation_ids: string[]; target_persona_id?: string | null }) =>
  sreq<{ id: string }>("POST", "/distill-jobs", d);

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString();
}
