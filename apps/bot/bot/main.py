"""Telegram command router - all 14 commands from user_experiences.

Run: python -m bot.main
Requires XP_TELEGRAM_BOT_TOKEN; every security-sensitive command deep-links
into the Nuxt Mini App rather than handling keys in chat.
"""

from __future__ import annotations

import os
import re
from urllib.parse import quote

import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    Message,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from xp_core.config import get_settings
from xp_core.logging import get_logger, setup_logging

log = get_logger(__name__)
router = Router(name="commands")

SECURITY_NOTE = (
    "🔒 I will never ask for your recovery phrase or private keys. "
    "Anyone who does is trying to steal your bitcoin."
)


def mini_app_keyboard(settings=None):
    settings = settings or get_settings()
    builder = InlineKeyboardBuilder()
    builder.button(text="⚡ Open Satish", web_app=WebAppInfo(url=settings.mini_app_url))
    return builder.as_markup()


def _api_url() -> str:
    return os.environ.get("XP_BOT_API_URL", "http://127.0.0.1:8001/api/v1")


async def _api_get(path: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{_api_url()}{path}")
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        return None
    return None


async def _open_app(message: Message, text: str) -> None:
    if message.chat.type != "private":
        # Groups can't show Mini App buttons; a t.me link still opens Satish inside Telegram.
        me = await message.bot.get_me()
        short = (get_settings().telegram_miniapp_short_name or "").strip("/")
        kb = InlineKeyboardBuilder()
        kb.button(text="⚡ Open Satish", url=f"https://t.me/{me.username}/{short}" if short else f"https://t.me/{me.username}?startapp=home")
        await message.answer(text, reply_markup=kb.as_markup())
        return
    await message.answer(text, reply_markup=mini_app_keyboard(get_settings()))


def _app_button(text: str, path: str):
    settings = get_settings()
    base = settings.mini_app_url.rstrip("/")
    builder = InlineKeyboardBuilder()
    builder.button(text=text, web_app=WebAppInfo(url=f"{base}{path}"))
    return builder.as_markup()


_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{6,24}$")


@router.message(CommandStart(deep_link=True))
async def cmd_start_deep_link(message: Message, command: CommandObject) -> None:
    """t.me/<bot>?start=pay_<id> from a shared payment link."""
    arg = (command.args or "").strip()
    if arg.startswith("pay_") and _REQUEST_ID.match(arg[4:]):
        await message.answer(
            "Someone sent you a payment request. Tap below to check it and pay from your Satish wallet.",
            reply_markup=_app_button("⚡ Review and pay", f"/?pay={arg[4:]}"),
        )
        return
    await cmd_start(message)


@router.message(Command("request"))
async def cmd_request(message: Message, command: CommandObject) -> None:
    """/request 5000 rice -> opens the request screen pre-filled."""
    parts = (command.args or "").split(maxsplit=1)
    query = "?request=1"
    if parts and parts[0].replace(",", "").isdigit():
        query += f"&amount={parts[0].replace(',', '')}"
        if len(parts) > 1:
            query += "&note=" + quote(parts[1][:140])
    elif parts:
        query += "&note=" + quote(" ".join(parts)[:140])
    await message.answer(
        "Create a payment link you can share on WhatsApp or anywhere. Anyone can pay it with bitcoin.",
        reply_markup=_app_button("⇄ Create payment link", f"/{query}"),
    )


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Welcome to <b>Satish</b> 👋\n\n"
        "Your own bitcoin wallet, right here in Telegram. Only you hold the keys.\n\n"
        "• Send and receive bitcoin, and see it in naira\n"
        "• Get a @username so friends can pay you by name\n"
        "• Share payment links on WhatsApp, payable from any wallet\n"
        "• Pay an AI assistant for research and reports with TK credits\n\n"
        f"{SECURITY_NOTE}\n\n"
        "Tap <b>Open Satish</b> to get started, or send /help.",
        reply_markup=mini_app_keyboard(get_settings()),
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>What I can do</b>\n"
        "/wallet - your bitcoin wallet\n"
        "/request 5000 rice - make a payment link to share\n"
        "/research - ask the AI assistant to research something\n"
        "/tk - your TK credits for the AI assistant\n"
        "/fund - buy TK credits with bitcoin\n"
        "/tasks - see your tasks and reports\n"
        "/automations - tasks that repeat on a schedule\n"
        "/connections - connect your email\n"
        "/link CODE - sign in the Satish browser extension\n"
        "/pay ₦2000 @friend, /split ₦10000 @a @b - pay or split bills in group chats\n"
        "Just type a question to chat with Satish AI. /new starts a fresh chat, /forget clears what I remember.\n"
        "/settings - security and your account\n\n"
        f"{SECURITY_NOTE}",
        parse_mode=ParseMode.HTML,
        reply_markup=mini_app_keyboard(get_settings()),
    )


