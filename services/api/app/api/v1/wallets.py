"""Wallets + address book (phase-3: BDK-backed on-chain self-custody).

Flow per transaction (plan transaction_policy):
  prepare  -> review payload {network, destination, amount, fee, warnings} +
             authorization digest binding EXACTLY those fields
  sign     -> requires a fresh unlock (recovery phrase, in-memory TTL vault);
             agent actors are rejected unconditionally
  broadcast-> mempool probe, then send; uncertain outages are explicit

Address aliases are labels only. ``prepare`` accepts either a raw address or
an alias; the digest binds the RESOLVED address, so relabeling the book can
never redirect an already-prepared transaction.

Mainnet remains release-gated (security review); the provider refuses it.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from wallet_adapter import (
    AgentSigningForbidden,
    AuthorizationMismatch,
    BroadcastRejected,
    BroadcastUncertain,
    InsufficientFunds,
    InvalidAddress,
    InvalidAmount,
    InvalidMnemonic,
    MnemonicMismatch,
    NetworkMismatch,
    PreparedTransactionNotFound,
    SigningLocked,
    WalletAlreadyExists,
    WalletError,
    WalletNotFound,
)
from xp_core.models.entities import Wallet, WalletAddress

from app.deps import CurrentUser, DbSession
from app.services import wallet_service as svc

router = APIRouter(tags=["wallets"])


# schemas


class WalletCreateIn(BaseModel):
    label: str = Field(default="", max_length=128)


class WalletRestoreIn(BaseModel):
    mnemonic: str = Field(min_length=24, max_length=512)
    label: str = Field(default="", max_length=128)


class WalletUnlockIn(BaseModel):
    mnemonic: str = Field(min_length=24, max_length=512)


class AddressCreateIn(BaseModel):
    alias: str | None = Field(default=None, max_length=128)


class AddressAliasIn(BaseModel):
    alias: str | None = Field(default=None, max_length=128)  # null clears the label


class PrepareIn(BaseModel):
    destination: str = Field(min_length=1, max_length=128)  # raw address or alias
    amount_sats: int = Field(gt=0)
    fee_rate_sat_vb: int | None = Field(default=None, gt=0, le=1000)


class SignIn(BaseModel):
    prepared_id: str = Field(min_length=8, max_length=64)
    authorization_digest: str = Field(min_length=64, max_length=64)


class BroadcastIn(BaseModel):
    tx_hex: str = Field(min_length=60, max_length=200_000)
    amount_sats: int = 0
    fee_sats: int = 0


def _http_error(exc: Exception) -> HTTPException:
    mapping = {
        WalletNotFound: 404,
        PreparedTransactionNotFound: 404,
        InvalidAddress: 422,
        InvalidAmount: 422,
        InvalidMnemonic: 422,
        NetworkMismatch: 422,
        InsufficientFunds: 409,
        MnemonicMismatch: 403,
        AuthorizationMismatch: 403,
        AgentSigningForbidden: 403,
        SigningLocked: 423,  # Locked
        WalletAlreadyExists: 409,
        BroadcastRejected: 502,
        BroadcastUncertain: 504,
        WalletError: 500,
    }
    code = mapping.get(type(exc), 500)
    return HTTPException(status_code=code, detail=str(exc))


def _wallet_out(row) -> dict:
    ext, _chg = svc.split_descriptors_json(row.public_descriptor_or_reference)
    return {
        "id": row.id,
        "label": row.label or "",
        "network": row.network,
        "wallet_type": row.wallet_type,
        "status": row.status,
        "public_descriptor": ext,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


# endpoints


@router.get("/wallets/capabilities", include_in_schema=True)
async def wallet_capabilities(session: DbSession, user: CurrentUser):
    """Honest capability disclosure for the custody model in this build."""
    return {
        "custody_model": "server-side signing vault, in-memory phrase unlock",
        "not_claimed": [
            "non-custodial (server holds the signing capability while unlocked)",
            "hardware-wallet-level protection",
            "browser-side signing (phase-4+ item)",
        ],
        "secrets_at_rest": "none - persisted state uses public descriptors only",
        "agent_signing": "forbidden by the signing boundary",
        "mainnet": "release-gated on security review",
    }


@router.post("/wallets", status_code=status.HTTP_201_CREATED)
async def create_wallet(payload: WalletCreateIn, session: DbSession, user: CurrentUser):
    provider = svc.get_provider(_settings())
    try:
        created = await provider.create_wallet(label=payload.label)
    except WalletError as exc:
        raise _http_error(exc) from exc
    row = Wallet(
        id=created.wallet_id,  # deterministic descriptor id - matches provider state
        user_id=user.id,
        wallet_type="software",
        network=created.network.value,
        public_descriptor_or_reference=svc.descriptors_json(
            created.public_descriptor, created.change_public_descriptor
        ),
        label=payload.label,
        status="active",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {
        **_wallet_out(row),
        "first_address": created.first_address,
        "mnemonic_once": created.mnemonic_once,
        "mnemonic_display": "one_time - shown now, never again, never stored",
    }


@router.post("/wallets/restore", status_code=status.HTTP_201_CREATED)
async def restore_wallet(payload: WalletRestoreIn, session: DbSession, user: CurrentUser):
    provider = svc.get_provider(_settings())
    try:
        created = await provider.restore_wallet(mnemonic_words=payload.mnemonic, label=payload.label)
    except WalletError as exc:
        raise _http_error(exc) from exc
    from sqlalchemy import select as _select
    existing = (
        await session.execute(_select(Wallet).where(Wallet.id == created.wallet_id))
    ).scalar_one_or_none()
    if existing is not None:
        if existing.user_id != user.id:
            raise HTTPException(status_code=404, detail="wallet not found")
        return {**_wallet_out(existing), "restored": True, "first_address": created.first_address}
    row = Wallet(
        id=created.wallet_id,  # deterministic descriptor id - matches provider state
        user_id=user.id,
        wallet_type="software",
        network=created.network.value,
        public_descriptor_or_reference=svc.descriptors_json(
            created.public_descriptor, created.change_public_descriptor
        ),
        label=payload.label,
        status="active",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {**_wallet_out(row), "restored": True, "first_address": created.first_address}


@router.get("/wallets")
async def list_wallets(session: DbSession, user: CurrentUser):
    rows = (
        await session.execute(
            select(Wallet).where(Wallet.user_id == user.id).order_by(Wallet.created_at.desc())
        )
    ).scalars().all()
    return {"wallets": [_wallet_out(r) for r in rows]}


@router.get("/wallets/{wallet_id}/balance")
async def wallet_balance(wallet_id: str, session: DbSession, user: CurrentUser):
    wallet = await _owned(session, user, wallet_id)
    provider = await svc.ensure_provider_open(session, wallet, _settings())
    try:
        info = await provider.get_balance_info(wallet.id)
    except WalletError as exc:
        raise _http_error(exc) from exc
    return {
        "wallet_id": wallet.id,
        "confirmed_sats": info.confirmed_sats,
        "unconfirmed_sats": info.unconfirmed_sats,
        "total_sats": info.total_sats,
    }


@router.post("/wallets/{wallet_id}/unlock")
async def wallet_unlock(wallet_id: str, payload: WalletUnlockIn, session: DbSession, user: CurrentUser):
    wallet = await _owned(session, user, wallet_id)
    provider = await svc.ensure_provider_open(session, wallet, _settings())
    try:
        info = await provider.unlock(wallet.id, mnemonic_words=payload.mnemonic)
    except WalletError as exc:
        raise _http_error(exc) from exc
    return {
        "wallet_id": wallet.id,
        "unlocked": True,
        "expires_at_epoch": info.expires_at_epoch,
        "note": "signing vault unlocked in memory only; lock() or wait for the TTL",
    }


@router.post("/wallets/{wallet_id}/lock")
async def wallet_lock(wallet_id: str, session: DbSession, user: CurrentUser):
    wallet = await _owned(session, user, wallet_id)
    provider = await svc.ensure_provider_open(session, wallet, _settings())
    await provider.lock(wallet.id)
    return {"wallet_id": wallet.id, "unlocked": False}


@router.post("/wallets/{wallet_id}/addresses", status_code=201)
async def derive_address(wallet_id: str, payload: AddressCreateIn, session: DbSession, user: CurrentUser):
    wallet = await _owned(session, user, wallet_id)
    provider = await svc.ensure_provider_open(session, wallet, _settings())
    if payload.alias:
        conflict = (
            await session.execute(
                select(WalletAddress.id).where(
                    WalletAddress.user_id == user.id, WalletAddress.alias == payload.alias
                )
            )
        ).scalar_one_or_none()
        if conflict is not None:
            raise HTTPException(status_code=409, detail="address alias already in use")
    try:
        address = await provider.derive_address(wallet.id)
    except WalletError as exc:
        raise _http_error(exc) from exc
    row = WalletAddress(
        user_id=user.id,
        wallet_id=wallet.id,
        address=address,
        alias=payload.alias,
        network=wallet.network,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {"id": row.id, "address": address, "alias": payload.alias, "network": wallet.network}


@router.get("/wallets/{wallet_id}/addresses")
async def list_addresses(wallet_id: str, session: DbSession, user: CurrentUser):
    wallet = await _owned(session, user, wallet_id)
    rows = await svc.list_addresses(session, wallet.id)
    return {
        "addresses": [
            {"id": r.id, "address": r.address, "alias": r.alias, "network": r.network}
            for r in rows
        ]
    }


@router.patch("/wallets/{wallet_id}/addresses/{address_id}")
async def set_alias(wallet_id: str, address_id: str, payload: AddressAliasIn, session: DbSession, user: CurrentUser):
    wallet = await _owned(session, user, wallet_id)
    row = (
        await session.execute(
            select(WalletAddress).where(
                WalletAddress.id == address_id, WalletAddress.wallet_id == wallet.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="address not found")
    if payload.alias:
        conflict = (
            await session.execute(
                select(WalletAddress.id).where(
                    WalletAddress.user_id == user.id,
                    WalletAddress.alias == payload.alias,
                    WalletAddress.id != address_id,
                )
            )
        ).scalar_one_or_none()
        if conflict is not None:
            raise HTTPException(status_code=409, detail="address alias already in use")
    row.alias = payload.alias
    await session.commit()
    return {"id": row.id, "address": row.address, "alias": row.alias}


@router.post("/wallets/{wallet_id}/prepare")
async def prepare_transaction(wallet_id: str, payload: PrepareIn, session: DbSession, user: CurrentUser):
    wallet = await _owned(session, user, wallet_id)
    provider = await svc.ensure_provider_open(session, wallet, _settings())

    # alias resolution: labels resolve ONCE here; the digest binds the address
    destination = payload.destination
    resolved_via_alias: str | None = None
    if not destination.startswith(("bc1", "bcrt1", "tb1", "2", "1", "3")):
        try:
            alias_row = await svc.resolve_alias(session, user, payload.destination)
            destination = alias_row.address
            resolved_via_alias = alias_row.alias
        except WalletNotFound as exc:
            raise HTTPException(status_code=404, detail="address alias not found") from exc

    try:
        prepared = await provider.prepare_transaction(
            wallet.id,
            destination=destination,
            amount_sats=payload.amount_sats,
            fee_rate_sat_vb=payload.fee_rate_sat_vb,
        )
        review = provider.prepared_review(prepared.psbt_or_reference)
    except WalletError as exc:
        raise _http_error(exc) from exc
    return {**review, "resolved_via_alias": resolved_via_alias}


@router.post("/wallets/{wallet_id}/sign")
async def sign_transaction(wallet_id: str, payload: SignIn, session: DbSession, user: CurrentUser):
    wallet = await _owned(session, user, wallet_id)
    provider = await svc.ensure_provider_open(session, wallet, _settings())
    try:
        signed = await provider.sign_prepared(
            payload.prepared_id,
            authorization_digest=payload.authorization_digest,
            actor=f"user:{user.id}",  # user identity - never an agent
        )
    except WalletError as exc:
        raise _http_error(exc) from exc
    return {
        "txid": signed.txid,
        "tx_hex": signed.tx_hex,
        "vsize": signed.vsize,
        "fee_sats": signed.fee_sats,
        "next": "review the txid, then POST /broadcast",
    }


@router.post("/wallets/{wallet_id}/broadcast")
async def broadcast_transaction(wallet_id: str, payload: BroadcastIn, session: DbSession, user: CurrentUser):
    wallet = await _owned(session, user, wallet_id)
    provider = await svc.ensure_provider_open(session, wallet, _settings())
    try:
        txid = await provider.broadcast(payload.tx_hex)
    except WalletError as exc:
        raise _http_error(exc) from exc
    row = await svc.record_transaction(
        session,
        wallet_id=wallet.id,
        txid=txid,
        transaction_type="send",
        amount_sats=payload.amount_sats,
        fee_sats=payload.fee_sats,
        metadata={"broadcast": "accepted" if payload.tx_hex else "unknown"},
    )
    return {"txid": txid, "transaction_id": row.id, "status": "pending"}


@router.get("/wallets/{wallet_id}/transactions")
async def wallet_transactions(wallet_id: str, session: DbSession, user: CurrentUser):
    wallet = await _owned(session, user, wallet_id)
    rows = await svc.list_transactions(session, wallet.id)
    return {
        "transactions": [
            {
                "id": r.id,
                "txid": r.transaction_reference,
                "type": r.transaction_type,
                "amount_sats": r.amount_sats,
                "fee_sats": r.fee_sats,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


# helpers


def _settings():
    from xp_core.config import get_settings

    return get_settings()


async def _owned(session: DbSession, user: CurrentUser, wallet_id: str):
    try:
        return await svc.get_owned_wallet(session, user, wallet_id)
    except WalletNotFound as exc:
        raise HTTPException(status_code=404, detail="wallet not found") from exc
