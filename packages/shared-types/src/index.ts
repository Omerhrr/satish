/**
 * Shared TypeScript contracts mirroring xp_core/schemas/api.py.
 *
 * These types are the single source of truth for the Nuxt app and the
 * api-client package. Keep them in sync with the FastAPI response models
 * (an OpenAPI-generated client can replace this file once the API
 * stabilizes — api_rules #7).
 */

export type Env = "dev" | "regtest" | "testnet" | "staging" | "prod";

export interface ComponentStatus {
  name: string;
  status: "ok" | "error" | "not_configured";
  detail: string | null;
}

export interface HealthOut {
  status: "ok" | "degraded";
  env: Env;
  version: string;
  database: ComponentStatus;
  queue: ComponentStatus;
  agent_runtime: ComponentStatus;
  dsh_revision: string;
}

export interface CapabilitiesOut {
  wallets: string;
  lightning: string;
  agent_runtime: string;
  notes: string[];
}

export interface UserOut {
  id: string;
  display_name: string | null;
  status: string;
  created_at: string;
}

export interface SessionOut {
  session_token: string;
  user: UserOut;
  mode: "telegram" | "dev";
}

export interface BalanceOut {
  balance_xp: number;
  sats_per_xp: number;
  updated_at: string;
}

export type LedgerEntryType =
  | "purchase"
  | "reservation"
  | "reservation_release"
  | "charge"
  | "refund"
  | "adjustment";

export interface LedgerEntryOut {
  id: string;
  entry_type: LedgerEntryType;
  amount: number;
  balance_after: number;
  reference_type: string | null;
  reference_id: string | null;
  note: string | null;
  created_at: string;
}

export interface LedgerPageOut {
  items: LedgerEntryOut[];
  total: number;
}

export type TaskStatus =
  | "awaiting_approval"
  | "planned"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export interface TaskOut {
  id: string;
  objective: string;
  status: TaskStatus;
  budget_xp: number;
  reserved_xp: number;
  actual_xp: number;
  deliverable: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
}

export interface ArtifactOut {
  id: string;
  object_key: string;
  content_type: string;
  size_bytes: number;
  sha256: string | null;
  status: "pending" | "ready" | "expired" | "failed";
  download_url: string | null;
  created_at: string;
}

// -- request payloads -------------------------------------------------------------

export interface TaskCreateIn {
  objective: string;
  budget_xp: number;
  idempotency_key?: string | null;
}

export interface DevGrantIn {
  amount_xp: number;
  reason?: string;
}

export interface DemoPdfIn {
  title: string;
  sections?: string[];
  metadata?: Record<string, unknown>;
}
