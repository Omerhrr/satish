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

    # -- pricing (phase 5, finalized) ------------------------------------------
    # ONE canonical conversion: XP credited per satoshi paid. Every surface
    # derives its display from it (pricing_requirements #1: published, and
    # "can change" — clients must re-check, never cache). The former
    # sats_per_xp=10 setting contradicted xp_per_sat=100 and was removed.
    xp_per_sat: int = 100
    # Published XP pack table (billing_flow #1: "chooses an XP pack or enters
    # an allowed amount"). Custom amounts within policy bounds also allowed.
    xp_pack_sats: list[int] = [1_000, 5_000, 20_000]

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

    # -- lightning (phase 4) ----------------------------------------------------
    lightning_mode: str = "canned"  # canned | lnd (lnd v0.21.4-beta via gRPC)
    lightning_network: str = "regtest"  # mainnet refused at provider construction
    lnd_rpc_host: str | None = None  # e.g. 127.0.0.1:10109
    lnd_tls_cert_path: str | None = None
    lnd_macaroon_path: str | None = None
    lightning_invoice_expiry_seconds: int = 3600  # bolt11 expiry for receive intents
    lightning_base_fee_msat: int = 1_000  # fee preview policy (published)
    lightning_fee_ppm: int = 1
    lightning_max_fee_msat: int = 10_000  # fee cap policy (payment authorization)
    lightning_min_inbound_msat: int = 1_000_000  # below this, receive is disclosed as constrained

    # -- agent runtime (phase 6) -------------------------------------------------
    # Deterministic backend enforcement of plan bounds (dsh_integration #7):
    # max plan steps, default tool timeout, and the maximum plan-estimate
    # discount the worker may trust without re-checking the ledger cap.
    agent_max_steps: int = 12
    agent_default_tool_timeout_seconds: int = 30
    agent_max_budget_xp: int = 100_000

    # -- research tools (phase 7) ------------------------------------------------
    # search: canned only (a live provider needs a search API key — none is
    # configured, and pretending otherwise would fabricate results).
    research_search_mode: str = "canned"
    # fetch: canned (offline eval corpus) or http (real retrieval behind the
    # FetchPolicy wall: http/https only, ports 80/443, public IPs only,
    # size + content-type caps, per-hop redirect re-checks).
    research_fetch_mode: str = "canned"
    research_fetch_max_bytes: int = 262_144
    research_fetch_timeout_seconds: int = 20
    # Evaluation corpus for canned search/fetch + the repeatable research
    # evaluation set (phase-7 acceptance #5). Relative to repo root.
    research_eval_set_path: str = "tests/data/research_eval_set.json"

    # -- commerce intelligence (phase 8) ---------------------------------------
    # Scoring factor weights as a JSON object; factor names are fixed (see
    # commerce_adapter.scoring.DEFAULT_FACTORS) and weights are operator-
    # configurable. Any defect falls back to the documented defaults WITH a
    # disclosure in the score output — never silently.
    commerce_scoring_factors: str = (
        '{"distinct_sources": 2.0, "supplier_count": 1.5, "price_spread": 1.5, '
        '"freshness": 1.0, "attribute_completeness": 1.0}'
    )
    # Commerce fixture corpus + repeatable commerce evaluation set
    # (phase-8 acceptance bars). Relative to repo root.
    commerce_eval_set_path: str = "tests/data/commerce_eval_set.json"

    # -- worker ----------------------------------------------------------------
    pdf_storage_dir: str = "./data/artifacts"
    reconcile_interval_seconds: int = 3600  # billing_flow #8

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