@router.message(Command("wallet", "receive", "send", "addresses", "history", "balance"))
async def cmd_wallet(message: Message) -> None:
    await _open_app(message, "Your wallet opens inside Satish, so nothing sensitive ends up in this chat.")


@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    await _open_app(message, "Security, sign-ins and your data are under Security in Satish.")


@router.message(Command("tk", "xp"))
async def cmd_xp(message: Message) -> None:
    await _open_app(message, "⚡ Your TK credits and history are under AI assistant in Satish.")


@router.message(Command("fund"))
async def cmd_fund(message: Message) -> None:
    await _open_app(
        message,
        "Open Satish, go to Satish AI > Credits, choose how much TK you want "
        "(1 sat = 5 TK, from 500 TK) and pay with Lightning or Bitcoin. Your "
        "TK arrives as soon as the payment is seen.",
    )


@router.message(Command("research"))
async def cmd_research(message: Message) -> None:
    await _open_app(
        message,
        "Open Satish, go to Tasks and describe what you need: compare products, "
        "find suppliers, research a car, or any question. It takes TK only "
        "for what it uses, and sends the result here.",
    )


@router.message(Command("tasks"))
async def cmd_tasks(message: Message) -> None:
    await _open_app(message, "Your tasks, progress and reports are under Tasks in Satish.")


@router.message(Command("automations"))
async def cmd_automations(message: Message) -> None:
    await _open_app(
        message,
        "Set up tasks that repeat on a schedule under Automations in Satish. "
        "You set a spending cap, and nothing is emailed without your OK.",
    )


@router.message(Command("connections"))
async def cmd_connections(message: Message) -> None:
    await _open_app(message, "Connect your email under Connect in Satish.")


async def link_device(code: str, user) -> str:
    """Ask the API to connect a waiting browser extension to this Telegram account."""
    import hashlib

    settings = get_settings()
    key = hashlib.sha256(f"satish-device-link|{settings.telegram_bot_token}".encode()).hexdigest()
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(
                f"{_api_url()}/auth/link/confirm",
                headers={"X-Bot-Key": key},
                json={
                    "code": code,
                    "telegram_user_id": user.id,
                    "username": user.username,
                    "first_name": user.first_name,
                },
            )
        status_ = resp.json().get("status") if resp.status_code == 200 else None
    except Exception:
        status_ = None
    if status_ == "linked":
        return (
            "✅ Your Satish browser extension is now signed in as you. "
            "Same account, same TK. Your wallet stays on each device: restore it "
            "in the extension with your 12 words if you want the same one there."
        )
    if status_ == "not_found":
        return "That code didn't match or has expired. Open the extension and try a new code."
    return "I couldn't reach Satish just now. Please try again in a moment."


@router.message(Command("link"))
async def cmd_link(message: Message, command: CommandObject) -> None:
    code = (command.args or "").strip()
    if not code:
        await message.answer(
            "To sign in the Satish browser extension, open it, then send me the code it shows, "
            "like: /link K7QF-2M9P"
        )
        return
    await message.answer(await link_device(code, message.from_user))


GROUP_HELP = (
    "Pay or split in this chat:\n"
    "/pay ₦2000 @musa lunch - send @musa ₦2,000 in bitcoin\n"
    "/split ₦10000 @ada @musa dinner - everyone named pays you their share\n"
    "Amounts can be sats (500), naira (₦2000 or 2000ngn), dollars ($5) or any currency."
)


async def _bot_post(path: str, body: dict) -> dict | None:
    import hashlib

    key = hashlib.sha256(f"satish-device-link|{get_settings().telegram_bot_token}".encode()).hexdigest()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{_api_url()}{path}", headers={"X-Bot-Key": key}, json=body)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


