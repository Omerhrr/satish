"""Fetch permission policy (phase 7: "Permitted page retrieval").

The permission model is DETERMINISTIC backend code, evaluated before any
network I/O and re-evaluated on every redirect hop and on every resolved IP
(DNS-rebinding resistance). Research tools can only reach PUBLIC pages:

- scheme must be http/https
- explicit port must be 80/443; no userinfo in the URL
- hostnames that look local (localhost, *.local, *.internal) are denied
- every resolved IP must be globally routable (loopback, private, link-local,
  reserved, multicast, unspecified ranges are denied)
- content-type must look like a document, size is capped, and HTML/text is
  wrapped as UNTRUSTED downstream (agent_execution_contract #6)
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443}
LOCAL_HOST_SUFFIXES = (".local", ".internal", ".lan", ".home", ".corp")
LOCAL_HOST_NAMES = {"localhost", "localhost.localdomain"}

# Content types we are willing to parse as documents. Everything else
# (binaries, archives, media) is denied rather than downloaded and ignored.
DOCUMENT_CONTENT_PREFIXES = ("text/", "application/json")


@dataclass(slots=True)
class PermissionVerdict:
    allowed: bool
    reason: str


def _deny(reason: str) -> PermissionVerdict:
    return PermissionVerdict(allowed=False, reason=reason)


@dataclass
class FetchPolicy:
    """Static policy knobs; the checks themselves are never negotiable."""

    max_bytes: int = 262_144
    allowed_schemes: set[str] = field(default_factory=lambda: set(ALLOWED_SCHEMES))
    allowed_content_prefixes: tuple[str, ...] = DOCUMENT_CONTENT_PREFIXES

    def check_url(self, url: str) -> PermissionVerdict:
        """Syntactic checks - no network, no DNS. Cheap and always first."""
        try:
            parsed = urlparse(url)
        except ValueError as exc:
            return _deny(f"url could not be parsed: {exc}")
        if parsed.scheme.lower() not in self.allowed_schemes:
            return _deny(f"scheme {parsed.scheme!r} is not permitted (http/https only)")
        host = parsed.hostname
        if not host:
            return _deny("URL has no host")
        if "@" in (parsed.netloc or ""):
            return _deny("userinfo in URL is not permitted")
        host = host.lower()
        if host in LOCAL_HOST_NAMES or any(host.endswith(s) for s in LOCAL_HOST_SUFFIXES):
            return _deny(f"host {host!r} looks local")
        # IP-literal hosts are checked right here; DNS-name hosts get the same
        # treatment in check_resolved() once we know their addresses.
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            addr = None
        if addr is not None and not _ip_is_global(addr):
            return _deny(f"IP-literal host {host!r} is not globally routable")
        port = parsed.port
        if port is not None and port not in ALLOWED_PORTS:
            return _deny(f"port {port} is not permitted (80/443 only)")
        return PermissionVerdict(allowed=True, reason="ok")

    def check_resolved(self, host: str, addresses: list[str]) -> PermissionVerdict:
        """DNS-layer check: EVERY address the host resolves to must be global.

        One private address is enough to deny - this is what makes rebinding
        a non-starter (an attacker cannot smuggle a private target past a
        public first answer).
        """
        if not addresses:
            return _deny(f"host {host!r} did not resolve to any address")
        for raw in addresses:
            try:
                addr = ipaddress.ip_address(raw.strip())
            except ValueError:
                return _deny(f"unparseable resolved address {raw!r}")
            if not _ip_is_global(addr):
                return _deny(f"resolved address {raw} for {host!r} is not globally routable")
        return PermissionVerdict(allowed=True, reason="ok")

    def check_content_type(self, content_type: str) -> PermissionVerdict:
        base = (content_type or "").split(";")[0].strip().lower()
        if not base:
            return _deny("response has no content-type")
        if not base.startswith(self.allowed_content_prefixes):
            return _deny(f"content-type {base!r} is not a permitted document type")
        return PermissionVerdict(allowed=True, reason="ok")


def _ip_is_global(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Conservative global-routability test.

    ``is_global`` covers loopback/private/link-local/reserved on modern
    Python, but we additionally reject anything sharing a version's
    not-fully-approved or special-purpose space (e.g. benchmark 198.18.0.0/15,
    CGNAT 100.64.0.0/10) so the answer errs on the deny side.
    """
    if not addr.is_global:
        return False
    if addr.version == 4:
        if addr in ipaddress.ip_network("198.18.0.0/15"):
            return False
        if addr in ipaddress.ip_network("100.64.0.0/10"):
            return False
    return True


__all__ = [
    "DOCUMENT_CONTENT_PREFIXES",
    "FetchPolicy",
    "PermissionVerdict",
]
