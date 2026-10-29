/**
 * Typed API client for the XP FastAPI backend.
 *
 * Two transport modes:
 * - Gateway mode (`apiPort` set): same-origin requests tagged with the
 *   XTransformPort query param, for sandboxes that expose a single port.
 * - Direct mode (`apiBase` set): absolute origin, e.g. http://127.0.0.1:8001.
 */

import type {
  AccountClosureOut,
  ArtifactOut,
  ApprovalOut,
  AutomationRunOut,
  BalanceOut,
  CapabilitiesOut,
  ConnectionOut,
  ConnectionProvidersOut,
  DemoPdfIn,
  DevGrantIn,
  EmailDraftOut,
  HealthOut,
  JobOut,
  LedgerPageOut,
  NotificationsPageOut,
  PackOut,
  PurchaseCreateIn,
  PurchaseOut,
  RateOut,
  SessionInfo,
  SessionOut,
  UserOut,
  TaskCreateIn,
  TaskEstimateOut,
  TaskEventPageOut,
  TaskOut,
  TaskResultOut,
  TaskStepOut,
} from "@xp/shared-types";

export interface DevKey {
  id: string;
  name: string;
  prefix: string;
  network: string;
  created_at: string;
  last_used_at: string | null;
  secret: string | null; // only right after creating it
}

export interface DevHook {
  id: string;
  url: string;
  events: string[];
  secret: string;
  active: boolean;
  created_at: string;
}

export interface PriceAlert {
  id: string;
  currency: string;
  direction: "above" | "below";
  target: number;
  active: boolean;
  triggered_at: string | null;
  created_at: string;
}

export interface SavingsGoal {
  id: string;
  name: string;
  target_amount: number;
  currency: string; // "SAT" or a fiat code
  deadline: string | null;
  weekly_reminder: boolean;
  reached_at: string | null;
  created_at: string;
}

export interface XpClientConfig {
  apiPort?: string | number;
  apiBase?: string;
  fetchImpl?: typeof fetch;
  /** Raw bearer token provider; set by the Mini App from local storage. */
  getToken?: () => string | null;
}

