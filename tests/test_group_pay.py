"""Pay and split in Telegram groups."""

from __future__ import annotations

from xp_core.config import get_settings
from xp_core.models.entities import TelegramAccount, User, WalletHandle

from app.api.v1.device_link import bot_key
from app.api.v1.group_pay import card_text, parse_amount
from tests.test_agent_runtime import client  # noqa: F401


def test_parse_amounts():
    assert parse_amount("500") == (500, "SAT")
    assert parse_amount("₦2,000") == (2000, "NGN")
    assert parse_amount("2000ngn") == (2000, "NGN")
    assert parse_amount("$5") == (5, "USD")
    assert parse_amount("2k ngn") == (2000, "NGN")
    assert parse_amount("1000 sats") == (1000, "SAT")
    assert parse_amount("lots") is None


async def _handle(session, name: str, tg_id: int, tg_username: str):
    u = User(display_name=name)
    session.add(u)
    await session.flush()
    session.add(TelegramAccount(user_id=u.id, telegram_user_id=tg_id, username=tg_username))
    session.add(WalletHandle(user_id=u.id, network=get_settings().onchain_network, username=name, identity_pubkey="02" + "a" * 64))
    await session.commit()
    return u


async def test_split_card_and_paid_ticks(client, session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", "7000:TEST")
    await _handle(session, "ada", 501, "ada_tg")
    await _handle(session, "musa", 502, "musa_tg")

    async def fake_rates():
        return {"btc": {"NGN": 160_000_000}}

    import app.api.v1.price as price

    monkeypatch.setattr(price, "current_rates", fake_rates)
    r = (
        await client.post(
            "/api/v1/group/create",
            headers={"X-Bot-Key": bot_key("7000:TEST")},
            json={"kind": "split", "telegram_user_id": 501, "username": "ada_tg", "amount": "₦9000",
                  "participants": ["@musa_tg", "@bola"], "note": "dinner"},
        )
    ).json()
    assert r["status"] == "ok" and r["start_param"] == f"gp_{r['id']}"
    assert "₦3,000 each" in r["text"] and "to @ada" in r["text"] and "⬜ @musa_tg" in r["text"]

    g = (await client.get(f"/api/v1/group/{r['id']}")).json()
    assert g["to_username"] == "ada" and g["amount_sats"] == round(3000 / 160_000_000 * 1e8)

    # pay: a Telegram @mention resolves to that person's Satish username
    p = (await client.post("/api/v1/group/create", headers={"X-Bot-Key": bot_key("7000:TEST")},
                           json={"kind": "pay", "telegram_user_id": 501, "amount": "1500", "to": "@musa_tg"})).json()
    assert p["status"] == "ok" and "@musa" in p["text"] and "1,500 sats" in p["text"]

    unknown = (await client.post("/api/v1/group/create", headers={"X-Bot-Key": bot_key("7000:TEST")},
                                 json={"kind": "pay", "telegram_user_id": 501, "amount": "1500", "to": "@nobody"})).json()
    assert unknown == {"status": "unknown_user", "who": "nobody"}

    assert (await client.post(f"/api/v1/group/{r['id']}/paid", json={"ref": "ab" * 32})).status_code == 200
    assert (await client.get(f"/api/v1/group/{r['id']}")).json()["already_paid"] is True


def test_card_text_counts_paid():
    from xp_core.models.entities import GroupPayment

    g = GroupPayment(id="x", kind="split", creator_user_id="u", to_username="ada", amount_sats=1875, display="₦3,000",
                     note="dinner", participants=["musa", "bola"], paid={"musa": "tx"})
    t = card_text(g)
    assert "✅ @musa" in t and "⬜ @bola" in t and "1 of 2 paid" in t


async def test_split_invites_links_and_decline(client, session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "telegram_bot_token", "7000:TEST")
    monkeypatch.setattr(s, "telegram_miniapp_short_name", "")
    await _handle(session, "ada", 601, "ada_tg")
    await _handle(session, "musa", 602, "musa_tg")
    r = (
        await client.post(
            "/api/v1/group/create",
            headers={"X-Bot-Key": bot_key("7000:TEST")},
            json={"kind": "split", "telegram_user_id": 601, "username": "ada_tg", "first_name": "Ada", "amount": "3000",
                  "participants": ["@musa_tg", "@stranger"], "bot_username": "SatishBot"},
        )
    ).json()
    # Opens inside Telegram as a Mini App, not as a web page
    assert r["pay_url"] == f"https://t.me/SatishBot?startapp=gp_{r['id']}"
    assert r["invite"] == [{"username": "musa_tg", "telegram_user_id": 602}]
    assert r["not_on_satish"] == ["stranger"] and r["from_name"] == "Ada"

    no = (await client.post(f"/api/v1/group/{r['id']}/decline", headers={"X-Bot-Key": bot_key("7000:TEST")},
                            json={"telegram_user_id": 602})).json()
    assert no["status"] == "declined" and no["creator_telegram_id"] == 601
    from xp_core.models.entities import GroupPayment

    g = await session.get(GroupPayment, r["id"])
    await session.refresh(g)
    assert "❌ @musa_tg" in card_text(g)
    outsider = (await client.post(f"/api/v1/group/{r['id']}/decline", headers={"X-Bot-Key": bot_key("7000:TEST")},
                                  json={"telegram_user_id": 601})).json()
    assert outsider["status"] == "not_invited"


def test_short_name_link(monkeypatch):
    from app.api.v1.group_pay import mini_app_link

    monkeypatch.setattr(get_settings(), "telegram_miniapp_short_name", "app")
    assert mini_app_link("gp_x", "SatishBot") == "https://t.me/SatishBot/app?startapp=gp_x"
