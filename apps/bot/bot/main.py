"""Telegram command router — all 14 commands from user_experiences.

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
    "⚠️ I will never ask for your seed phrase or private keys — "
    "anyone who does is trying to steal your bitcoin."
)


def mini_app_keyboard(settings=None):
    settings = settings or get_settings()
    builder = InlineKeyboardBuilder()
    builder.button(text="🔓 Open XP Mini App", web_app=WebAppInfo(url=settings.mini_app_url))
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


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    settings = get_settings()
    await message.answer(
        "Welcome to <b>XP</b> — your Bitcoin-native AI workforce.\n\n"
        "Self-custody first: your keys, your bitcoin. "
        "I help you run research, business intelligence, and document jobs "
        "paid in sats via XP credits.\n\n"
        f"{SECURITY_NOTE}\n\n"
        "Tap below to open the Mini App, or try /help.",
        reply_markup=mini_app_keyboard(settings),
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>Commands</b>\n"
        "/wallet — wallet overview (Mini App)\n"
        "/receive — receive bitcoin\n"
        "/send — send bitcoin (Mini App confirmation)\n"
        "/addresses — address book\n"
        "/history — transaction history\n"
        "/balance — on-chain balance\n"
        "/xp — XP balance and usage receipts\n"
        "/fund — buy XP credits with sats\n"
        "/research — start a research task\n"
        "/tasks — running and past tasks\n"
        "/automations — scheduled jobs\n"
        "/settings — security and recovery\n\n"
        f"{SECURITY_NOTE}",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("wallet", "receive", "send", "addresses", "history", "settings"))
async def cmd_to_mini_app(message: Message) -> None:
    await message.answer(
        "This flow runs inside the Mini App so your data stays out of chat history.",
        reply_markup=mini_app_keyboard(get_settings()),
    )


@router.message(Command("balance"))
async def cmd_balance(message: Message) -> None:
    data = await _api_get("/health")
    if data is None:
        await message.answer("API is unreachable right now — try again shortly.")
        return
    await message.answer(
        "Balances live in the Mini App wallet view — on-chain (phase 3) and "
        "Lightning invoices/payments (phase 4) are wired end-to-end there.",
        reply_markup=mini_app_keyboard(get_settings()),
    )


@router.message(Command("xp"))
async def cmd_xp(message: Message) -> None:
    data = await _api_get("/xp/balance")
    if data is None:
        await message.answer("XP service is unreachable — try again shortly.")
        return
    await message.answer(
        f"⚡ XP balance: <b>{data['balance_xp']:,} XP</b>\n"
        f"Rate: 1 sat = {data['xp_per_sat']} XP\n\n"
        "XP is an internal usage credit — not Bitcoin, not a token.",
        parse_mode=ParseMode.HTML,
        reply_markup=mini_app_keyboard(get_settings()),
    )


@router.message(Command("fund"))
async def cmd_fund(message: Message) -> None:
    await message.answer(
        "XP purchases flow through the Mini App: choose a pack, review the "
        "sats cost, pay from your wallet, and the credit lands once payment "
        "settles — credited exactly once.",
        reply_markup=mini_app_keyboard(get_settings()),
    )


@router.message(Command("research"))
async def cmd_research(message: Message) -> None:
    await message.answer(
        "Describe your objective and constraints in the Mini App task form. "
        "The agent proposes a plan with an XP estimate; you approve the budget "
        "before anything runs.",
        reply_markup=mini_app_keyboard(get_settings()),
    )


@router.message(Command("tasks"))
async def cmd_tasks(message: Message) -> None:
    await message.answer(
        "Task plans, progress, and receipts are tracked in the Mini App.",
        reply_markup=mini_app_keyboard(get_settings()),
    )


@router.message(Command("automations"))
async def cmd_automations(message: Message) -> None:
    await message.answer(
        "Scheduled research jobs and monitors live in the Mini App automations "
        "screen, always within granted scopes and budgets.",
        reply_markup=mini_app_keyboard(get_settings()),
    )


@router.message(F.text.startswith("/"))
async def unknown_command(message: Message) -> None:
    await message.answer("Unknown command — try /help.")


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
