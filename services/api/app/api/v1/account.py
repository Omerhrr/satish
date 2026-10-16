"""Account self-service (KL-10): data export + ledger-aware closure.

Export returns the caller's data as a downloadable JSON document; secrets
(token hashes, credential ciphertexts) are never included and their absence
is disclosed in the document itself. Closure refuses with precise reasons
while anything is in flight, requires a clean reconciliation, then erases
user content, anonymizes identity, and keeps the immutable money/evidence
trail - the full contract is xp_core.services.closure and
docs/privacy-retention.md.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import JSONResponse
from xp_core.schemas.api import AccountClosureIn, AccountClosureOut
from xp_core.services.closure import ClosureBlocked, close_account, export_user_data

from app.deps import CurrentUser, DbSession, SettingsDep

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/export")
async def export_my_data(user: CurrentUser, session: DbSession) -> Response:
    """Download everything the system stores about the caller."""
    document = await export_user_data(session, user)
    filename = f"xp-account-export-{user.id}.json"
    return JSONResponse(
        content=document,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/closure", response_model=AccountClosureOut)
async def close_my_account(
    payload: AccountClosureIn,
    user: CurrentUser,
    session: DbSession,
    settings: SettingsDep,
) -> AccountClosureOut:
    """Permanent, ledger-aware self-serve closure (requires confirm=CLOSE)."""
    if user.status == "closed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="account is already closed"
        )
    try:
        result = await close_account(session, user, settings)
    except ClosureBlocked as blocked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reasons": blocked.reasons},
        ) from blocked
    return AccountClosureOut(**result)
