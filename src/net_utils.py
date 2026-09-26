"""Client-address helpers.

When the ASGI server listens on a dual-stack IPv6 socket, IPv4 peers are reported
as IPv4-mapped IPv6 addresses (``::ffff:172.30.32.2``, ``::ffff:127.0.0.1``).
Security checks that compare ``request.client.host`` against plain IPv4 literals
therefore stop matching the moment the server switches to a dual-stack socket —
the Home Assistant ingress trust check and the loopback bypass are the important
ones. Normalize before comparing.
"""

from __future__ import annotations

from typing import Optional


def normalize_client_ip(host: Optional[str]) -> str:
    """Return ``host`` with an IPv4-mapped IPv6 prefix collapsed to IPv4."""
    if not host:
        return ""
    host = host.strip()
    if host.lower().startswith("::ffff:"):
        return host[7:]
    return host


def get_client_ip(request) -> str:
    """Normalized client address for a Starlette/FastAPI request."""
    client = getattr(request, "client", None)
    return normalize_client_ip(client.host if client else None)