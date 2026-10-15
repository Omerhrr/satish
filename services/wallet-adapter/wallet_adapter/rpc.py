"""Minimal async bitcoind JSON-RPC client (phase-3, decision D10).

Scope: exactly the calls the BDK-backed provider needs — fee estimation,
raw-transaction broadcast + mempool acceptance probing, and chain/wallet
state queries. No wallet-file management, no admin surface; the node is a
chain source, not a custody boundary (keys live in the BDK layer).

Failure taxonomy (acceptance: "Failed and uncertain broadcasts are
represented accurately"):
- ``RpcRejected``      — bitcoind answered with a definite rejection.
- ``RpcUnavailable``   — the node could not be reached at all; any broadcast
  attempted during such an outage is UNCERTAIN (it may or may not have
  arrived before the connection failed).
"""

from __future__ import annotations

import httpx


class RpcError(RuntimeError):
    """Base class for bitcoind RPC failures."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class RpcRejected(RpcError):
    """bitcoind explicitly rejected the request (definite outcome)."""


class RpcUnavailable(RpcError):
    """Node unreachable / timed out (outcome of any in-flight send unknown)."""


class BitcoindRpc:
    """Async JSON-RPC 1.0 client for a single bitcoind instance."""

    def __init__(
        self,
        *,
        url: str,
        rpc_user: str,
        rpc_password: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._url = url
        self._auth = (rpc_user, rpc_password)
        self._timeout = timeout_seconds

    async def call(self, method: str, *params: object) -> object:
        payload = {
            "jsonrpc": "1.0",
            "id": "xp-wallet-adapter",
            "method": method,
            "params": list(params),
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._url, json=payload, auth=self._auth)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.TransportError) as exc:
            raise RpcUnavailable(f"bitcoind unreachable ({method}): {exc}") from exc

        if resp.status_code in (401, 403):
            raise RpcRejected("bitcoind RPC authentication failed", code=resp.status_code)
        try:
            body = resp.json()
        except ValueError as exc:
            raise RpcRejected(f"bitcoind returned non-JSON (HTTP {resp.status_code})") from exc

        if body.get("error") is not None:
            err = body["error"]
            raise RpcRejected(
                str(err.get("message", err)), code=err.get("code") if isinstance(err, dict) else None
            )
        return body.get("result")

    # -- sugar ---------------------------------------------------------------

    async def estimatesmartfee_sat_vb(self, conf_target: int = 6) -> tuple[int, bool]:
        """Return (sat/vB, is_fallback). BDK-compatible integer sat/vB."""
        try:
            result = await self.call("estimatesmartfee", conf_target)
        except RpcUnavailable:
            return (0, True)  # caller decides the fallback policy
        except RpcRejected:
            return (0, True)
        feerate_btc_kb = (result or {}).get("feerate")  # type: ignore[union-attr]
        if not feerate_btc_kb or feerate_btc_kb <= 0:
            return (0, True)
        # BTC/kvB -> sat/vB: * 1e8 / 1000
        return (max(1, round(feerate_btc_kb * 1e8 / 1000)), False)

    async def sendrawtransaction(self, raw_hex: str) -> str:
        """Broadcast. Raises RpcRejected (definite) or RpcUnavailable (uncertain)."""
        result = await self.call("sendrawtransaction", raw_hex)
        return str(result)

    async def testmempoolaccept(self, raw_hex: str) -> dict | None:
        result = await self.call("testmempoolaccept", [raw_hex])
        entries = result if isinstance(result, list) else []
        return entries[0] if entries else None

    async def best_block_height(self) -> int:
        result = await self.call("getblockcount")
        return int(result)  # type: ignore[arg-type]

    async def health(self) -> dict:
        info = await self.call("getblockchaininfo")
        data = info if isinstance(info, dict) else {}
        return {
            "reachable": True,
            "chain": data.get("chain"),
            "blocks": data.get("blocks"),
            "headers": data.get("headers"),
        }
