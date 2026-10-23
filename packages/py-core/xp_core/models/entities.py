"""XP data model - product-plan tables (data_model.tables).

Conventions (data_rules):
- UTC datetimes, integer satoshi and integer XP units (never floats),
  UUID string PKs for portability across SQLite (dev) and Postgres (prod).
- Constraints encode invariants at the DB level where feasible.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from xp_core.db import Base, new_id, utcnow

# users & identity


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(32), default="active")  # active|suspended|closed
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    telegram_accounts: Mapped[list[TelegramAccount]] = relationship(back_populates="user")
    xp_account: Mapped[XpAccount | None] = relationship(back_populates="user", uselist=False)


class TelegramAccount(Base):
    __tablename__ = "telegram_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status: Mapped[str] = mapped_column(String(32), default="linked")

    user: Mapped[User] = relationship(back_populates="telegram_accounts")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Phase-2 hardening: visibility + audit for the session lifecycle UI.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_via: Mapped[str] = mapped_column(String(32), default="miniapp")


# wallets


class Wallet(Base):
    """Non-secret wallet metadata only - no seed/private-key fields by design."""

    __tablename__ = "wallets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    wallet_type: Mapped[str] = mapped_column(String(32))  # software|hardware|descriptor
    network: Mapped[str] = mapped_column(String(16))  # mainnet|testnet|signet|regtest
    public_descriptor_or_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WalletAddress(Base):
    __tablename__ = "wallet_addresses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    wallet_id: Mapped[str | None] = mapped_column(
        ForeignKey("wallets.id"), nullable=True, index=True
    )
    address: Mapped[str] = mapped_column(String(128))
    alias: Mapped[str | None] = mapped_column(String(128), nullable=True)
    network: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("address", "network", name="uq_address_network"),)


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    wallet_id: Mapped[str] = mapped_column(ForeignKey("wallets.id"), index=True)
    transaction_reference: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    transaction_type: Mapped[str] = mapped_column(String(32))  # receive|send|internal
    amount_sats: Mapped[int] = mapped_column(BigInteger)
    fee_sats: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    raw_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


# payments & XP


class PaymentIntent(Base):
    __tablename__ = "payment_intents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    provider_reference: Mapped[str | None] = mapped_column(String(191), nullable=True, unique=True)
    amount_sats: Mapped[int] = mapped_column(BigInteger)
    xp_amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="created")
    # receive: created | pending | settled | expired
    # send:    created | prepared | authorized | in_flight | succeeded | failed
    direction: Mapped[str] = mapped_column(String(16), default="receive")
    bolt11: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    fee_msat: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    authorization_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(191), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class XpAccount(Base):
    __tablename__ = "xp_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="xp_account")

    __table_args__ = (CheckConstraint("balance >= 0", name="ck_xp_balance_nonnegative"),)


class XpLedgerEntry(Base):
    """Append-only accounting events. Refunds/corrections append, never rewrite."""

    __tablename__ = "xp_ledger_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    entry_type: Mapped[str] = mapped_column(String(32))
    # purchase | reservation | reservation_release | charge | refund | adjustment
    amount: Mapped[int] = mapped_column(Integer)  # signed; XP integers, never floats
    balance_after: Mapped[int] = mapped_column(Integer)
    reference_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(191), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    __table_args__ = (
        CheckConstraint("amount != 0 OR entry_type = 'charge'", name="ck_ledger_amount"),
    )


# agent tasks


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    objective: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="awaiting_approval")
    # awaiting_approval | planned | running | completed | failed | cancelled
    budget_xp: Mapped[int] = mapped_column(Integer)
    reserved_xp: Mapped[int] = mapped_column(Integer, default=0)
    actual_xp: Mapped[int] = mapped_column(Integer, default=0)
    deliverable: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TaskStep(Base):
    __tablename__ = "task_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    step_index: Mapped[int] = mapped_column(Integer)
    tool_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    input_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    output_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("task_id", "step_index", name="uq_task_step_index"),)


class TaskEvent(Base):
    """Append-only task event stream (phase 6, deliverable: Task event stream
    and progress updates). One row per lifecycle event: plan, step status,
    approval requests/decisions, evaluation, completion. Survives worker
    restarts; GET /tasks/{id}/events replays it in order."""

    __tablename__ = "task_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # monotonic per task
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    __table_args__ = (UniqueConstraint("task_id", "seq", name="uq_task_event_seq"),)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id"), nullable=True, index=True
    )
    action_type: Mapped[str] = mapped_column(String(64))
    action_digest: Mapped[str] = mapped_column(String(64))  # sha256 of canonical action payload
    status: Mapped[str] = mapped_column(String(32), default="pending")
    # pending | approved | denied | expired | revoked
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ConnectedService(Base):
    __tablename__ = "connected_services"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    scopes: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    credential_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="linked")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Artifact(Base):
    """Generated file metadata. Objects live in storage, private by default."""

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    object_key: Mapped[str] = mapped_column(String(255), unique=True)
    content_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending|ready|expired|failed
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ScheduledJob(Base):
    """Recurring automation (phase 9).

    Budget discipline: every spawned run's task budget is capped at
    ``budget_per_run_xp`` AND at whatever remains of ``budget_total_xp``
    (when configured) - the ledger refuses settlement beyond a task's
    budget, so these caps are enforced in backend code, not by the model.
    """

    __tablename__ = "scheduled_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    task_template: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    schedule: Mapped[str] = mapped_column(String(128))  # cron-like expression
    conditions: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    budget_per_run_xp: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="active")  # active|paused|cancelled
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    budget_total_xp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_spent_xp: Mapped[int] = mapped_column(Integer, default=0)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_run_status: Mapped[str | None] = mapped_column(String(48), nullable=True)
    auto_paused_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)


class ResearchSource(Base):
    """Durable provenance for research tasks (phase 7).

    One row per (task, url): search listings start at ``listed`` and are
    upgraded by a successful fetch; unavailable/denied/errored fetches are
    KEPT and disclosed rather than dropped. Facts are typed
    observed|estimate|assumption so reports never pass a listing snapshot
    off as a live quote.
    """

    __tablename__ = "research_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    url: Mapped[str] = mapped_column(String(2048))
    title: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(16), default="listed")
    # listed | ok | unavailable | denied | error
    retrieval_mode: Mapped[str] = mapped_column(String(16), default="canned")  # canned | http
    facts: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    fact_count: Mapped[int] = mapped_column(Integer, default=0)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("task_id", "url", name="uq_research_source_task_url"),)


class ReconciliationAlert(Base):
    """Operator-facing payment/ledger discrepancy alert (phase 10).

    Written by xp_core.jobs.reconciliation when a sweep finds a mismatch.
    One open alert per (kind, subject) - repeat sightings bump last_seen_at
    instead of stacking duplicates, so the queue measures distinct problems,
    not sweep frequency. Acknowledgement and resolution are explicit operator
    actions; nothing here mutates balances (the ledger stays authoritative).
    """

    __tablename__ = "reconciliation_alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # balance_mismatch | settlement_1to1 | expired_pending
    kind: Mapped[str] = mapped_column(String(48), index=True)
    # critical (money-integrity) | warning (housekeeping)
    severity: Mapped[str] = mapped_column(String(16), default="warning")
    # user_id / intent_id / entry id the alert is about
    subject: Mapped[str] = mapped_column(String(72), index=True)
    expected: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # open | acknowledged | resolved
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_note: Mapped[str | None] = mapped_column(String(280), nullable=True)
    # Dedupe of live alerts is application-level (one open row per
    # kind+subject); resolved rows deliberately remain as history, so no
    # hard unique constraint across all statuses.


class AuditEvent(Base):
    """Security and business event trail. Never store secrets in metadata."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_type: Mapped[str] = mapped_column(String(32))  # user|agent|system|admin
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_redacted: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    __table_args__ = (
        Index("ix_audit_event_resource", "event_type", "resource_type", "resource_id"),
    )


