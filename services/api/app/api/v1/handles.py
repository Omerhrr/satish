"""@usernames for on-device wallets and shareable payment requests."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from xp_core.config import get_settings
from xp_core.logging import get_logger
from xp_core.models.entities import PaymentRequest
from xp_core.services import handles as svc

from app.deps import CurrentUser, DbSession

log = get_logger(__name__)
router = APIRouter(tags=["handles"])

Network = Literal["mainnet", "testnet"]


class SignedAddressIn(BaseModel):
    address: str = Field(min_length=26, max_length=100)
    index: int = Field(ge=0, le=1_000_000)
    signature: str = Field(min_length=16, max_length=160)


class ClaimIn(BaseModel):
    network: Network
    username: str = Field(min_length=3, max_length=21)
    identity_pubkey: str = Field(min_length=66, max_length=66)
    addresses: list[SignedAddressIn] = Field(default_factory=list, max_length=svc.UPLOAD_MAX)


class TopUpIn(BaseModel):
    network: Network
    identity_pubkey: str = Field(min_length=66, max_length=66)
    addresses: list[SignedAddressIn] = Field(max_length=svc.UPLOAD_MAX)


class HandleMeOut(BaseModel):
    username: str | None
    identity_pubkey: str | None
    available: int
    max_index: int
    issued_max_index: int


class HandleOut(BaseModel):
    username: str
    identity_pubkey: str


class IssuedAddressOut(BaseModel):
    username: str
    address: str
    signature: str
    identity_pubkey: str
    reused: bool


class LightningIn(BaseModel):
    network: Network
    identity_pubkey: str = Field(min_length=66, max_length=66)
    ln_network: Literal["mainnet", "regtest", "signet"]
    spark_address: str = Field(min_length=20, max_length=300)
    signature: str = Field(min_length=16, max_length=160)


class LightningOut(BaseModel):
    username: str
    identity_pubkey: str
    ln_network: str
    spark_address: str
    signature: str


class RequestIn(BaseModel):
    network: Network
    amount_sats: int | None = Field(default=None, ge=546)
    note: str | None = Field(default=None, max_length=140)


class RequestOut(BaseModel):
    id: str
    url: str
    network: str
    username: str
    address: str
    signature: str
    identity_pubkey: str
    amount_sats: int | None
    note: str | None
    status: str
    paid_sats: int
    created_at: str
    paid_at: str | None


def _bad(exc: svc.HandleError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


def _items(rows: list[SignedAddressIn]) -> list[svc.SignedAddress]:
    return [svc.SignedAddress(address=r.address.strip(), index=r.index, signature=r.signature.strip().lower()) for r in rows]


def _request_out(r: PaymentRequest) -> RequestOut:
    base = get_settings().mini_app_url.rstrip("/")
    return RequestOut(
        id=r.id,
        url=f"{base}/pay/{r.id}",
        network=r.network,
        username=r.username,
        address=r.address,
        signature=r.signature,
        identity_pubkey=r.identity_pubkey,
        amount_sats=r.amount_sats,
        note=r.note,
        status=r.status,
        paid_sats=r.paid_sats,
        created_at=r.created_at.isoformat(),
        paid_at=r.paid_at.isoformat() if r.paid_at else None,
    )


# ------------------------------------------------------------- usernames


@router.get("/handles/check")
async def check_name(username: str, network: Network, user: CurrentUser, session: DbSession) -> dict:
    reason = await svc.name_availability(session, network, username, user)
    return {"username": svc.normalize_username(username), "available": not reason, "reason": reason or None}


@router.post("/handles/claim", response_model=HandleMeOut)
async def claim(payload: ClaimIn, user: CurrentUser, session: DbSession) -> HandleMeOut:
    try:
        row = await svc.claim(
            session, user, network=payload.network, username=payload.username,
            identity_pubkey=payload.identity_pubkey.lower(), addresses=_items(payload.addresses),
        )
    except svc.HandleError as exc:
        raise _bad(exc) from exc
    pool = await svc.pool_status(session, user, payload.network)
    await session.commit()
    return HandleMeOut(username=row.username, identity_pubkey=row.identity_pubkey, **pool)


@router.get("/handles/me", response_model=HandleMeOut)
async def me(network: Network, user: CurrentUser, session: DbSession) -> HandleMeOut:
    row = await svc.my_handle(session, user, network)
    pool = await svc.pool_status(session, user, network)
    return HandleMeOut(username=row.username if row else None, identity_pubkey=row.identity_pubkey if row else None, **pool)


@router.post("/handles/addresses", response_model=HandleMeOut)
async def top_up(payload: TopUpIn, user: CurrentUser, session: DbSession) -> HandleMeOut:
    row = await svc.my_handle(session, user, payload.network)
    if row is None or row.identity_pubkey != payload.identity_pubkey.lower():
        raise HTTPException(status_code=409, detail="This wallet doesn't own your username. Claim it again from this wallet.")
    try:
        await svc.add_addresses(session, user, payload.network, row.identity_pubkey, _items(payload.addresses))
    except svc.HandleError as exc:
        raise _bad(exc) from exc
    pool = await svc.pool_status(session, user, payload.network)
    await session.commit()
    return HandleMeOut(username=row.username, identity_pubkey=row.identity_pubkey, **pool)


@router.get("/handles/lookup/{username}", response_model=HandleOut)
async def lookup(username: str, network: Network, user: CurrentUser, session: DbSession) -> HandleOut:
    row = await svc.active_handle(session, network, svc.normalize_username(username))
    if row is None:
        raise HTTPException(status_code=404, detail=f"No Satish user called @{svc.normalize_username(username)}.")
    return HandleOut(username=row.username, identity_pubkey=row.identity_pubkey)


@router.post("/handles/lightning", response_model=LightningOut)
async def publish_lightning(payload: LightningIn, user: CurrentUser, session: DbSession) -> LightningOut:
    try:
        h = await svc.set_lightning(
            session, user, network=payload.network, identity_pubkey=payload.identity_pubkey.lower(),
            ln_network=payload.ln_network, spark_address=payload.spark_address, signature=payload.signature.strip().lower(),
        )
    except svc.HandleError as exc:
        raise _bad(exc) from exc
    await session.commit()
    return LightningOut(username=h.username, identity_pubkey=h.identity_pubkey, ln_network=h.spark_network or "",
                        spark_address=h.spark_address or "", signature=h.spark_signature or "")


@router.get("/handles/{username}/lightning", response_model=LightningOut)
async def lightning_address(username: str, network: Network, user: CurrentUser, session: DbSession) -> LightningOut:
    name = svc.normalize_username(username)
    h = await svc.active_handle(session, network, name)
    if h is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No Satish user called @{name}.")
    if not h.spark_address or not h.spark_signature:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"@{name} hasn't opened Lightning yet. Pay them from your Bitcoin wallet, or ask them to open Lightning once.")
    return LightningOut(username=h.username, identity_pubkey=h.identity_pubkey, ln_network=h.spark_network or "",
                        spark_address=h.spark_address, signature=h.spark_signature)


@router.post("/handles/{username}/address", response_model=IssuedAddressOut)
async def address_for(username: str, network: Network, user: CurrentUser, session: DbSession) -> IssuedAddressOut:
    row = await svc.active_handle(session, network, svc.normalize_username(username))
    if row is None:
        raise HTTPException(status_code=404, detail=f"No Satish user called @{svc.normalize_username(username)}.")
    try:
        addr, reused = await svc.issue_address(session, row)
    except svc.HandleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return IssuedAddressOut(
        username=row.username, address=addr.address, signature=addr.signature, identity_pubkey=addr.identity_pubkey, reused=reused
    )


# ------------------------------------------------------------- payment requests


@router.post("/requests", response_model=RequestOut, status_code=201)
async def create_request(payload: RequestIn, user: CurrentUser, session: DbSession) -> RequestOut:
    try:
        req = await svc.create_request(session, user, network=payload.network, amount_sats=payload.amount_sats, note=payload.note)
    except svc.HandleError as exc:
        raise _bad(exc) from exc
    await session.commit()
    return _request_out(req)


@router.get("/requests", response_model=list[RequestOut])
async def my_requests(user: CurrentUser, session: DbSession, limit: int = Query(default=30, ge=1, le=100)) -> list[RequestOut]:
    rows = (
        await session.execute(
            select(PaymentRequest).where(PaymentRequest.user_id == user.id).order_by(PaymentRequest.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [_request_out(r) for r in rows]


@router.get("/requests/{request_id}", response_model=RequestOut)
async def get_request(request_id: str, session: DbSession) -> RequestOut:
    """Public: anyone with the link can see and pay the request."""
    req = await session.get(PaymentRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="This payment request doesn't exist.")
    try:
        await svc.refresh_request(session, req, get_settings())
    except Exception as exc:
        log.warning("request_check_failed", request_id=req.id, error=str(exc))
    return _request_out(req)


@router.post("/requests/{request_id}/cancel", response_model=RequestOut)
async def cancel_request(request_id: str, user: CurrentUser, session: DbSession) -> RequestOut:
    req = await session.get(PaymentRequest, request_id)
    if req is None or req.user_id != user.id:
        raise HTTPException(status_code=404, detail="This payment request doesn't exist.")
    if req.status == "open":
        req.status = "cancelled"
        await session.commit()
    return _request_out(req)
