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

    # -- pricing (published sats->XP conversion; pricing_requirements #1) -----
    sats_per_xp: int = 10

    # -- agent / DSH ----------------------------------------------------------
    dsh_revision: str = "unpinned-spike-0"  # pin a tested revision per plan
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # -- worker ----------------------------------------------------------------
    pdf_storage_dir: str = "./data/artifacts"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
