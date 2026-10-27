"""Price alerts and savings goals.

Price alerts: "tell me when bitcoin is above ₦150m". Checked every minute by
the worker (sweep_price_alerts); fires once through the Telegram relay, then
switches off. Savings goals: name, target (sats or any currency) and an
optional deadline. Progress is worked out on the phone from the wallet
balance, which the server never sees.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from xp_core.logging import get_logger
from xp_core.models.entities import Notification, PriceAlert, SavingsGoal

from app.deps import CurrentUser, DbSession

log = get_logger(__name__)
router = APIRouter(tags=["money"])
MAX_ALERTS = 20
MAX_GOALS = 20


def fmt_money(value: float, code: str) -> str:
    symbols = {"NGN": "₦", "USD": "$", "EUR": "€", "GBP": "£", "GHS": "GH₵", "KES": "KSh", "ZAR": "R", "INR": "₹"}
    v = f"{value:,.0f}" if value >= 100 else f"{value:,.2f}"
    return f"{symbols[code]}{v}" if code in symbols else f"{v} {code}"


class AlertIn(BaseModel):
    currency: str = Field(min_length=3, max_length=8)
    direction: Literal["above", "below"]
    target: float = Field(gt=0)


class AlertOut(BaseModel):
    id: str
    currency: str
    direction: str
    target: float
    active: bool
    triggered_at: datetime | None
    created_at: datetime


def _alert_out(a: PriceAlert) -> AlertOut:
    return AlertOut(id=a.id, currency=a.currency, direction=a.direction, target=a.target, active=a.active,
                    triggered_at=a.triggered_at, created_at=a.created_at)


@router.get("/alerts/price", response_model=list[AlertOut])
async def list_alerts(user: CurrentUser, session: DbSession) -> list[AlertOut]:
    rows = await session.execute(select(PriceAlert).where(PriceAlert.user_id == user.id).order_by(PriceAlert.created_at.desc()))
    return [_alert_out(a) for a in rows.scalars()]


@router.post("/alerts/price", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
async def create_alert(payload: AlertIn, user: CurrentUser, session: DbSession) -> AlertOut:
    n = len((await session.execute(select(PriceAlert.id).where(PriceAlert.user_id == user.id, PriceAlert.active))).all())
    if n >= MAX_ALERTS:
        raise HTTPException(422, f"You can have up to {MAX_ALERTS} active alerts.")
    a = PriceAlert(user_id=user.id, currency=payload.currency.upper(), direction=payload.direction, target=payload.target)
    session.add(a)
    await session.commit()
    return _alert_out(a)


@router.delete("/alerts/price/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_alert(alert_id: str, user: CurrentUser, session: DbSession) -> None:
    await session.execute(delete(PriceAlert).where(PriceAlert.id == alert_id, PriceAlert.user_id == user.id))
    await session.commit()


async def sweep_price_alerts(session: AsyncSession, rates: dict[str, float]) -> int:
    """Fire every active alert whose condition is met (once each)."""
    if not rates:
        return 0
    fired = 0
    rows = (await session.execute(select(PriceAlert).where(PriceAlert.active))).scalars().all()
    now = datetime.now(UTC).replace(tzinfo=None)
    for a in rows:
        price = rates.get(a.currency)
        if not price:
            continue
        hit = price >= a.target if a.direction == "above" else price <= a.target
        if not hit:
            continue
        a.active = False
        a.triggered_at = now
        session.add(
            Notification(
                user_id=a.user_id,
                kind="price.alert",
                payload={
                    "currency": a.currency,
                    "direction": a.direction,
                    "price": price,
                    "target": a.target,
                    "price_text": fmt_money(price, a.currency),
                    "target_text": fmt_money(a.target, a.currency),
                },
            )
        )
        fired += 1
    await session.commit()
    return fired


class GoalIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    target_amount: float = Field(gt=0)
    currency: str = Field(min_length=3, max_length=8)  # SAT or a fiat code
    deadline: datetime | None = None
    weekly_reminder: bool = False


class GoalOut(GoalIn):
    id: str
    reached_at: datetime | None
    created_at: datetime


def _goal_out(g: SavingsGoal) -> GoalOut:
    return GoalOut(id=g.id, name=g.name, target_amount=g.target_amount, currency=g.currency, deadline=g.deadline,
                   weekly_reminder=g.weekly_reminder, reached_at=g.reached_at, created_at=g.created_at)


@router.get("/goals", response_model=list[GoalOut])
async def list_goals(user: CurrentUser, session: DbSession) -> list[GoalOut]:
    rows = await session.execute(select(SavingsGoal).where(SavingsGoal.user_id == user.id).order_by(SavingsGoal.created_at))
    return [_goal_out(g) for g in rows.scalars()]


@router.post("/goals", response_model=GoalOut, status_code=status.HTTP_201_CREATED)
async def create_goal(payload: GoalIn, user: CurrentUser, session: DbSession) -> GoalOut:
    n = len((await session.execute(select(SavingsGoal.id).where(SavingsGoal.user_id == user.id))).all())
    if n >= MAX_GOALS:
        raise HTTPException(422, f"You can have up to {MAX_GOALS} goals.")
    g = SavingsGoal(user_id=user.id, name=payload.name.strip(), target_amount=payload.target_amount,
                    currency=payload.currency.upper(), deadline=payload.deadline.replace(tzinfo=None) if payload.deadline else None,
                    weekly_reminder=payload.weekly_reminder)
    session.add(g)
    await session.commit()
    return _goal_out(g)


@router.post("/goals/{goal_id}/reached", response_model=GoalOut)
async def goal_reached(goal_id: str, user: CurrentUser, session: DbSession) -> GoalOut:
    """The phone saw the balance reach the goal: celebrate once in Telegram."""
    g = await session.scalar(select(SavingsGoal).where(SavingsGoal.id == goal_id, SavingsGoal.user_id == user.id))
    if g is None:
        raise HTTPException(404, "goal not found")
    if g.reached_at is None:
        g.reached_at = datetime.now(UTC).replace(tzinfo=None)
        session.add(Notification(user_id=user.id, kind="savings.goal_reached", payload={"name": g.name}))
        await session.commit()
    return _goal_out(g)


@router.delete("/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(goal_id: str, user: CurrentUser, session: DbSession) -> None:
    await session.execute(delete(SavingsGoal).where(SavingsGoal.id == goal_id, SavingsGoal.user_id == user.id))
    await session.commit()
