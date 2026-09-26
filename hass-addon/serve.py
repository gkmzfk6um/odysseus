#!/usr/bin/env python3
"""Start the Odysseus ASGI app on IPv4 and IPv6.

Home Assistant publishes the add-on port on the host and clients may arrive over
either family (browsers prefer IPv6 when the host advertises AAAA records).

A single listening socket is used:

* By default an IPv6 socket with ``IPV6_V6ONLY=0`` (dual-stack), which accepts
  both IPv6 and IPv4-mapped connections. Setting V6ONLY explicitly matters:
  1.0.11 bound ``::`` without clearing it, inherited ``v6only=1`` and silently
  dropped IPv4.
* If the kernel refuses ``v6only=0`` (or has no IPv6), it falls back to an
  IPv4-only socket.

Passing several sockets to uvicorn proved unreliable (only one got served), so
exactly one socket is handed over.
"""

from __future__ import annotations

import os
import socket
import sys

import uvicorn

PORT = int(os.environ.get("APP_PORT", "7000"))
BIND = (os.environ.get("ODYSSEUS_BIND_ADDRESS") or "").strip()
# Where the application source lives. Running `python /serve.py` puts "/" (the
# script dir) on sys.path, so without this `import app` would resolve to the
# /app DIRECTORY and uvicorn would report "Attribute 'app' not found".
APP_DIR = os.environ.get("ODYSSEUS_APP_DIR", "/app")


def _listen(family: int, address, v6only=None) -> socket.socket:
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if family == socket.AF_INET6 and v6only is not None:
        # Let a failure propagate: a socket that could not clear V6ONLY would be
        # IPv6-only, and IPv4 clients would get "connection refused".
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, v6only)
    sock.bind(address)
    sock.listen(128)
    return sock


def build_socket() -> socket.socket:
    if BIND:
        # Explicit override: bind exactly this address. "::" is asked to be
        # dual-stack (v6only=0); anything else is used literally.
        family = socket.AF_INET6 if ":" in BIND else socket.AF_INET
        return _listen(family, (BIND, PORT), v6only=0 if family == socket.AF_INET6 else None)

    try:
        return _listen(socket.AF_INET6, ("::", PORT), v6only=0)
    except OSError as exc:
        print(
            f"[odysseus] dual-stack bind failed ({exc}); falling back to IPv4",
            file=sys.stderr,
        )
        return _listen(socket.AF_INET, ("0.0.0.0", PORT))


def main() -> None:
    if APP_DIR not in sys.path:
        sys.path.insert(0, APP_DIR)
    try:
        os.chdir(APP_DIR)
    except OSError:
        pass

    sock = build_socket()
    family = "dual-stack (IPv4+IPv6)" if sock.family == socket.AF_INET6 else "IPv4"
    print(f"[odysseus] listening on port {PORT} ({family})")
    # No app_dir kwarg: it is absent in some uvicorn versions. sys.path.insert
    # above (plus chdir) is what makes "app:app" resolve to /app/app.py.
    config = uvicorn.Config("app:app", log_level=os.environ.get("LOG_LEVEL", "info"))
    uvicorn.Server(config).run(sockets=[sock])


if __name__ == "__main__":
    main()