class ServiceCredential(Base):
    """Encrypted-at-rest credential for a connected external service (phase 9).

    One row per connection. The payload (e.g. SMTP host/port/password) is
    Fernet-encrypted with the operator-configured master key; the plaintext
    never enters logs, task events, or API responses. Revocation hard-deletes
    the row, so a revoked connection cannot authenticate even if the API
    layer were bypassed.
    """

    __tablename__ = "service_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("connected_services.id"), unique=True, index=True
    )
    ciphertext: Mapped[str] = mapped_column(Text)
    key_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EmailDraft(Base):
    """Email draft with preview-before-send semantics (phase 9).

    ``digest`` is sha256 over the canonical {to, subject, body}; the
    email.send approval binds to the tool action digest, which contains the
    exact same content - the user approves what they previewed. Status moves
    drafted -> sent | failed | unknown_outcome | refused; a sent draft can
    never be sent again (repeat send requires a new draft + new approval).
    """

    __tablename__ = "email_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id"), nullable=True, index=True
    )
    connection_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    to_address: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(512))
    body: Mapped[str] = mapped_column(Text)
    digest: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="drafted")
    # drafted | sent | failed | unknown_outcome | refused
    provider_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow
    )


class AutomationRun(Base):
    """One execution attempt of a scheduled job (phase 9: run history).

    Every attempt - success, failure, or skip - is recorded here with its
    reason. Failures never silently repeat consequential actions: the next
    sweep sees the failure count, and approval-blocked runs surface as
    ``blocked_on_approval`` while pending, then ``skipped_approval_pending``
    on subsequent sweeps (no approval spam, no hidden resend).
    """

    __tablename__ = "automation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("scheduled_jobs.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    run_number: Mapped[int] = mapped_column(Integer)
    trigger: Mapped[str] = mapped_column(String(16), default="scheduled")  # scheduled|manual
    status: Mapped[str] = mapped_column(String(48))
    # running | succeeded | failed | blocked_on_approval | skipped_budget |
    # skipped_total_budget | skipped_cancelled
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id"), nullable=True, index=True
    )
    xp_charged: Mapped[int] = mapped_column(Integer, default=0)
    xp_budget_per_run: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("job_id", "run_number", name="uq_automation_run_number"),
    )


