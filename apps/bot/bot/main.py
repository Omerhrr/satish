"""Telegram command router - all 14 commands from user_experiences.

Run: python -m bot.main
Requires XP_TELEGRAM_BOT_TOKEN; every security-sensitive command deep-links
into the Nuxt Mini App rather than handling keys in chat.
"""

from __future__ import annotations

import os

import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
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
    builder.button(text="⚡ Open XP", web_app=WebAppInfo(url=settings.mini_app_url))
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


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Welcome to <b>XP</b> 👋\n\n"
        "Get research, reports and everyday work done by an AI assistant, "
        "and pay for it in bitcoin.\n\n"
        "1. Buy XP credits with sats over Lightning\n"
        "2. Tell the assistant what you need and set a budget\n"
        "3. Get your answer or PDF report. Unused XP comes back to you\n\n"
        f"{SECURITY_NOTE}\n\n"
        "Tap <b>Open XP</b> to get started, or send /help.",
        reply_markup=mini_app_keyboard(get_settings()),
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>What I can do</b>\n"
        "/xp - check your XP balance\n"
        "/fund - buy XP with bitcoin\n"
        "/research - ask the assistant to research something\n"
        "/tasks - see your tasks and reports\n"
        "/automations - tasks that repeat on a schedule\n"
        "/connections - connect your email\n"
        "/wallet - your bitcoin wallet\n"
        "/settings - security and your account\n\n"
        f"{SECURITY_NOTE}",
        parse_mode=ParseMode.HTML,
        reply_markup=mini_app_keyboard(get_settings()),
    )


@router.message(Command("wallet", "receive", "send", "addresses", "history", "balance"))
async def cmd_wallet(message: Message) -> None:
    await _open_app(message, "Your wallet opens inside XP, so nothing sensitive ends up in this chat.")


@router.message(Command("settings"))
async def cmd_settings(message: Message) -> None:
    await _open_app(message, "Security, sign-ins and your data are under Security in XP.")


@router.message(Command("xp"))
async def cmd_xp(message: Message) -> None:
    await _open_app(message, "⚡ Your XP balance and history are on the XP home screen.")


@router.message(Command("fund"))
async def cmd_fund(message: Message) -> None:
    await _open_app(
        message,
        "Open XP, go to Buy XP and pick a pack. Pay the Lightning invoice and "
        "your XP arrives as soon as the payment is confirmed.",
    )


@router.message(Command("research"))
async def cmd_research(message: Message) -> None:
    await _open_app(
        message,
        "Open XP, go to Tasks and describe what you need: compare products, "
        "find suppliers, research a car, or any question. You approve the "
        "budget before anything starts.",
    )


@router.message(Command("tasks"))
async def cmd_tasks(message: Message) -> None:
    await _open_app(message, "Your tasks, progress and reports are under Tasks in XP.")


@router.message(Command("automations"))
async def cmd_automations(message: Message) -> None:
    await _open_app(
        message,
        "Set up tasks that repeat on a schedule under Automations in XP. "
        "You set a spending cap, and nothing is emailed without your OK.",
    )


@router.message(Command("connections"))
async def cmd_connections(message: Message) -> None:
    await _open_app(message, "Connect your email under Connect in XP.")


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
