"""XP data model — 16 tables from the product plan (data_model.tables).

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

# -- users & identity ---------------------------------------------------------


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
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True)  # unique mapping
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


# -- wallets -------------------------------------------------------------------


class Wallet(Base):
    """Non-secret wallet metadata only — no seed/private-key fields by design."""

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


# -- payments & XP ---------------------------------------------------------------


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


# -- agent tasks -----------------------------------------------------------------


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
    AuditEvent,
]