class Notification(Base):
    """Condition-based notification for a user (phase 9).

    Created by backend evaluation of scheduled-job conditions (run outcomes,
    balance thresholds). Persisted and API-readable. The relay fields record
    exactly ONE push decision per notification (phase 9, KL-06):
    ``relay_status`` is sent | refused | unknown | skipped, set together with
    ``relayed_at``; unknown outcomes are never retried automatically.
    """

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("scheduled_jobs.id"), nullable=True
    )
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    relayed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    relay_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    relay_detail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class WalletHandle(Base):
    """A public @username for a user's on-device wallet (per network).

    The server never holds keys. It stores the username, the wallet's
    identity PUBLIC key, and a pool of receive addresses each signed by that
    key (HandleAddress), so payers' phones can verify an address really came
    from @username even if this server were compromised.
    status: active | released (old names stay reserved for a while).
    """

    __tablename__ = "wallet_handles"
    __table_args__ = (UniqueConstraint("network", "username", name="uq_handle_network_username"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    network: Mapped[str] = mapped_column(String(16))
    username: Mapped[str] = mapped_column(String(32))
    identity_pubkey: Mapped[str] = mapped_column(String(66))
    status: Mapped[str] = mapped_column(String(16), default="active")
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Lightning (Spark) address published by the owner's phone, signed by the identity key.
    spark_address: Mapped[str | None] = mapped_column(String(300), nullable=True)
    spark_signature: Mapped[str | None] = mapped_column(String(160), nullable=True)
    spark_network: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class HandleAddress(Base):
    """One signed receive address in a user's pool. status: available | issued."""

    __tablename__ = "handle_addresses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    network: Mapped[str] = mapped_column(String(16), index=True)
    identity_pubkey: Mapped[str] = mapped_column(String(66))
    address: Mapped[str] = mapped_column(String(100), unique=True)
    derivation_index: Mapped[int] = mapped_column(Integer)
    signature: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(16), default="available", index=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PaymentRequest(Base):
    """A shareable request to pay a user (link + QR). status: open | paid | cancelled."""

    __tablename__ = "payment_requests"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    network: Mapped[str] = mapped_column(String(16))
    username: Mapped[str] = mapped_column(String(32))
    address: Mapped[str] = mapped_column(String(100))
    signature: Mapped[str] = mapped_column(String(160))
    identity_pubkey: Mapped[str] = mapped_column(String(66))
    amount_sats: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str | None] = mapped_column(String(140), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    paid_sats: Mapped[int] = mapped_column(BigInteger, default=0)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WalletAlertSetting(Base):
    """A user's opt-in for Telegram messages when their wallet receives bitcoin."""

    __tablename__ = "wallet_alert_settings"
    __table_args__ = (UniqueConstraint("user_id", "network", name="uq_wallet_alert_user_network"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    network: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WatchedAddress(Base):
    """A receive address the user asked us to watch for incoming payments.

    Watch-only: an address, never a key. ``seen`` maps txid -> "p" (pending)
    or "c" (confirmed) so each payment produces at most one "received" and one
    "confirmed" message. The first check only records existing payments
    (``baseline``), so turning alerts on never replays old history.
    """

    __tablename__ = "watched_addresses"
    __table_args__ = (UniqueConstraint("user_id", "address", name="uq_watched_user_address"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    network: Mapped[str] = mapped_column(String(16), index=True)
    address: Mapped[str] = mapped_column(String(100))
    seen: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


ALL_TABLES = [
    User,
    TelegramAccount,
    Session,
    Wallet,
    WalletAddress,
    WalletTransaction,
    PaymentIntent,
    XpAccount,
    XpLedgerEntry,
    Task,
    TaskStep,
    TaskEvent,
    Approval,
    ConnectedService,
    Artifact,
    ScheduledJob,
    ResearchSource,
    ServiceCredential,
    EmailDraft,
    AutomationRun,
    Notification,
    ReconciliationAlert,
    AuditEvent,
    WalletHandle,
    HandleAddress,
    PaymentRequest,
    WalletAlertSetting,
    WatchedAddress,
]
