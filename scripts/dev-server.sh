#!/usr/bin/env bash
# XP dev-server bootstrap used by the sandbox preview supervisor.
# Starts: FastAPI (:8001, SQLite dev DB) + Nuxt Mini App (:3000, foreground).
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # -> xp/
export XP_DATABASE_URL="${XP_DATABASE_URL:-sqlite+aiosqlite:////$ROOT/data/xp-dev.db}"
export XP_ARTIFACT_DIR="${XP_ARTIFACT_DIR:-$ROOT/data/artifacts}"
export XP_DEV_MODE="${XP_DEV_MODE:-true}"
export XP_ENV="${XP_ENV:-dev}"

mkdir -p "$ROOT/data/artifacts"

# -- 1. FastAPI on :8001 (skip if already healthy) -----------------------------
if ! curl -sf http://127.0.0.1:8001/healthz >/dev/null 2>&1; then
  cd "$ROOT/services/api"
  "$ROOT/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8001 >> "$ROOT/data/api.log" 2>&1 &
  echo "[xp] uvicorn starting on :8001 (pid $!)"
else
  echo "[xp] uvicorn already healthy on :8001"
fi

# wait briefly for API readiness
for i in $(seq 1 30); do
  curl -sf http://127.0.0.1:8001/healthz >/dev/null 2>&1 && break
  sleep 1
done

# -- 2. Nuxt Mini App on :3000 (foreground process) ----------------------------
cd "$ROOT/apps/web"
# Gateway mode by default (single exposed port via XTransformPort). Override
# with an explicit empty NUXT_PUBLIC_API_PORT to use direct API_BASE mode.
export NUXT_PUBLIC_API_PORT="${NUXT_PUBLIC_API_PORT-8001}"
export NUXT_PUBLIC_API_BASE="${NUXT_PUBLIC_API_BASE-http://127.0.0.1:8001}"
echo "[xp] starting nuxt on :3000 (apiPort='$NUXT_PUBLIC_API_PORT' apiBase='$NUXT_PUBLIC_API_BASE')"
exec bun run dev --port 3000