export interface XpClient {
  health: () => Promise<HealthOut>;
  capabilities: () => Promise<CapabilitiesOut>;
  authTelegram: (initData?: string) => Promise<SessionOut>;
  me: () => Promise<UserOut>;
  devKeys: () => Promise<DevKey[]>;
  devCreateKey: (name: string, network: string) => Promise<DevKey>;
  devRevokeKey: (id: string) => Promise<void>;
  devHooks: () => Promise<DevHook[]>;
  devCreateHook: (url: string, events?: string[]) => Promise<DevHook>;
  devDeleteHook: (id: string) => Promise<void>;
  devTestHook: (id: string) => Promise<{ delivered: boolean; status_code: number | null; error: string | null }>;
  devDeliveries: (id: string) => Promise<{ id: string; event: string; status: string; attempts: number; last_status_code: number | null; last_error: string | null; created_at: string }[]>;
  devCreatePaymentRequest: (body: Record<string, unknown>) => Promise<Record<string, any>>;
  devPaymentRequests: () => Promise<{ data: Record<string, any>[] }>;
  currentNames: (network: string, identityPubkeys: string[]) => Promise<Record<string, string>>;
  groupPayment: (id: string) => Promise<{ id: string; kind: string; to_username: string; amount_sats: number; display: string; note: string | null; already_paid: boolean }>;
  groupPaid: (id: string, ref: string) => Promise<{ status: string }>;
  priceAlerts: () => Promise<PriceAlert[]>;
  addPriceAlert: (a: { currency: string; direction: "above" | "below"; target: number }) => Promise<PriceAlert>;
  deletePriceAlert: (id: string) => Promise<void>;
  goals: () => Promise<SavingsGoal[]>;
  addGoal: (g: { name: string; target_amount: number; currency: string; deadline?: string | null }) => Promise<SavingsGoal>;
  goalReached: (id: string) => Promise<SavingsGoal>;
  deleteGoal: (id: string) => Promise<void>;
  aiMemory: () => Promise<{ id: string; text: string; source: string; created_at: string }[]>;
  aiRemember: (text: string) => Promise<{ id: string; text: string; source: string; created_at: string }[]>;
  aiForget: (id?: string) => Promise<void>;
  linkStart: () => Promise<{ code: string; poll_token: string; expires_in: number; bot_username: string | null }>;
  /** null while waiting for /link in Telegram. */
  linkPoll: (pollToken: string) => Promise<SessionOut | null>;
  balance: () => Promise<BalanceOut>;
  ledger: (limit?: number, offset?: number) => Promise<LedgerPageOut>;
  devGrant: (payload: DevGrantIn) => Promise<BalanceOut>;
  listTasks: () => Promise<TaskOut[]>;
  createTask: (payload: TaskCreateIn) => Promise<TaskOut>;
  cancelTask: (taskId: string) => Promise<TaskOut>;
  deleteTask: (taskId: string) => Promise<void>;
  deliverTask: (taskId: string) => Promise<TaskOut>;
  clearTasks: () => Promise<{ deleted: number }>;
  rate: () => Promise<RateOut>;
  packs: () => Promise<PackOut[]>;
  estimateTask: (objective: string) => Promise<TaskEstimateOut>;
  createPurchase: (payload: PurchaseCreateIn) => Promise<PurchaseOut>;
  listPurchases: () => Promise<PurchaseOut[]>;
  getPurchase: (purchaseId: string) => Promise<PurchaseOut>;
  receiptPdfUrl: (purchaseId: string) => string;
  createReceiptArtifact: (purchaseId: string) => Promise<{ artifact_id: string; download_url: string }>;
  settleDevInvoice: (paymentHash: string) => Promise<{ credited: boolean; status: string }>;
  /** POST /run - the server resumes automatically from awaiting_approval. */
  runTask: (taskId: string) => Promise<TaskOut>;
  taskEvents: (taskId: string) => Promise<TaskEventPageOut>;
  taskSteps: (taskId: string) => Promise<TaskStepOut[]>;
  listApprovals: (taskId: string) => Promise<ApprovalOut[]>;
  decideApproval: (taskId: string, approvalId: string, approve: boolean) => Promise<ApprovalOut>;
  increaseBudget: (taskId: string, additionalXp: number) => Promise<TaskOut>;
  listArtifacts: () => Promise<ArtifactOut[]>;
  createDemoPdf: (payload: DemoPdfIn) => Promise<ArtifactOut>;
  artifactDownloadUrl: (artifact: ArtifactOut) => string;
  receiptUrl: (purchaseId: string) => string;
  sendReceiptToTelegram: (purchaseId: string) => Promise<{ status: string }>;
  logout: () => Promise<{ status: string; revoked: boolean }>;
  listSessions: () => Promise<SessionInfo[]>;
  revokeSession: (sessionId: string) => Promise<{ status: string; session_id: string }>;
  // phase 9: connections / drafts / automation / notifications
  connectionProviders: () => Promise<ConnectionProvidersOut>;
  listConnections: () => Promise<ConnectionOut[]>;
  linkConnection: (payload: {
    provider: string;
    scopes?: string[] | null;
    credential: Record<string, unknown>;
  }) => Promise<ConnectionOut>;
  revokeConnection: (connectionId: string) => Promise<ConnectionOut>;
  listDrafts: () => Promise<EmailDraftOut[]>;
  getDraft: (draftId: string) => Promise<EmailDraftOut>;
  listJobs: () => Promise<JobOut[]>;
  createJob: (payload: {
    objective: string;
    schedule: string;
    budget_per_run_xp: number;
    budget_total_xp?: number | null;
    conditions?: Record<string, unknown> | null;
  }) => Promise<JobOut>;
  pauseJob: (jobId: string) => Promise<JobOut>;
  resumeJob: (jobId: string) => Promise<JobOut>;
  cancelJob: (jobId: string) => Promise<JobOut>;
  triggerJob: (jobId: string) => Promise<AutomationRunOut>;
  jobRuns: (jobId: string) => Promise<AutomationRunOut[]>;
  listNotifications: () => Promise<NotificationsPageOut>;
  markNotificationRead: (notificationId: string) => Promise<NotificationOut>;
  exportAccount: () => Promise<Response>;
  closeAccount: (confirm: "CLOSE") => Promise<AccountClosureOut>;
  handleCheck: (username: string, network: string) => Promise<{ username: string; available: boolean; reason: string | null }>;
  handleClaim: (body: HandleClaimIn) => Promise<HandleMeOut>;
  handleMe: (network: string) => Promise<HandleMeOut>;
  handleTopUp: (body: { network: string; identity_pubkey: string; addresses: SignedAddressIn[] }) => Promise<HandleMeOut>;
  handleAddress: (username: string, network: string) => Promise<IssuedAddressOut>;
  createRequest: (body: { network: string; amount_sats?: number; note?: string }) => Promise<PaymentRequestOut>;
  listRequests: () => Promise<PaymentRequestOut[]>;
  getRequest: (id: string) => Promise<PaymentRequestOut>;
  cancelRequest: (id: string) => Promise<PaymentRequestOut>;
  btcPrice: () => Promise<{ btc_ngn: number; btc_usd: number | null; updated_at: number; source: string }>;
  /** Price of 1 BTC in every currency (code -> price). */
  btcRates: () => Promise<{ btc: Record<string, number>; updated_at: number; source: string }>;
  onrampStatus: () => Promise<{ enabled: boolean; default_fiat: string }>;
  onrampLink: (body: { address: string; fiat?: string; amount?: number }) => Promise<{ url: string; expires_at: string }>;
  handleLightningPublish: (body: { network: string; identity_pubkey: string; ln_network: string; spark_address: string; signature: string }) => Promise<HandleLightningOut>;
  handleLightning: (username: string, network: string) => Promise<HandleLightningOut>;
  alertsStatus: (network: string) => Promise<WalletAlertsOut>;
  aiStatus: () => Promise<{ online: boolean; queued: number; running: number; mode: string }>;
  alertsSet: (body: { network: string; enabled: boolean; addresses?: string[] }) => Promise<WalletAlertsOut>;
  alertsWatch: (body: { network: string; addresses: string[] }) => Promise<WalletAlertsOut>;
}

