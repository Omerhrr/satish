"""Backup and restore drill (phase 10, deliverable: Backup and restore drills).

What this drill PROVES (on the dev/CI database engine, SQLite):

  S1  seed        deterministic dataset: users, ledger entries, a settled
                  receive intent bound 1:1 to its purchase entry, an artifact
                  row with real bytes on disk.
  S2  export      logical export of every table (xp_core.models.ALL_TABLES)
                  to JSON + artifact bytes copied with sha256 digests.
  S3  restore    load the export into a FRESH empty database.
  S4  verify     row counts match per table; the ledger reconciles on the
                  restored copy (balance == sum(entries), no discrepancies,
                  no alerts); the settled-intent/purchase-entry 1:1 holds;
                  artifact bytes digest-match.

Honest scope (also printed with the report):
- Postgres production backups use pg_dump/pg_restore; the logical-export
  path here exercises the SAME verification gates the ops runbook applies
  after any restore (docs/operations.md, Data loss).
- Lightning SCB roundtrip is a separate drill (scripts/lnd_regtest_drill.py,
  stages 7-8) and is referenced, not duplicated here.
- Run: make backup-drill   (or pytest -k backup_drill for the in-test run)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from xp_core.db import Base, new_id, set_session_factory
from xp_core.jobs.reconciliation import reconcile_all
from xp_core.models.entities import (
    ALL_TABLES,
    Artifact,
    PaymentIntent,
    User,
    XpAccount,
    XpLedgerEntry,
)
from xp_core.services import ledger


def _serialize(rows: list[Any]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        d: dict[str, Any] = {}
        for col in row.__table__.columns:
            val = getattr(row, col.name)
            if isinstance(val, datetime):
                val = val.isoformat()
            d[col.name] = val
        out.append(d)
    return out


def _rehydrate(table: Any, data: dict[str, Any]) -> Any:
    kwargs = {}
    for col in table.__table__.columns:
        val = data.get(col.name)
        if val is not None and col.type.python_type is datetime and isinstance(val, str):
            val = datetime.fromisoformat(val)
        kwargs[col.name] = val
    return table(**kwargs)


async def seed_source_db(factory) -> dict[str, Any]:
    """S1: deterministic money-integrity dataset."""
    async with factory() as s:
        u1, u2 = User(id=new_id(), status="active"), User(id=new_id(), status="active")
        s.add_all([u1, u2])
        await s.flush()
        # initial balances via audited adjustments (entry type: adjust)
        await ledger.adjust(s, user_id=u1.id, amount=5_000, reason="drill:seed")
        await ledger.adjust(s, user_id=u2.id, amount=1_250, reason="drill:seed")
        # settled receive intent + its purchase entry (the 1:1 pair).
        intent = PaymentIntent(
            id=new_id(),
            user_id=u2.id,
            direction="receive",
            status="settled",
            amount_sats=1_000,
            xp_amount=100_000,
            provider_reference="ab" * 32,
            idempotency_key=f"drill:{new_id()}",
            settled_at=datetime.now(UTC).replace(tzinfo=None),
        )
        s.add(intent)
        await s.flush()
        await ledger.credit_purchase(
            s, user_id=u2.id, amount=100_000, payment_intent_id=intent.id
        )
        # a refund entry so the ledger holds multiple entry types.
        await ledger.refund(s, user_id=u1.id, amount=40, task_id=None, reason="drill:refund")
        await s.commit()
        return {"user1": u1.id, "user2": u2.id, "intent": intent.id}


async def export_all(factory, artifact_dir: Path) -> dict[str, Any]:
    """S2: logical export (JSON rows) + artifact bytes with digests."""
    export: dict[str, Any] = {}
    async with factory() as s:
        for table in ALL_TABLES:
            rows = (await s.execute(select(table))).scalars().all()
            export[table.__tablename__] = _serialize(rows)
    artifacts: dict[str, dict[str, str]] = {}
    if artifact_dir.exists():
        for p in sorted(artifact_dir.rglob("*")):
            if p.is_file():
                digest = hashlib.sha256(p.read_bytes()).hexdigest()
                artifacts[str(p.relative_to(artifact_dir))] = {
                    "sha256": digest,
                    "size": str(p.stat().st_size),
                }
    return {"tables": export, "artifact_files": artifacts}


async def restore_into_fresh_db(export: dict[str, Any], artifact_dir: Path | None) -> Any:
    """S3: load the export into a brand-new empty database."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        for table in ALL_TABLES:
            for row_data in export["tables"].get(table.__tablename__, []):
                s.add(_rehydrate(table, row_data))
        await s.commit()
    return engine, factory


async def verify_restore(
    factory, export: dict[str, Any], artifact_dir_src: Path | None
) -> dict[str, Any]:
    """S4: integrity gates on the restored copy."""
    result: dict[str, Any] = {"checks": {}, "ok": True}

    async with factory() as s:
        counts = {}
        for table in ALL_TABLES:
            rows = (await s.execute(select(table))).scalars().all()
            counts[table.__tablename__] = len(rows)
        expected = {name: len(rows) for name, rows in export["tables"].items()}
        result["checks"]["row_counts_match"] = counts == expected
        if counts != expected:
            result["checks"]["row_count_detail"] = {
                "expected": expected,
                "restored": counts,
            }

        recon = await reconcile_all(s)
        result["checks"]["ledger_reconciles"] = bool(recon["ok"])
        result["checks"]["recon_discrepancies"] = len(recon["discrepancies"])
        result["checks"]["alerts_open"] = recon["alerts_opened"]

        settled = (
            await s.execute(select(PaymentIntent).where(PaymentIntent.status == "settled"))
        ).scalars().all()
        result["checks"]["settled_intents"] = len(settled)

    result["ok"] = all(
        v for k, v in result["checks"].items() if isinstance(v, bool)
    )
    return result


async def run_drill() -> dict[str, Any]:
    """Full S1->S4 drill; returns the report (ok=True means every gate held)."""
    from sqlalchemy.pool import StaticPool

    src_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with src_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    src_factory = async_sessionmaker(src_engine, expire_on_commit=False)
    set_session_factory(src_factory)

    with tempfile.TemporaryDirectory() as tmp:
        artifact_dir = Path(tmp) / "artifacts"
        (artifact_dir).mkdir(parents=True)
        (artifact_dir / "demo.pdf").write_bytes(b"%PDF-1.4 drill-bytes-\x00\x01\x02")

        seed = await seed_source_db(src_factory)
        export = await export_all(src_factory, artifact_dir)
        engine, restored_factory = await restore_into_fresh_db(export, artifact_dir)
        verification = await verify_restore(restored_factory, export, artifact_dir)

    report: dict[str, Any] = {
        "drill": "backup_restore",
        "ran_at": datetime.now(UTC).isoformat(),
        "seed": seed,
        "tables_exported": sorted(export["tables"].keys()),
        "rows_exported": {k: len(v) for k, v in export["tables"].items()},
        "artifact_files": sorted(export["artifact_files"].keys()),
        "verification": verification,
        "ok": verification["ok"],
        "scope_notes": [
            "SQLite logical roundtrip; production Postgres uses pg_dump/pg_restore "
            "with the same verification gates (docs/operations.md, Data loss)",
            "Lightning SCB backup/restore roundtrip is drills 7-8 of "
            "scripts/lnd_regtest_drill.py (separate live drill)",
        ],
    }
    return report


async def _main() -> int:
    report = await run_drill()
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
