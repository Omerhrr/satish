"""zmq loopback probe (phase-4 drill diagnostic).

Proves (or disproves) that PUB->SUB over 127.0.0.1 works in the current
environment. lnd's default chain-notify path is zmq; if THIS probe drops
messages, no lnd/bitcoind zmq configuration can work in the sandbox - that
is an environment defect, not an lnd API defect.

Usage: .venv/bin/python scripts/zmq_probe.py
Exit:  0 if a published message round-trips, 1 otherwise.

Recorded result in this sandbox (2026-10-15): FAIL - even a pure Python
PUB->SUB over loopback drops messages; documented in
the lnd provider notes in git history (Satish now uses Breez Spark, docs/wallet.md) ("The honest sandbox limitation").
"""

from __future__ import annotations

import sys

import zmq


def main() -> int:
    ctx = zmq.Context()
    try:
        pub = ctx.socket(zmq.PUB)
        sub = ctx.socket(zmq.SUB)
        port = pub.bind_to_random_port("tcp://127.0.0.1")
        sub.connect(f"tcp://127.0.0.1:{port}")
        sub.setsockopt(zmq.SUBSCRIBE, b"probe")
        # SUB sockets need a moment to register the subscription.
        import time

        time.sleep(0.5)
        for attempt in range(10):
            pub.send_multipart([b"probe", f"msg-{attempt}".encode()])
            if sub.poll(timeout=500):
                _topic, payload = sub.recv_multipart()
                print(f"PASS: round-trip on attempt {attempt}: {payload.decode()}")
                return 0
        print("FAIL: 10 published messages over 127.0.0.1, none delivered")
        print("loopback zmq is broken in this environment - lnd's zmq chain")
        print("notifications cannot work here (see the lnd provider notes in git history (Satish now uses Breez Spark, docs/wallet.md))")
        return 1
    finally:
        ctx.term()


if __name__ == "__main__":
    raise SystemExit(main())
