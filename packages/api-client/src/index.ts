/**
 * Typed API client for the XP FastAPI backend.
 *
 * Two transport modes:
 * - Gateway mode (`apiPort` set): same-origin requests tagged with the
 *   XTransformPort query param, for sandboxes that expose a single port.
 * - Direct mode (`apiBase` set): absolute origin, e.g. http://127.0.0.1:8001.
 */

import type {
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
  TaskCreateIn,
  TaskEstimateOut,
  TaskEventPageOut,
  TaskOut,
  TaskResultOut,
  TaskStepOut,
} from "@xp/shared-types";

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
  balance: () => Promise<BalanceOut>;
  ledger: (limit?: number, offset?: number) => Promise<LedgerPageOut>;
  devGrant: (payload: DevGrantIn) => Promise<BalanceOut>;
  listTasks: () => Promise<TaskOut[]>;
  createTask: (payload: TaskCreateIn) => Promise<TaskOut>;
  cancelTask: (taskId: string) => Promise<TaskOut>;
  rate: () => Promise<RateOut>;
  packs: () => Promise<PackOut[]>;
  estimateTask: (objective: string) => Promise<TaskEstimateOut>;
  createPurchase: (payload: PurchaseCreateIn) => Promise<PurchaseOut>;
  listPurchases: () => Promise<PurchaseOut[]>;
  getPurchase: (purchaseId: string) => Promise<PurchaseOut>;
  receiptPdfUrl: (purchaseId: string) => string;
  createReceiptArtifact: (purchaseId: string) => Promise<{ artifact_id: string; download_url: string }>;
  settleDevInvoice: (paymentHash: string) => Promise<{ credited: boolean; status: string }>;
  /** POST /run — the server resumes automatically from awaiting_approval. */
  runTask: (taskId: string) => Promise<TaskOut>;
  taskEvents: (taskId: string) => Promise<TaskEventPageOut>;
  taskSteps: (taskId: string) => Promise<TaskStepOut[]>;
  listApprovals: (taskId: string) => Promise<ApprovalOut[]>;
  decideApproval: (taskId: string, approvalId: string, approve: boolean) => Promise<ApprovalOut>;
  increaseBudget: (taskId: string, additionalXp: number) => Promise<TaskOut>;
  listArtifacts: () => Promise<ArtifactOut[]>;
  createDemoPdf: (payload: DemoPdfIn) => Promise<ArtifactOut>;
  artifactDownloadUrl: (artifact: ArtifactOut) => string;
  logout: () => Promise<{ status: string; revoked: boolean }>;
  listSessions: () => Promise<SessionInfo[]>;
  revokeSession: (sessionId: string) => Promise<{ status: string; session_id: string }>;
  // -- phase 9: connections / drafts / automation / notifications ------------
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
        const body = (await res.json()) as { detail?: string };
        if (body?.detail) detail = body.detail;
      } catch {
        /* keep statusText */
      }
      throw new Error(`XP API ${res.status}: ${detail}`);
    }
    return (await res.json()) as T;
  }

  return {
    health: () => request<HealthOut>("/api/v1/health"),
    capabilities: () => request<CapabilitiesOut>("/api/v1/capabilities"),
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
    logout: () =>
      request<{ status: string; revoked: boolean }>("/api/v1/auth/logout", { method: "POST" }),
    listSessions: () => request<SessionInfo[]>("/api/v1/auth/sessions"),
    revokeSession: (sessionId) =>
      request<{ status: string; session_id: string }>(`/api/v1/auth/sessions/${sessionId}`, {
        method: "DELETE",
      }),
    // -- phase 9 ---------------------------------------------------------------
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
  };
}