export interface HandleLightningOut {
  username: string;
  identity_pubkey: string;
  ln_network: string;
  spark_address: string;
  signature: string;
}

export interface WalletAlertsOut {
  enabled: boolean;
  watched: number;
}

/** Plain-language error text for people, not developers. */
export function friendlyError(status: number, detail: string): string {
  if (status === 401) return "You're not signed in. Please open Satish from the Telegram bot.";
  if (status === 403) return "That isn't available on your account.";
  if (status === 404) {
    // Our own 404s explain themselves ("No Satish user called @x."); framework ones say "Not Found".
    const own = detail.trim();
    return own && own !== "Not Found" && /\s/.test(own) ? own : "We couldn't find that. It may have been removed.";
  }
  if (status === 429) return "You're going a bit fast. Please wait a moment and try again.";
  if (status >= 500) return "Something went wrong on our side. Please try again shortly.";
  if (/insufficient|balance/i.test(detail)) return "You don't have enough TK for that. Buy more TK and try again.";
  // 400/409/422: the server's reason is usually meaningful; keep it short.
  const text = detail.replace(/^[A-Z_]+:\s*/, "").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "That didn't work. Please try again.";
}

export interface SignedAddressIn {
  address: string;
  index: number;
  signature: string;
}
export interface HandleClaimIn {
  network: string;
  username: string;
  identity_pubkey: string;
  addresses: SignedAddressIn[];
}
export interface HandleMeOut {
  username: string | null;
  identity_pubkey: string | null;
  available: number;
  max_index: number;
  issued_max_index: number;
  lightning_address?: string | null;
  lightning_network?: string | null;
}
export interface IssuedAddressOut {
  username: string;
  address: string;
  signature: string;
  identity_pubkey: string;
  reused: boolean;
}
export interface PaymentRequestOut {
  id: string;
  url: string;
  network: string;
  username: string;
  address: string;
  signature: string;
  identity_pubkey: string;
  amount_sats: number | null;
  note: string | null;
  status: "open" | "paid" | "cancelled";
  paid_sats: number;
  created_at: string;
  paid_at: string | null;
}

