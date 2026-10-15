"""Central application settings.

All services read the same settings object so configuration stays consistent.
Every value is environment-overridable with the ``XP_`` prefix (12-factor style).
Local development never requires production secrets (Phase 1 acceptance).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="XP_",
        env_file=(".env", "../.env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- environment ---------------------------------------------------------
    env: Literal["dev", "regtest", "testnet", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    dev_mode: bool = True  # relaxes auth for local/sandbox development only

    # -- HTTP ----------------------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8001
    cors_origins: list[str] = ["*"]  # tighten per-environment before testnet+
    request_id_header: str = "X-Request-ID"

    # -- persistence ---------------------------------------------------------
    # Postgres in shared environments; SQLite keeps local dev zero-dependency.
    database_url: str = "sqlite+aiosqlite:///./data/xp-dev.db"
    db_echo: bool = False

    # -- queue (Redis-backed; PostgreSQL-backed queue is the documented
    #    alternative pending the operational prototype) -----------------------
    redis_url: str | None = None  # None => inline dev execution of worker jobs

    # -- artifacts / object storage ------------------------------------------
    # Local filesystem now; S3-compatible backend later, private by default.
    artifact_dir: str = "./data/artifacts"
    artifact_url_ttl_seconds: int = 600

    # -- Telegram ------------------------------------------------------------
    telegram_bot_token: str | None = None
    telegram_init_data_max_age_seconds: int = 86400
    mini_app_url: str = "https://t.me/XPDevBot/app"

    # -- sessions (phase-2 hardening) ------------------------------------------
    # Short-lived bearer sessions (trust boundary control: "Short-lived
    # sessions and authorization checks"). The Mini App re-exchanges fresh
    # initData on every launch, so a short TTL costs nothing in UX.
    session_ttl_hours: int = 24

    # -- pricing (published sats->XP conversion; pricing_requirements #1) -----
    sats_per_xp: int = 10

    # -- agent / DSH ----------------------------------------------------------
    # Revision is pinned in services/agent-adapter/dsh_adapter/dsh_revision.json
    # (phase-0 spike); dsh_revision below is only an informational label.
    dsh_revision: str = "dsh-pin-2026-10-15-flash-v4-1"
    deepseek_api_key: str | None = None
    deepseek_base_url: str | None = None  # None => pinned base_url
    # None => pinned primary model (deepseek-flash). A discontinued legacy
    # alias here fails loudly at client construction (see revision.py).
    deepseek_model: str | None = None

    # -- wallet (phase-3 on-chain self-custody) -------------------------------
    # BDK-based provider (decision D10). The persisted wallet state uses PUBLIC
    # descriptors only; signing happens in an in-memory private wallet built at
    # unlock from the user's recovery phrase (never written to disk or DB).
    wallet_data_dir: str = "./data/wallets"
    bitcoind_rpc_url: str | None = None  # e.g. http://127.0.0.1:18443
    bitcoind_rpc_user: str | None = None
    bitcoind_rpc_password: str | None = None
    wallet_unlock_ttl_minutes: int = 10  # inactivity lock for the signing vault
    wallet_fallback_fee_rate_sat_vb: int = 2  # when estimatesmartfee has no data
    wallet_max_fee_rate_sat_vb: int = 50  # fee cap policy (transaction_policy)
    wallet_default_word_count: int = 24  # 12 or 24 BIP39 words on creation

    # -- worker ----------------------------------------------------------------
    pdf_storage_dir: str = "./data/artifacts"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
