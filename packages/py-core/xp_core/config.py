"""Central application settings.

All services read the same settings object so configuration stays consistent.
Every value is environment-overridable with the ``XP_`` prefix (12-factor style).
Local development never requires production secrets (Phase 1 acceptance).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="XP_",
        env_file=(".env", "../.env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # environment
    env: Literal["dev", "regtest", "testnet", "staging", "prod"] = "dev"
    log_level: str = "INFO"
    # Relaxes auth for local/sandbox development only. Defaults OFF so a
    # deployment that forgets to configure it fails closed, not open.
    dev_mode: bool = False
    # Demo seam: allow the canned-Lightning "settle-dev" button with real
    # Telegram auth (dev_mode off). Only honoured with lightning_mode=canned.
    demo_lightning_settle: bool = False

    # Operator credential for /ops/* (KL-11). Constant-time compared, never
    # logged, never echoed back. When set it is REQUIRED for every ops
    # request in every environment; when unset, ops surfaces run only in
    # DEV_MODE and refuse (503) anywhere else instead of opening unauthenticated.
    ops_operator_token: str | None = None

    # HTTP
    api_host: str = "0.0.0.0"
    api_port: int = 8001
    cors_origins: list[str] = ["*"]  # tighten per-environment before testnet+
    request_id_header: str = "X-Request-ID"

    # persistence
    # Postgres in shared environments; SQLite keeps local dev zero-dependency.
    database_url: str = "sqlite+aiosqlite:///./data/xp-dev.db"
    db_echo: bool = False

    # queue
    # Redis-backed; a PostgreSQL-backed queue is the documented alternative
    # pending the operational prototype.
    redis_url: str | None = None  # None => inline dev execution of worker jobs

    # artifacts / object storage
    # Local filesystem now; S3-compatible backend later, private by default.
    artifact_dir: str = "./data/artifacts"
    artifact_url_ttl_seconds: int = 600

    # Telegram
    telegram_bot_token: str | None = None
    telegram_init_data_max_age_seconds: int = 86400
    mini_app_url: str = "https://t.me/XPDevBot/app"
    telegram_bot_username: str | None = None  # without @, shown on the extension sign-in screen
    # Short name of the Mini App in BotFather (t.me/<bot>/<short>). Empty: links use the bot's
    # Main Mini App (t.me/<bot>?startapp=...), set in BotFather > Bot Settings > Configure Mini App.
    telegram_miniapp_short_name: str = ""
    # Notification relay (phase 9, KL-06): "canned" records a deterministic
    # local receipt and states that nothing was transmitted; "bot_api" sends
    # for real and refuses to construct without a bot token.
    telegram_relay_mode: str = "canned"
    # Unread notifications older than this are skipped as stale, never pushed.
    telegram_relay_lookback_hours: int = 24

    # sessions
    # Short-lived bearer sessions (trust boundary control: "Short-lived
    # sessions and authorization checks"). The Mini App re-exchanges fresh
    # initData on every launch, so a short TTL costs nothing in UX.
    session_ttl_hours: int = 24
    extension_session_ttl_hours: int = 24 * 30  # browser extension stays signed in
    cors_allow_extensions: bool = True  # chrome-extension:// / moz-extension:// origins

    # pricing
    # ONE canonical conversion: XP credited per satoshi paid. Every surface
    # derives its display from it (published, and "can change" - clients must
    # re-check, never cache). The former sats_per_xp=10 setting contradicted
    # xp_per_sat=100 and was removed.
    xp_per_sat: int = 5  # 1 sat = 5 TK
    tk_welcome_bonus: int = 300  # free TK every account gets once
    tk_min_purchase: int = 500  # smallest TK purchase (= 100 sats at 5 TK/sat)
    tk_max_purchase: int = 50_000_000
    # Satish AI spends from the balance automatically: each task may use up to
    # this much TK (less if the balance is lower); unused TK is never taken.
    agent_auto_budget_xp: int = 1_000
    # Where TK is paid: the operator's own wallets.
    # Lightning: the operator's wallet phrase lets the server create invoices
    # and see them paid (it can also spend - keep only a float there).
    tk_lightning_mnemonic: str | None = None  # never logged
    # Simplest setup: the 12 words of the owner's own Satish wallet. TK paid by
    # Bitcoin lands in that wallet's on-chain side (addresses 0/5000+), TK paid
    # by Lightning lands in its Lightning side. Overrides the two settings
    # above/below when set. Never logged.
    tk_wallet_mnemonic: str | None = None
    tk_lightning_network: str = "regtest"  # regtest | mainnet (mainnet needs breez_api_key)
    breez_api_key: str | None = None
    tk_lightning_storage_dir: str = "/data/tk-lightning"
    tk_payee_username: str = ""  # shown to payers, e.g. "satish"
    # Published XP pack table (billing_flow #1: "chooses an XP pack or enters
    # an allowed amount"). Custom amounts within policy bounds also allowed.
    xp_pack_sats: list[int] = [1_000, 5_000, 20_000]

    # agent / DSH
    # Revision is pinned in services/agent-adapter/dsh_adapter/dsh_revision.json;
    # dsh_revision below is only an informational label.
    dsh_revision: str = "dsh-pin-2026-10-15-flash-v4-1"
    deepseek_api_key: str | None = None
    deepseek_base_url: str | None = None  # None => pinned base_url
    # None => pinned primary model (deepseek-flash). A discontinued legacy
    # alias here fails loudly at client construction (see revision.py).
    deepseek_model: str | None = None

    # wallet
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

    # lightning
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

    # agent runtime
    # Deterministic backend enforcement of plan bounds (dsh_integration #7):
    # max plan steps, default tool timeout, and the maximum plan-estimate
    # discount the worker may trust without re-checking the ledger cap.
    agent_max_steps: int = 12
    agent_default_tool_timeout_seconds: int = 30
    agent_max_budget_xp: int = 100_000
    # Hard limit for one task run on the worker. Anything still "running"
    # STALE_GRACE seconds after this is stopped by the watchdog and refunded.
    agent_task_timeout_seconds: int = 600

    # research tools
    # search: canned (offline eval corpus) or brave (live Brave Search API;
    # needs brave_search_api_key, use with research_fetch_mode=http).
    research_search_mode: str = "canned"
    brave_search_api_key: str | None = None  # never logged
    brave_search_country: str = ""  # e.g. "NG" to favour Nigerian results
    # fetch: canned (offline eval corpus) or http (real retrieval behind the
    # FetchPolicy wall: http/https only, ports 80/443, public IPs only,
    # size + content-type caps, per-hop redirect re-checks).
    research_fetch_mode: str = "canned"
    research_fetch_max_bytes: int = 262_144
    research_fetch_timeout_seconds: int = 20
    # Evaluation corpus for canned search/fetch + the repeatable research
    # evaluation set (phase-7 acceptance #5). Relative to repo root.
    research_eval_set_path: str = "tests/data/research_eval_set.json"

    # commerce intelligence
    # Scoring factor weights as a JSON object; factor names are fixed (see
    # commerce_adapter.scoring.DEFAULT_FACTORS) and weights are operator-
    # configurable. Any defect falls back to the documented defaults WITH a
    # disclosure in the score output - never silently.
    commerce_scoring_factors: str = (
        '{"distinct_sources": 2.0, "supplier_count": 1.5, "price_spread": 1.5, '
        '"freshness": 1.0, "attribute_completeness": 1.0}'
    )
    # Commerce fixture corpus + repeatable commerce evaluation set
    # (phase-8 acceptance bars). Relative to repo root.
    commerce_eval_set_path: str = "tests/data/commerce_eval_set.json"

    # external connections
    # Master key for the credential vault (Fernet over a sha256-derived key).
    # NEVER logged, never returned by any API. In dev mode a documented
    # fallback key keeps local development zero-config, and every response
    # discloses that fallback; non-dev environments refuse to link connections
    # until an operator key is configured.
    connections_credential_key: str | None = None

    # Buy bitcoin (Onramper). The API key is public; the signing key is an
    # Ed25519 private key (PEM) used to sign widget links server-side so the
    # user's own wallet address can be pre-filled safely. Never logged.
    onramper_api_key: str | None = None
    onramper_signing_key: str | None = None
    onramper_default_fiat: str = "NGN"
    onramper_widget_url: str = "https://buy.onramper.com"
    coingecko_api_key: str | None = None  # optional free "demo" key, raises rate limits

    # How XP purchases are paid: "lightning" (built-in demo/lnd flow) or
    # "onchain" (real bitcoin to the operator's watch-only wallet).
    payment_mode: str = "lightning"
    # Operator's BIP84 account PUBLIC key (xpub/tpub/zpub/vpub). The server
    # can derive and watch addresses but never spend. Keep the phrase offline.
    onchain_xpub: str | None = None

    @property
    def tk_onchain_xpub(self) -> str | None:
        """Account xpub TK addresses come from (own Satish wallet if set)."""
        if self.tk_wallet_mnemonic:
            from xp_core.services.onchain import xpub_from_mnemonic

            return xpub_from_mnemonic(self.tk_wallet_mnemonic, self.onchain_network)
        return self.onchain_xpub

    @property
    def tk_ln_mnemonic(self) -> str | None:
        return self.tk_wallet_mnemonic or self.tk_lightning_mnemonic
    onchain_network: Literal["mainnet", "testnet"] = "testnet"  # testnet = testnet4
    onchain_esplora_url: str | None = None  # default: mempool.space for the network
    onchain_min_conf: int = 1  # 0 accepts unconfirmed payments (demo only)
    onchain_request_ttl_minutes: int = 60
    # email.send delivery mode: "canned" (deterministic, no network - the
    # receipt says so) or "smtp" (real delivery via the connection's stored
    # credentials, with an honest definite-vs-unknown outcome taxonomy).
    email_send_mode: str = "canned"

    # approvals + automation
    # Approval expiry: an approval decision binds to the action digest AND a
    # TTL. Execution after expiry re-requests approval - no stale sends.
    approval_ttl_minutes: int = 60
    # Scheduler sweep cadence (worker cron). arq cron is minute-granular.
    automation_sweep_interval_seconds: int = 60
    # Notification relay sweep cadence (worker cron, KL-06).
    relay_sweep_interval_seconds: int = 60
    # Consecutive failed runs before a job auto-pauses (failed jobs do not
    # silently repeat consequential actions - they stop and notify).
    automation_max_consecutive_failures: int = 3
    # A run left "running" longer than this (worker crash) is marked failed on
    # the next sweep; fresher ones are waited on, never run concurrently.
    automation_run_stale_seconds: int = 3600
    # Operator caps on per-job budgets (user input is clamped to these).
    automation_max_budget_per_run_xp: int = 10_000
    automation_use_remaining_balance: bool = True  # low balance: run with what's left
    automation_max_budget_total_xp: int = 100_000

    # worker
    pdf_storage_dir: str = "./data/artifacts"
    reconcile_interval_seconds: int = 3600  # billing_flow #8

    # abuse controls
    # Token buckets per (route class, subject); limits are code-pinned
    # in xp_core.services.ratelimit.RULES (auth tightest, money tight, reads
    # loose). Kill switch for operators. backend=memory is per-process;
    # backend=redis shares buckets across workers through an atomic Lua
    # token bucket and requires redis_url (refuses to construct without it),
    # failing OPEN with a disclosed degraded state when Redis is unreachable.
    rate_limit_enabled: bool = True
    rate_limit_backend: Literal["memory", "redis"] = "memory"
    rate_limit_bucket_ttl_seconds: int = 3600  # idle bucket eviction
    rate_limit_max_buckets: int = 10_000

    # privacy / retention
    # Days after which the retention sweep deletes expired data classes.
    # Money-trail and audit surfaces are never swept (see
    # xp_core/jobs/retention.py PRESERVED_SURFACES and docs/privacy-retention.md).
    retention_sessions_days: int = 7
    retention_notifications_read_days: int = 30
    retention_notifications_unread_days: int = 90
    retention_automation_runs_days: int = 180
    retention_email_drafts_sent_days: int = 30

    @model_validator(mode="after")
    def _refuse_dev_mode_in_shared_envs(self) -> Settings:
        if self.dev_mode and self.env in ("staging", "prod"):
            raise ValueError(
                f"XP_DEV_MODE=true is refused when XP_ENV={self.env}: dev mode "
                "disables authentication"
            )
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
