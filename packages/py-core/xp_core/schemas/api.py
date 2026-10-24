"""Pydantic wire schemas shared by API responses and the generated TS client."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# health


class ComponentStatus(BaseModel):
    name: str
    status: Literal["ok", "error", "not_configured"]
    detail: str | None = None


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    env: str
    version: str
    database: ComponentStatus
    queue: ComponentStatus
    agent_runtime: ComponentStatus
    dsh_revision: str


# auth / users


class UserOut(BaseModel):
    id: str
    display_name: str | None
    status: str
    created_at: datetime


class SessionOut(BaseModel):
    session_token: str
    user: UserOut
    mode: Literal["telegram", "dev"]


class SessionInfoOut(BaseModel):
    """Session metadata for the lifecycle UI - never the token or its hash."""

    id: str
    created_via: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime


# TK


class BalanceOut(BaseModel):
    balance_xp: int
    xp_per_sat: int  # the ONE canonical conversion (phase 5)
    updated_at: datetime


class LedgerEntryOut(BaseModel):
    id: str
    entry_type: str
    amount: int
    balance_after: int
    reference_type: str | None
    reference_id: str | None
    note: str | None
    created_at: datetime


class LedgerPageOut(BaseModel):
    items: list[LedgerEntryOut]
    total: int


class DevGrantIn(BaseModel):
    amount_xp: int = Field(gt=0, le=1_000_000)
    reason: str = "dev seed grant"


# purchases / receipts


class PackOut(BaseModel):
    pack_id: str
    label: str
    amount_sats: int
    xp_amount: int


class RateOut(BaseModel):
    xp_per_sat: int
    can_change: bool
    note: str


class PurchaseCreateIn(BaseModel):
    """Choose a published pack OR enter a custom sats amount."""

    pack_id: str | None = Field(default=None, max_length=64)
    amount_sats: int | None = Field(default=None, ge=100, le=100_000_000)
    description: str = Field(default="TK purchase", max_length=500)


class PurchaseOut(BaseModel):
    """A purchase = receive-direction payment intent + TK credit view."""

    id: str
    payment_hash: str | None
    amount_sats: int
    xp_amount: int
    status: str  # pending | settled | expired
    bolt11: str | None
    expires_at: datetime | None
    settled_at: datetime | None
    ledger_entry_id: str | None = None
    balance_after: int | None = None
    created_at: datetime
    payment_method: str = "lightning"  # lightning | onchain
    address: str | None = None  # on-chain: where to pay
    network: str | None = None  # on-chain: mainnet | testnet
    seen_sats: int | None = None  # on-chain: amount seen so far (incl. unconfirmed)


class ReconcileReportOut(BaseModel):
    ok: bool
    ran_at: str
    checked_users: int
    checked_settled_intents: int
    checked_purchase_entries: int
    expired_pending_flagged: int
    discrepancies: list[dict[str, Any]]


class TaskEstimateOut(BaseModel):
    estimated_xp_low: int
    estimated_xp_high: int
    basis: str
    variable_cost_activities: list[str]


class IncreaseBudgetIn(BaseModel):
    additional_xp: int = Field(gt=0, le=100_000)


class SettleTaskIn(BaseModel):
    actual_xp: int = Field(ge=0)


class ReconcileOut(BaseModel):
    ok: bool
    balance: int
    sum_entries: int


# tasks


class TaskCreateIn(BaseModel):
    objective: str = Field(min_length=2, max_length=4000)
    budget_xp: int = Field(gt=0, le=100_000)
    idempotency_key: str | None = Field(default=None, max_length=191)


class TaskOut(BaseModel):
    id: str
    objective: str
    status: str
    budget_xp: int
    reserved_xp: int
    actual_xp: int
    deliverable: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    error: str | None = None  # plain-language reason when status == failed
    queued: bool = False  # handed to the AI worker but not started yet


# task events / approvals


class TaskEventOut(BaseModel):
    seq: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class TaskEventPageOut(BaseModel):
    task_id: str
    status: str
    events: list[TaskEventOut]


class ApprovalOut(BaseModel):
    id: str
    task_id: str | None
    action_type: str
    action_digest: str
    status: str
    created_at: datetime
    expires_at: datetime | None


# task result


class ResultArtifactOut(BaseModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str | None
    download_url: str


class ResultSourceOut(BaseModel):
    url: str
    title: str
    status: str
    retrieval_mode: str
    fact_count: int
    retrieved_at: datetime | None
    note: str | None
    # phase-8: source freshness + confidence indicators (deliverable #7)
    freshness: str = "unknown"  # fresh | recent | stale | outdated | unknown
    confidence: str = "low"  # high | medium | low


class XpReceiptOut(BaseModel):
    budget_xp: int
    actual_xp: int
    released_xp: int
    charge_entry_id: str | None
    settled_at: datetime | None
    balance_after: int | None
    status: str  # settled | pending_settlement | no_charge


class ScoredFactorOut(BaseModel):
    name: str
    weight: float
    signal: str
    normalized: float | None = None
    included: bool
    reason: str = ""


class ScoredOut(BaseModel):
    product: str
    score: float
    factors: list[ScoredFactorOut]
    excluded: list[str] = []
    config_echo: dict[str, float] = {}
    disclosures: list[str] = []


class TaskResultOut(BaseModel):
    task_id: str
    status: str
    objective: str
    deliverable: str | None
    completed_at: datetime | None
    artifacts: list[ResultArtifactOut]
    answer: str | None = None  # the full reply written for the user
    sources: list[ResultSourceOut]
    conflicts: list[dict[str, Any]]
    gaps: list[str]
    limitations: list[str]
    xp_receipt: XpReceiptOut
    # phase-8: latest commerce.scored verdict, if the task scored a candidate
    scored: ScoredOut | None = None


class ApprovalDecisionIn(BaseModel):
    approve: bool


class PlanApprovalIn(BaseModel):
    approve: bool = True


# artifacts


class ArtifactOut(BaseModel):
    id: str
    object_key: str
    content_type: str
    size_bytes: int
    sha256: str | None
    status: str
    download_url: str | None = None
    created_at: datetime


class DemoPdfIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    sections: list[str] = Field(
        default_factory=lambda: ["Summary", "Findings", "Sources"]
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


# wallets


class CapabilitiesOut(BaseModel):
    wallets: str
    lightning: str
    agent_runtime: str
    notes: list[str]


# connections


class ConnectionCreateIn(BaseModel):
    provider: str
    scopes: list[str] | None = None
    # provider-specific payload (e.g. SMTP host/port/username/password);
    # secret fields are encrypted at rest and NEVER returned by any API.
    credential: dict[str, Any]


class ConnectionOut(BaseModel):
    id: str
    provider: str
    scopes: list[str]
    status: str
    credential_reference: str | None = None
    created_at: datetime
    revoked_at: datetime | None = None
    disclosure: str | None = None


# email drafts


class EmailDraftOut(BaseModel):
    id: str
    task_id: str | None
    connection_id: str | None
    to_address: str
    subject: str
    body: str
    digest: str
    status: str
    provider_mode: str | None
    error: str | None
    sent_at: datetime | None
    created_at: datetime


# automation jobs


class JobCreateIn(BaseModel):
    objective: str = Field(min_length=1, max_length=2000)
    schedule: str = Field(min_length=1, max_length=128)
    budget_per_run_xp: int = Field(default=20, ge=1)
    budget_total_xp: int | None = Field(default=None, ge=1)
    conditions: dict[str, Any] | None = None


class AutomationRunOut(BaseModel):
    id: str
    job_id: str
    run_number: int
    trigger: str
    status: str
    task_id: str | None
    xp_charged: int
    xp_budget_per_run: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class JobOut(BaseModel):
    id: str
    objective: str
    schedule: str
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_run_status: str | None
    status: str
    budget_per_run_xp: int
    budget_total_xp: int | None
    total_spent_xp: int
    run_count: int
    consecutive_failures: int
    auto_paused_reason: str | None
    conditions: dict[str, Any] | None
    created_at: datetime


class NotificationsPageOut(BaseModel):
    notifications: list[NotificationOut]
    unread: int


class NotificationOut(BaseModel):
    id: str
    kind: str
    payload: dict[str, Any] | None
    job_id: str | None
    run_id: str | None
    read_at: datetime | None
    relay_status: str | None = None
    created_at: datetime


# ops


class ReconciliationAlertOut(BaseModel):
    id: str
    kind: str
    severity: str
    subject: str
    expected: str | None
    observed: str | None
    detail: dict[str, Any] | None
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    resolved_note: str | None


class ReconciliationAlertsPageOut(BaseModel):
    alerts: list[ReconciliationAlertOut]
    open_critical: int
    open_warning: int


class AlertAckOut(BaseModel):
    id: str
    status: str
    acknowledged_at: datetime | None


class ObservabilityOut(BaseModel):
    """Ops-facing system summary (phase 10). Counts, never row content."""

    env: str
    reconcile_interval_seconds: int
    alerts_open_critical: int
    alerts_open_warning: int
    alerts_resolved_total: int
    rate_limit_enabled: bool
    rate_limit_backend: str
    rate_limit_degraded_checks: int
    retention_policy: dict[str, int]


# account export + closure (KL-10)


class AccountClosureIn(BaseModel):
    confirm: Literal["CLOSE"]


class AccountClosureOut(BaseModel):
    status: str
    closed_at: str
    erased: dict[str, int]
    anonymized: dict[str, int]
    retained: list[str]
    disclosures: list[str]
