"""Satish AI health check, run on the server:

    docker compose exec api python -m app.diag_ai

Prints, in plain words, each link in the chain a task goes through:
settings -> Redis -> queues -> AI worker heartbeat -> one real AI call.
Never prints secrets.
"""

from __future__ import annotations

import asyncio
import time


def line(ok: bool | None, text: str) -> None:
    mark = "OK  " if ok else ("FAIL" if ok is False else "INFO")
    print(f"[{mark}] {text}", flush=True)


async def main() -> None:
    from xp_core.config import get_settings

    s = get_settings()
    print("Satish AI check\n")

    line(bool(s.deepseek_api_key), f"DeepSeek key set: {'yes' if s.deepseek_api_key else 'NO (tasks run in demo mode)'}")
    line(None, f"model: {s.deepseek_model or 'pinned default'}  base url: {s.deepseek_base_url or 'pinned default'}")
    line(None, f"research search: {s.research_search_mode}  (Brave key set: {'yes' if getattr(s, 'brave_search_api_key', None) else 'no'})")
    line(None, f"task time limit: {s.agent_task_timeout_seconds}s  max steps: {s.agent_max_steps}")
    line(bool(s.redis_url), f"Redis configured: {'yes' if s.redis_url else 'NO (tasks run inside the API, slowly)'}")

    if s.redis_url:
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(s.redis_url)
            t = time.perf_counter()
            await r.ping()
            line(True, f"Redis reachable ({(time.perf_counter() - t) * 1000:.0f} ms)")
            ai_waiting = await r.zcard("satish:ai")
            old_waiting = await r.zcard("arq:queue")
            alive = await r.get("satish:ai:alive")
            beat = await r.get("satish:ai:health-check")
            await r.aclose()
            line(ai_waiting == 0, f"tasks waiting on the Satish AI queue: {ai_waiting}")
            line(None, f"jobs waiting on the background queue: {old_waiting}")
            if alive:
                age = int(time.time()) - int(alive)
                line(age < 180, f"AI worker heartbeat: {age}s ago")
            else:
                line(False, "AI worker heartbeat: none (is the ai-worker service running?)")
            if beat:
                line(None, f"AI worker says: {beat.decode() if isinstance(beat, bytes) else beat}")
        except Exception as exc:  # noqa: BLE001 - this is a diagnostic
            line(False, f"Redis error: {type(exc).__name__}: {exc}")

    print("\nOne real AI call (\"Reply with the word OK\")...", flush=True)
    try:
        from dsh_adapter.client import make_chat_client

        client = make_chat_client(s)
        t = time.perf_counter()
        out = await asyncio.wait_for(
            client.complete([{"role": "user", "content": "Reply with the word OK."}]), timeout=120
        )
        took = time.perf_counter() - t
        content = (out.get("content") or "").strip().replace("\n", " ")[:80]
        line(took < 30, f"AI answered in {took:.1f}s: {content!r} (model {out.get('model')})")
        if out.get("model") == "stub-model":
            line(False, "that was the built-in demo AI, not DeepSeek: set XP_DEEPSEEK_API_KEY")
    except TimeoutError:
        line(False, "AI call took over 120s (DeepSeek too slow or unreachable from this server)")
    except Exception as exc:  # noqa: BLE001
        line(False, f"AI call failed: {type(exc).__name__}: {str(exc)[:300]}")


if __name__ == "__main__":
    asyncio.run(main())