GROUP_ERRORS = {
    "bad_amount": "I couldn't read that amount. Try 500, ₦2000, 2000ngn or $5.",
    "no_recipient": "Who should get paid? Like: /pay ₦2000 @musa",
    "unknown_user": "@{who} doesn't have a Satish username yet. They can open Satish and pick one.",
    "no_people": "Name the people to split with, like: /split ₦10000 @ada @musa dinner",
    "no_username": "Pick your Satish username first (open Satish > Wallet), so people know where to pay you.",
    "no_rate": "I couldn't get the exchange rate right now. Try the amount in sats.",
}


async def _post_card(message: Message, kind: str, args: str) -> None:
    parts = (args or "").split()
    if not parts:
        await message.answer(GROUP_HELP)
        return
    # The amount may be "2000 ngn" (two words) or "₦2000".
    amount = parts[0]
    rest = parts[1:]
    if rest and re.fullmatch(r"[A-Za-z]{3}|sats?", rest[0]):
        amount += rest.pop(0)
    mentions = [p for p in rest if p.startswith("@")]
    note = " ".join(p for p in rest if not p.startswith("@")) or None
    u = message.from_user
    me = await message.bot.get_me()
    body = {
        "kind": kind, "telegram_user_id": u.id, "username": u.username, "first_name": u.first_name,
        "amount": amount, "note": note, "chat_id": message.chat.id, "bot_username": me.username,
    }
    if kind == "pay":
        body["to"] = mentions[0] if mentions else None
    else:
        body["participants"] = mentions
    r = await _bot_post("/group/create", body)
    if not r or r.get("status") != "ok":
        st = (r or {}).get("status", "")
        await message.answer(GROUP_ERRORS.get(st, "Satish couldn't make that card right now.").format(who=(r or {}).get("who", "")))
        return
    # A t.me link opens Satish as a Mini App inside Telegram (a plain web link opens a browser).
    kb = InlineKeyboardBuilder()
    kb.button(text="💸 Pay in Satish", url=r["pay_url"])
    sent = await message.answer(r["text"], reply_markup=kb.as_markup())
    await _bot_post(f"/group/{r['id']}/message", {"message_id": sent.message_id})
    if kind == "split":
        await _invite(message, r)


