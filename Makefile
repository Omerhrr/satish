# XP monorepo developer entrypoints.
VENV := .venv
PY := $(VENV)/bin/python
API_URL := sqlite+aiosqlite:////$(CURDIR)/data/xp-dev.db

.PHONY: help install migrate run-api run-worker run-bot run-web test lint dsh-verify research-eval commerce-eval wallet-regtest lightning-drill compose-up compose-down

help:
	@echo "install      - install python (uv) + node (bun) dependencies"
	@echo "migrate      - apply database migrations"
	@echo "run-api      - FastAPI on :8001"
	@echo "run-worker   - arq worker (needs XP_REDIS_URL)"
	@echo "dsh-verify   - live-verify the pinned DSH revision (needs XP_DEEPSEEK_API_KEY)"
	@echo "research-eval - run the committed research evaluation set (phase 7)"
	@echo "commerce-eval - run the committed commerce evaluation set (phase 8)"
	@echo "wallet-regtest - end-to-end BDK+bitcoind regtest proof (spawns its own node)"
	@echo "lightning-drill - two-node lnd regtest drill (invoice/payment/recovery; needs healthy zmq)"
	@echo "run-bot      - Telegram bot (needs XP_TELEGRAM_BOT_TOKEN)"
	@echo "run-web      - Nuxt Mini App on :3000"
	@echo "test / lint  - pytest / ruff"
	@echo "compose-up   - Postgres + Redis via infra/docker-compose.yml"

install:
	uv pip install --python $(PY) -e packages/py-core -e services/api -e services/worker \
	        -e services/agent-adapter -e services/wallet-adapter -e services/lightning-adapter -e services/research-adapter -e services/commerce-adapter -e services/email-adapter -e apps/bot
	bun install

migrate:
	cd services/api && XP_DATABASE_URL=$(API_URL) ../../$(VENV)/bin/alembic upgrade head

run-api:
	cd services/api && XP_DATABASE_URL=$(API_URL) ../../$(VENV)/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

run-worker:
	cd services/worker && ../../$(VENV)/bin/arq worker.settings.WorkerSettings

run-bot:
	cd apps/bot && ../../$(VENV)/bin/python -m bot.main

run-web:
	cd apps/web && bun run dev --port 3000

test:
	$(PY) -m pytest tests/ -q

lint:
	$(PY) -m ruff check packages services apps tests

dsh-verify:
	$(PY) scripts/dsh_live_check.py

research-eval:
	$(PY) scripts/research_eval.py

commerce-eval:
	$(PY) scripts/commerce_eval.py

wallet-regtest:
	$(PY) scripts/regtest_proof.py

lightning-drill:
	$(PY) scripts/lnd_regtest_drill.py

compose-up:
	docker compose -f infra/docker-compose.yml up -d

compose-down:
	docker compose -f infra/docker-compose.yml down
