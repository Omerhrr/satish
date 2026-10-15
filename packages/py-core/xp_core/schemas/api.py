"""Pydantic wire schemas shared by API responses and the generated TS client."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# -- health ---------------------------------------------------------------------


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


# -- auth / users -----------------------------------------------------------------


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
    """Session metadata for the lifecycle UI — never the token or its hash."""

    id: str
    created_via: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime


# -- XP ---------------------------------------------------------------------------


class BalanceOut(BaseModel):
    balance_xp: int
    sats_per_xp: int
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


# -- tasks ------------------------------------------------------------------------


class TaskCreateIn(BaseModel):
    objective: str = Field(min_length=8, max_length=4000)
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


# -- artifacts ---------------------------------------------------------------------


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
    sections: list[str] = Field(default_factory=lambda: ["Summary", "Findings", "Sources"])
    metadata: dict[str, Any] = Field(default_factory=dict)


# -- wallets (scaffold contract shape) ----------------------------------------------


class CapabilitiesOut(BaseModel):
    wallets: str
    lightning: str
    agent_runtime: str
    notes: list[str]
