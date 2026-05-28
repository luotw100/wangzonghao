import { useQuery, type QueryClient } from "@tanstack/react-query";
import { api } from "./bridge";
import * as studio from "./studio";
import * as chat from "./chat";

// ---- /local types ----------------------------------------------------

export type Status = {
  running: boolean;
  status: string;
  in_count_5m: number;
  outbound_pending: number;
  last_error: string | null;
  studio_url?: string;
};

export type Account = {
  logged_in: boolean;
  account_id: string | null;
  display_name: string | null;
  machine_id: string | null;
  studio_url?: string;
};

export type AccountListItem = {
  account_id: string;
  display_name: string | null;
  active: boolean;
  channel_count: number;
  has_token: boolean;
};

export type Channel = {
  channel_id: number;
  platform: string;
  platform_label: string;
  self_id: string | null;
  state: string;
  online: boolean;
  conv_count: number;
  last_error: string | null;
};

export type Platform = { id: string; label: string };

// ---- query keys ------------------------------------------------------

export const qk = {
  local: ["local"] as const,
  account: ["local", "account"] as const,
  accounts: ["local", "accounts"] as const,
  status: ["local", "status"] as const,
  channels: ["local", "channels"] as const,
  platforms: ["local", "platforms"] as const,
  studio: ["studio"] as const,
  bridges: ["studio", "bridges"] as const,
  inboxes: ["studio", "inboxes"] as const,
  personas: ["studio", "personas"] as const,
  persona: (id: string) => ["studio", "persona", id] as const,
  conversations: ["studio", "conversations"] as const,
  conversation: (id: string) => ["studio", "conversation", id] as const,
  messages: (id: string) => ["studio", "messages", id] as const,
  chatAccount: ["chat", "account"] as const,
  chatConversations: ["chat", "conversations"] as const,
};

// Invalidate helpers — call after a mutation so the UI reconciles against
// the server instead of trusting the optimistic local change.
export const invalidateLocal = (qc: QueryClient) => qc.invalidateQueries({ queryKey: qk.local });
export const invalidateStudio = (qc: QueryClient) => qc.invalidateQueries({ queryKey: qk.studio });
export const invalidatePersonas = (qc: QueryClient) => qc.invalidateQueries({ queryKey: qk.personas });
export const invalidateConversations = (qc: QueryClient) => {
  qc.invalidateQueries({ queryKey: qk.conversations });
};
export const invalidateBridges = (qc: QueryClient) => {
  qc.invalidateQueries({ queryKey: qk.bridges });
  qc.invalidateQueries({ queryKey: qk.inboxes });
};

// ---- /local hooks ----------------------------------------------------

export const useLocalAccount = () =>
  useQuery({ queryKey: qk.account, queryFn: () => api<Account>("/local/account"), refetchInterval: 3000 });
export const useLocalAccounts = () =>
  useQuery({ queryKey: qk.accounts, queryFn: () => api<AccountListItem[]>("/local/accounts"), refetchInterval: 5000 });
export const useLocalStatus = () =>
  useQuery({ queryKey: qk.status, queryFn: () => api<Status>("/local/status"), refetchInterval: 3000 });
export const useLocalChannels = () =>
  useQuery({ queryKey: qk.channels, queryFn: () => api<Channel[]>("/local/channels"), refetchInterval: 3000 });
export const useLocalPlatforms = () =>
  useQuery({ queryKey: qk.platforms, queryFn: () => api<Platform[]>("/local/platforms"), staleTime: Infinity });

// ---- studio hooks ----------------------------------------------------

export const useBridges = () =>
  useQuery({ queryKey: qk.bridges, queryFn: studio.getBridges, refetchInterval: 10000 });
export const useInboxes = () =>
  useQuery({ queryKey: qk.inboxes, queryFn: studio.getInboxes, refetchInterval: 10000 });
export const usePersonas = () =>
  useQuery({ queryKey: qk.personas, queryFn: studio.getPersonas });
export const useConversations = () =>
  useQuery({ queryKey: qk.conversations, queryFn: studio.getConversations, refetchInterval: 3000 });
export const useConversation = (id: string | null) =>
  useQuery({
    queryKey: qk.conversation(id ?? ""),
    queryFn: () => studio.getConversation(id as string),
    enabled: !!id,
  });
export const useConversationMessages = (id: string | null) =>
  useQuery({
    queryKey: qk.messages(id ?? ""),
    queryFn: () => studio.getConversationMessages(id as string),
    enabled: !!id,
    refetchInterval: 3000,
  });

// ---- chat hooks (sandbox scaffolding; messages use their own long-poll) ----

export const useChatAccount = () =>
  useQuery({
    queryKey: qk.chatAccount,
    queryFn: async (): Promise<chat.Account> => {
      const a = await studio.authMe();
      return { id: a.id, username: a.username, nickname: a.display_name || a.username };
    },
    staleTime: Infinity,
  });
export const useChatConversations = () =>
  useQuery({ queryKey: qk.chatConversations, queryFn: chat.listConversations, refetchInterval: 5000 });