async def _invite(message: Message, r: dict) -> None:
    """Privately ask each person in a split to accept (and pay) or decline."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    base = get_settings().mini_app_url.rstrip("/")
    first_line = r["text"].splitlines()[0].replace("🧾 ", "")
    missed = list(r.get("not_on_satish") or [])
    for person in r.get("invite") or []:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Accept & pay", web_app=WebAppInfo(url=f"{base}/?gp={r['id']}")),
            InlineKeyboardButton(text="❌ Decline", callback_data=f"gpd:{r['id']}"),
        ]])
        try:
            await message.bot.send_message(
                person["telegram_user_id"],
                f"🧾 {r.get('from_name', 'Someone')} split a bill with you in {message.chat.title or 'a chat'}.\n"
                f"{first_line}\n\nAccept to pay your share from your Satish wallet, or decline.",
                reply_markup=kb,
            )
        except Exception:
            missed.append(person["username"])
    if missed:
        await message.answer(
            "I couldn't message " + ", ".join(f"@{m}" for m in missed)
            + " privately. They need to open Satish once (tap the bot and press Start); they can still pay from the card above."
        )


@router.callback_query(F.data.startswith("gpd:"))
async def split_declined(call) -> None:
    gid = call.data.split(":", 1)[1]
    r = await _bot_post(f"/group/{gid}/decline", {"telegram_user_id": call.from_user.id})
    status_ = (r or {}).get("status")
    if status_ == "declined":
        await call.message.edit_text(call.message.text + "\n\n❌ You declined this split.")
        if r.get("creator_telegram_id"):
            try:
                await call.bot.send_message(
                    r["creator_telegram_id"],
                    f"@{r['who']} declined your split" + (f" for {r['note']}" if r.get("note") else "") + f" ({r['display']}).",
                )
            except Exception:
                pass
        await call.answer("Declined")
    elif status_ == "already_paid":
        await call.answer("You've already paid this one ✅", show_alert=True)
    else:
        await call.answer("This split isn't available any more.", show_alert=True)


@router.message(Command("pay"))
async def cmd_pay(message: Message, command: CommandObject) -> None:
    await _post_card(message, "pay", command.args or "")


@router.message(Command("split"))
async def cmd_split(message: Message, command: CommandObject) -> None:
    await _post_card(message, "split", command.args or "")


async def ask_ai(message: Message, text: str, command: str | None = None) -> dict | None:
    import hashlib

    settings = get_settings()
    key = hashlib.sha256(f"satish-device-link|{settings.telegram_bot_token}".encode()).hexdigest()
    u = message.from_user
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_api_url()}/ai/chat",
                headers={"X-Bot-Key": key},
                json={
                    "telegram_user_id": u.id,
                    "username": u.username,
                    "first_name": u.first_name,
                    "language_code": u.language_code,
                    "text": text[:4000],
                    "command": command,
                },
            )
        return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


CHAT_REPLIES = {
    "started": "🔎 On it. I'll reply here when I'm done.",
    "busy": "⏳ I'm still working on your last question. I'll answer that first.",
    "no_tk": "You're out of TK. Open Satish, go to Satish AI > Credits to top up (every sat buys 5 TK).",
    "forgotten": "🧹 Done. I've forgotten everything I remembered about you and our recent chat.",
    "new_chat": "🆕 New chat started. Ask me anything.",
}


@router.message(Command("forget"))
async def cmd_forget(message: Message) -> None:
    r = await ask_ai(message, "forget", command="forget")
    await message.answer(CHAT_REPLIES.get((r or {}).get("status", ""), "I couldn't reach Satish AI just now."))


@router.message(Command("new"))
async def cmd_new(message: Message) -> None:
    r = await ask_ai(message, "new", command="new")
    await message.answer(CHAT_REPLIES.get((r or {}).get("status", ""), "I couldn't reach Satish AI just now."))


@router.message(Command("ask"))
async def cmd_ask(message: Message, command: CommandObject) -> None:
    if not (command.args or "").strip():
        await message.answer("Ask me anything, like: /ask what's the price of a 50kg bag of rice in Kaduna?")
        return
    await chat_reply(message, command.args)


async def chat_reply(message: Message, text: str) -> None:
    r = await ask_ai(message, text)
    status_ = (r or {}).get("status", "")
    if status_ == "remembered":
        await message.answer(f"📝 Got it, I'll remember: {r.get('fact')}")
        return
    await message.answer(CHAT_REPLIES.get(status_, "I couldn't reach Satish AI just now. Please try again."))


@router.message(F.chat.type == "private", F.document)
async def private_document(message: Message) -> None:
    """A PDF or text file sent to the bot: Satish AI reads it and answers the caption."""
    from xp_core.services.file_text import extract_text

    doc = message.document
    if (doc.file_size or 0) > 10 * 1024 * 1024:
        await message.answer("That file is too big (10 MB max).")
        return
    buf = await message.bot.download(doc)
    text = extract_text(buf.read() if buf else b"", doc.file_name or "", doc.mime_type or "")
    if not text:
        await message.answer("I can read PDFs and text files (txt, csv, md). For photos, type out what you need for now.")
        return
    question = (message.caption or "Summarise this file and point out anything important.").strip()
    await chat_reply(message, f"{question}\n\n[Attached file: {doc.file_name}]\n{text}")


@router.message(F.chat.type == "private", F.photo | F.voice)
async def private_media(message: Message) -> None:
    await message.answer(
        "I can't read photos or voice notes yet. Send the question as text, or a PDF/text file, and I'll take it from there."
    )


@router.message(F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def private_chat(message: Message) -> None:
    """Talk to Satish AI by just messaging the bot."""
    await chat_reply(message, message.text or "")


@router.message(F.text.startswith("/"))
async def unknown_command(message: Message) -> None:
    await message.answer("Sorry, I don't know that one. Send /help to see what I can do.")


async def main() -> None:
    setup_logging(get_settings().log_level)
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise SystemExit(
            "XP_TELEGRAM_BOT_TOKEN is not set. Create a bot with @BotFather, "
            "set the token, and run again."
        )
    bot = Bot(token=settings.telegram_bot_token)
    dp = Dispatcher()
    dp.include_router(router)
    log.info("bot_starting", mini_app_url=settings.mini_app_url)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
