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
