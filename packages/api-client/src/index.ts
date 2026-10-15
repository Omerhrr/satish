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
  SessionInfo,
  BalanceOut,
  CapabilitiesOut,
  DemoPdfIn,
  DevGrantIn,
  HealthOut,
  LedgerPageOut,
  SessionOut,
  TaskCreateIn,
  TaskOut,
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
  listArtifacts: () => Promise<ArtifactOut[]>;
  createDemoPdf: (payload: DemoPdfIn) => Promise<ArtifactOut>;
  artifactDownloadUrl: (artifact: ArtifactOut) => string;
  logout: () => Promise<{ status: string; revoked: boolean }>;
  listSessions: () => Promise<SessionInfo[]>;
  revokeSession: (sessionId: string) => Promise<{ status: string; session_id: string }>;
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
  };
}
