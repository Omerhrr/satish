/**
 * Shared TypeScript contracts mirroring xp_core/schemas/api.py.
 *
 * These types are the single source of truth for the Nuxt app and the
 * api-client package. Keep them in sync with the FastAPI response models
 * (an OpenAPI-generated client can replace this file once the API
 * stabilizes - api_rules #7).
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

export interface SessionInfo {
  id: string;
  created_via: string;
  created_at: string;
  last_used_at: string | null;
  expires_at: string;
}

export interface BalanceOut {
  balance_xp: number;
  xp_per_sat: number;
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

// task result: explicit result + limitations + XP receipt (phase 7)

export interface ResultArtifactOut {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string | null;
  download_url: string;
}

export interface ResultSourceOut {
  url: string;
  title: string;
  status: "listed" | "ok" | "unavailable" | "denied" | "error";
  retrieval_mode: "canned" | "http";
  fact_count: number;
  retrieved_at: string | null;
  note: string | null;
  // phase-8: source freshness + confidence indicators
  freshness: "fresh" | "recent" | "stale" | "outdated" | "unknown";
  confidence: "high" | "medium" | "low";
}

export interface XpReceiptOut {
  budget_xp: number;
  actual_xp: number;
  released_xp: number;
  charge_entry_id: string | null;
  settled_at: string | null;
  balance_after: number | null;
  status: "settled" | "pending_settlement" | "no_charge";
}

// phase-8: transparent commerce scoring verdict (factors + weights echoed)
export interface ScoredFactorOut {
  name: string;
  weight: number;
  signal: string;
  normalized: number | null;
  included: boolean;
  reason: string;
}

export interface ScoredOut {
  product: string;
  score: number;
  factors: ScoredFactorOut[];
  excluded: string[];
  config_echo: Record<string, number>;
  disclosures: string[];
}

export interface TaskResultOut {
  task_id: string;
  status: TaskStatus;
  objective: string;
  deliverable: string | null;
  completed_at: string | null;
  artifacts: ResultArtifactOut[];
  sources: ResultSourceOut[];
  conflicts: Array<{ subject: string; detail: string; values?: unknown[] }>;
  gaps: string[];
  limitations: string[];
  xp_receipt: XpReceiptOut;
  scored: ScoredOut | null;
}

// request payloads

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

// Lightning (phase 4)

export type LightningIntentStatus =
  | "created"
  | "pending"
  | "prepared"
  | "authorized"
  | "in_flight"
  | "settled"
  | "succeeded"
  | "failed"
  | "expired";

export interface LightningIntentOut {
  payment_hash: string;
  id: string;
  direction: "receive" | "send";
  amount_sats: number;
  xp_amount: number;
  status: LightningIntentStatus;
  bolt11: string | null;
  fee_msat: number | null;
  expires_at: string | null;
  settled_at: string | null;
  created_at: string;
}

export interface LightningPrepareOut {
  payment_id: string;
  state: "prepared";
  amount_msat: number;
  fee_estimate_msat: number;
  fee_limit_msat: number;
  fee_clamped: boolean;
  authorization_digest: string;
  description: string;
  note: string;
}

export interface LightningChannelsOut {
  channels: Array<{
    channel_id: string;
    peer_pubkey: string;
    capacity_msat: number;
    local_msat: number;
    remote_msat: number;
    active: boolean;
  }>;
  outbound_msat: number;
  inbound_msat: number;
  disclosures: string[];
  inbound_constrained: boolean;
}

export interface LightningCapabilitiesOut {
  mode: "canned" | "lnd";
  network: string;
  implementation: string;
  invoice_expiry_seconds: number;
  fee_policy: {
    base_fee_msat: number;
    fee_ppm: number;
    max_fee_msat: number;
    note: string;
  };
  sats_to_xp: { xp_per_sat: number; can_change: boolean; note: string };
  custody_disclosure: string[];
}

// XP economy: purchases / receipts (phase 5)

export interface RateOut {
  xp_per_sat: number;
  can_change: boolean;
  note: string;
}

export interface PackOut {
  pack_id: string;
  label: string;
  amount_sats: number;
  xp_amount: number;
}

export interface PurchaseCreateIn {
  pack_id?: string | null;
  amount_sats?: number | null;
  description?: string;
}

export interface PurchaseOut {
  id: string;
  payment_hash: string | null;
  amount_sats: number;
  xp_amount: number;
  status: "pending" | "settled" | "expired";
  bolt11: string | null;
  expires_at: string | null;
  settled_at: string | null;
  ledger_entry_id?: string | null;
  balance_after?: number | null;
  created_at: string;
}

export interface TaskEstimateOut {
  estimated_xp_low: number;
  estimated_xp_high: number;
  basis: string;
  variable_cost_activities: string[];
}

export interface ReconcileReportOut {
  ok: boolean;
  ran_at: string;
  checked_users: number;
  checked_settled_intents: number;
  checked_purchase_entries: number;
  expired_pending_flagged: number;
  discrepancies: Array<Record<string, unknown>>;
}

// Agent runtime: events / approvals (phase 6)

export interface TaskEventOut {
  seq: number;
  event_type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface TaskEventPageOut {
  task_id: string;
  status: string;
  events: TaskEventOut[];
}

export interface TaskStepOut {
  step_index: number;
  tool_name: string | null;
  status: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface ApprovalOut {
  id: string;
  task_id: string | null;
  action_type: string;
  action_digest: string;
  status: "pending" | "approved" | "denied" | "expired" | "revoked";
  created_at: string;
  expires_at: string | null;
}

export interface IncreaseBudgetIn {
  additional_xp: number;
}

export interface SettleTaskIn {
  actual_xp: number;
}

// phase 9: connections / email drafts / automation

export interface ConnectionOut {
  id: string;
  provider: string;
  scopes: string[];
  status: string;
  credential_reference: string | null;
  created_at: string;
  revoked_at: string | null;
  disclosure: string | null;
}

export interface ConnectionProvidersOut {
  providers: Record<
    string,
    {
      label: string;
      scopes: string[];
      required_fields: string[];
      optional_fields: string[];
    }
  >;
  disclosure: string;
}

export interface EmailDraftOut {
  id: string;
  task_id: string | null;
  connection_id: string | null;
  to_address: string;
  subject: string;
  body: string;
  digest: string;
  status: string;
  provider_mode: string | null;
  error: string | null;
  sent_at: string | null;
  created_at: string;
}

export interface AutomationRunOut {
  id: string;
  job_id: string;
  run_number: number;
  trigger: string;
  status: string;
  task_id: string | null;
  xp_charged: number;
  xp_budget_per_run: number;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface JobOut {
  id: string;
  objective: string;
  schedule: string;
  next_run_at: string | null;
  last_run_at: string | null;
  last_run_status: string | null;
  status: "active" | "paused" | "cancelled";
  budget_per_run_xp: number;
  budget_total_xp: number | null;
  total_spent_xp: number;
  run_count: number;
  consecutive_failures: number;
  auto_paused_reason: string | null;
  conditions: Record<string, unknown> | null;
  created_at: string;
}

export interface NotificationOut {
  id: string;
  kind: string;
  payload: Record<string, unknown> | null;
  job_id: string | null;
  run_id: string | null;
  read_at: string | null;
  created_at: string;
}

export interface NotificationsPageOut {
  notifications: NotificationOut[];
  unread: number;
}