export function createXpClient(config: XpClientConfig = {}): XpClient {
  const doFetch = config.fetchImpl ?? fetch;

  function buildUrl(path: string): string {
    let url = path.startsWith("/") ? path : `/${path}`;
    if (config.apiPort) {
      url += (url.includes("?") ? "&" : "?") + `XTransformPort=${config.apiPort}`;
      // Gateway mode: same-origin. In a browser `fetch` resolves it naturally;
      // outside a browser an explicit origin keeps it callable.
      if (typeof window === "undefined" && typeof process !== "undefined") {
        const origin = process.env.XP_CLIENT_ORIGIN;
        if (origin) url = origin + url;
      }
    } else {
      url = (config.apiBase ?? "http://127.0.0.1:8001").replace(/\/$/, "") + url;
    }
    return url;
  }

  async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...((init?.headers as Record<string, string>) ?? {}),
    };
    const token = config.getToken?.();
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await doFetch(buildUrl(path), {
      ...init,
      headers,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = (await res.json()) as { detail?: unknown };
        if (typeof body?.detail === "string") {
          detail = body.detail;
        } else if (body?.detail && typeof body.detail === "object") {
          const reasons = (body.detail as { reasons?: string[] }).reasons;
          if (Array.isArray(reasons)) detail = reasons.join("; ");
          else detail = JSON.stringify(body.detail);
        }
      } catch {
        /* keep statusText */
      }
      throw new Error(friendlyError(res.status, detail));
    }
    if (res.status === 204) return undefined as T;
    if (res.status === 202) return { pending: true } as T;
    return (await res.json()) as T;
  }

  async function requestRaw(path: string): Promise<Response> {
    const headers: Record<string, string> = {};
    const token = config.getToken?.();
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await doFetch(buildUrl(path), { headers });
    if (!res.ok) throw new Error(`XP API ${res.status}: ${res.statusText}`);
    return res;
  }

  return {
    health: () => request<HealthOut>("/api/v1/health"),
    capabilities: () => request<CapabilitiesOut>("/api/v1/capabilities"),
    me: () => request<UserOut>("/api/v1/auth/me"),
    devKeys: () => request("/api/v1/dev/keys"),
    devCreateKey: (name, network) => request("/api/v1/dev/keys", { method: "POST", body: JSON.stringify({ name, network }) }),
    devRevokeKey: (id) => request<void>(`/api/v1/dev/keys/${id}`, { method: "DELETE" }),
    devHooks: () => request("/api/v1/dev/webhooks"),
    devCreateHook: (url, events) => request("/api/v1/dev/webhooks", { method: "POST", body: JSON.stringify({ url, events: events ?? ["request.paid"] }) }),
    devDeleteHook: (id) => request<void>(`/api/v1/dev/webhooks/${id}`, { method: "DELETE" }),
    devTestHook: (id) => request(`/api/v1/dev/webhooks/${id}/test`, { method: "POST" }),
    devDeliveries: (id) => request(`/api/v1/dev/webhooks/${id}/deliveries`),
    devCreatePaymentRequest: (body) => request("/api/v1/dev/payment-requests", { method: "POST", body: JSON.stringify(body) }),
    devPaymentRequests: () => request("/api/v1/dev/payment-requests"),
    currentNames: (network, identityPubkeys) =>
      request("/api/v1/handles/current-names", { method: "POST", body: JSON.stringify({ network, identity_pubkeys: identityPubkeys }) }),
    groupPayment: (id) => request(`/api/v1/group/${id}`),
    groupPaid: (id, ref) => request(`/api/v1/group/${id}/paid`, { method: "POST", body: JSON.stringify({ ref }) }),
    priceAlerts: () => request("/api/v1/alerts/price"),
    addPriceAlert: (a) => request("/api/v1/alerts/price", { method: "POST", body: JSON.stringify(a) }),
    deletePriceAlert: (id) => request<void>(`/api/v1/alerts/price/${id}`, { method: "DELETE" }),
    goals: () => request("/api/v1/goals"),
    addGoal: (g) => request("/api/v1/goals", { method: "POST", body: JSON.stringify(g) }),
    goalReached: (id) => request(`/api/v1/goals/${id}/reached`, { method: "POST" }),
    deleteGoal: (id) => request<void>(`/api/v1/goals/${id}`, { method: "DELETE" }),
    aiMemory: () => request("/api/v1/ai/memory"),
    aiRemember: (text) => request("/api/v1/ai/memory", { method: "POST", body: JSON.stringify({ text }) }),
    aiForget: (id) => request<void>(id ? `/api/v1/ai/memory/${id}` : "/api/v1/ai/memory", { method: "DELETE" }),
    linkStart: () => request("/api/v1/auth/link/start", { method: "POST" }),
    linkPoll: async (pollToken) => {
      const r = await request<SessionOut | { pending: true }>("/api/v1/auth/link/poll", {
        method: "POST",
        body: JSON.stringify({ poll_token: pollToken }),
      });
      return r && "session_token" in r ? r : null;
    },
    authTelegram: (initData = "") =>
      request<SessionOut>("/api/v1/auth/telegram", {
        method: "POST",
        body: JSON.stringify({ init_data: initData }),
      }),
    balance: () => request<BalanceOut>("/api/v1/xp/balance"),
    ledger: (limit = 50, offset = 0) =>
      request<LedgerPageOut>(`/api/v1/xp/ledger?limit=${limit}&offset=${offset}`),
    devGrant: (payload) =>
      request<BalanceOut>("/api/v1/xp/dev/grant", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    listTasks: () => request<TaskOut[]>("/api/v1/tasks"),
    createTask: (payload) =>
      request<TaskOut>("/api/v1/tasks", { method: "POST", body: JSON.stringify(payload) }),
    cancelTask: (taskId) =>
      request<TaskOut>(`/api/v1/tasks/${taskId}/cancel`, { method: "POST" }),
    deliverTask: (taskId) => request<TaskOut>(`/api/v1/tasks/${taskId}/deliver`, { method: "POST" }),
    deleteTask: (taskId) => request<void>(`/api/v1/tasks/${taskId}`, { method: "DELETE" }),
    clearTasks: () => request<{ deleted: number }>("/api/v1/tasks/clear", { method: "POST" }),
    rate: () => request<RateOut>("/api/v1/xp/rate"),
    packs: () => request<PackOut[]>("/api/v1/xp/packs"),
    estimateTask: (objective) =>
      request<TaskEstimateOut>("/api/v1/tasks/estimate", {
        method: "POST",
        body: JSON.stringify({ objective, budget_xp: 1 }),
      }),
    createPurchase: (payload) =>
      request<PurchaseOut>("/api/v1/xp/purchases", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    listPurchases: () => request<PurchaseOut[]>("/api/v1/xp/purchases"),
    getPurchase: (purchaseId) =>
      request<PurchaseOut>(`/api/v1/xp/purchases/${purchaseId}`),
    receiptPdfUrl: (purchaseId) =>
      buildUrl(`/api/v1/xp/purchases/${purchaseId}/receipt.pdf`),
    createReceiptArtifact: (purchaseId) =>
      request<{ artifact_id: string; download_url: string }>(
        `/api/v1/xp/purchases/${purchaseId}/receipt.pdf`,
        { method: "POST" }
      ),
    settleDevInvoice: (paymentHash) =>
      request<{ credited: boolean; status: string }>(
        `/api/v1/lightning/invoices/${paymentHash}/settle-dev`,
        { method: "POST" }
      ),
    runTask: (taskId) =>
      request<TaskOut>(`/api/v1/tasks/${taskId}/run`, { method: "POST" }),
    taskEvents: (taskId) =>
      request<TaskEventPageOut>(`/api/v1/tasks/${taskId}/events`),
    taskSteps: (taskId) =>
      request<TaskStepOut[]>(`/api/v1/tasks/${taskId}/steps`),
    listApprovals: (taskId) =>
      request<ApprovalOut[]>(`/api/v1/tasks/${taskId}/approvals`),
    decideApproval: (taskId, approvalId, approve) =>
      request<ApprovalOut>(`/api/v1/tasks/${taskId}/approvals/${approvalId}/decision`, {
        method: "POST",
        body: JSON.stringify({ approve }),
      }),
    increaseBudget: (taskId, additionalXp) =>
      request<TaskOut>(`/api/v1/tasks/${taskId}/increase-budget`, {
        method: "POST",
        body: JSON.stringify({ additional_xp: additionalXp }),
      }),
    taskResult: (taskId) =>
      request<TaskResultOut>(`/api/v1/tasks/${taskId}/result`),
    listArtifacts: () => request<ArtifactOut[]>("/api/v1/artifacts"),
    createDemoPdf: (payload) =>
      request<ArtifactOut>("/api/v1/artifacts/demo-pdf", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    artifactDownloadUrl: (artifact) => buildUrl(`/api/v1/artifacts/${artifact.id}/download`),
    receiptUrl: (purchaseId) => buildUrl(`/api/v1/xp/purchases/${purchaseId}/receipt`),
    sendReceiptToTelegram: (purchaseId) =>
      request<{ status: string }>(`/api/v1/xp/purchases/${purchaseId}/receipt/telegram`, { method: "POST" }),
    logout: () =>
      request<{ status: string; revoked: boolean }>("/api/v1/auth/logout", { method: "POST" }),
    listSessions: () => request<SessionInfo[]>("/api/v1/auth/sessions"),
    revokeSession: (sessionId) =>
      request<{ status: string; session_id: string }>(`/api/v1/auth/sessions/${sessionId}`, {
        method: "DELETE",
      }),
    // phase 9
    connectionProviders: () => request<ConnectionProvidersOut>("/api/v1/connections/providers"),
    listConnections: () => request<ConnectionOut[]>("/api/v1/connections"),
    linkConnection: (payload) =>
      request<ConnectionOut>("/api/v1/connections", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    revokeConnection: (connectionId) =>
      request<ConnectionOut>(`/api/v1/connections/${connectionId}`, { method: "DELETE" }),
    listDrafts: () => request<EmailDraftOut[]>("/api/v1/drafts"),
    getDraft: (draftId) => request<EmailDraftOut>(`/api/v1/drafts/${draftId}`),
    listJobs: () => request<JobOut[]>("/api/v1/jobs"),
    createJob: (payload) =>
      request<JobOut>("/api/v1/jobs", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    pauseJob: (jobId) => request<JobOut>(`/api/v1/jobs/${jobId}/pause`, { method: "POST" }),
    resumeJob: (jobId) => request<JobOut>(`/api/v1/jobs/${jobId}/resume`, { method: "POST" }),
    cancelJob: (jobId) => request<JobOut>(`/api/v1/jobs/${jobId}/cancel`, { method: "POST" }),
    triggerJob: (jobId) => request<AutomationRunOut>(`/api/v1/jobs/${jobId}/run`, { method: "POST" }),
    jobRuns: (jobId) => request<AutomationRunOut[]>(`/api/v1/jobs/${jobId}/runs`),
    listNotifications: () => request<NotificationsPageOut>("/api/v1/notifications"),
    markNotificationRead: (notificationId) =>
      request<NotificationOut>(`/api/v1/notifications/${notificationId}/read`, {
        method: "POST",
      }),
    exportAccount: () => requestRaw("/api/v1/account/export"),
    handleCheck: (username, network) =>
      request(`/api/v1/handles/check?username=${encodeURIComponent(username)}&network=${network}`),
    handleClaim: (body) => request("/api/v1/handles/claim", { method: "POST", body: JSON.stringify(body) }),
    handleMe: (network) => request(`/api/v1/handles/me?network=${network}`),
    handleTopUp: (body) => request("/api/v1/handles/addresses", { method: "POST", body: JSON.stringify(body) }),
    handleAddress: (username, network) =>
      request(`/api/v1/handles/${encodeURIComponent(username)}/address?network=${network}`, { method: "POST" }),
    createRequest: (body) => request("/api/v1/requests", { method: "POST", body: JSON.stringify(body) }),
    listRequests: () => request("/api/v1/requests"),
    getRequest: (id) => request(`/api/v1/requests/${encodeURIComponent(id)}`),
    cancelRequest: (id) => request(`/api/v1/requests/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
    btcPrice: () => request("/api/v1/price/btc"),
    btcRates: () => request("/api/v1/price/rates"),
    onrampStatus: () => request("/api/v1/onramp/status"),
    onrampLink: (body) => request("/api/v1/onramp/link", { method: "POST", body: JSON.stringify(body) }),
    handleLightningPublish: (body) => request("/api/v1/handles/lightning", { method: "POST", body: JSON.stringify(body) }),
    handleLightning: (username, network) =>
      request(`/api/v1/handles/${encodeURIComponent(username)}/lightning?network=${network}`),
    aiStatus: () => request("/api/v1/tasks/ai-status"),
    alertsStatus: (network) => request(`/api/v1/wallet/alerts?network=${network}`),
    alertsSet: (body) => request("/api/v1/wallet/alerts", { method: "PUT", body: JSON.stringify(body) }),
    alertsWatch: (body) => request("/api/v1/wallet/alerts/addresses", { method: "POST", body: JSON.stringify(body) }),
    closeAccount: (confirm) =>
      request<AccountClosureOut>("/api/v1/account/closure", {
        method: "POST",
        body: JSON.stringify({ confirm }),
      }),
  };
}
