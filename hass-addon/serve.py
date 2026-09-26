#!/usr/bin/env python3
"""Start the Odysseus ASGI app on IPv4 and, when possible, IPv6.

Home Assistant publishes the add-on port on the host and clients may arrive over
either family (browsers prefer IPv6 when the host advertises AAAA records).
Binding a single ``::`` socket is not portable: with ``net.ipv6.bindv6only=1``
(the default on some systems/containers) it accepts IPv6 only and silently drops
IPv4. So we create one listening socket per family and hand both to uvicorn.
IPv4 is always bound; the IPv6 socket is skipped when it cannot be created.
"""

from __future__ import annotations

import os
import socket
import sys

import uvicorn

PORT = int(os.environ.get("APP_PORT", "7000"))
BIND = (os.environ.get("ODYSSEUS_BIND_ADDRESS") or "").strip()
# Where the application source lives. Running this script as `python /serve.py`
# puts "/" (the script's directory) on sys.path, not the app dir, so `import app`
# would otherwise resolve to the /app DIRECTORY and uvicorn would report
# "Attribute 'app' not found in module 'app'".
APP_DIR = os.environ.get("ODYSSEUS_APP_DIR", "/app")


def _listen(family: int, address, v6only=None) -> socket.socket:
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if family == socket.AF_INET6 and v6only is not None:
        try:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, v6only)
        except OSError:
            pass
    sock.bind(address)
    sock.listen(128)
    return sock


def build_sockets() -> list[socket.socket]:
    if BIND:
        # Explicit override: bind exactly this address. "::" is asked to be
        # dual-stack (v6only=0); anything else is used literally.
        family = socket.AF_INET6 if ":" in BIND else socket.AF_INET
        return [_listen(family, (BIND, PORT), v6only=0 if family == socket.AF_INET6 else None)]

    sockets = [_listen(socket.AF_INET, ("0.0.0.0", PORT))]
    try:
        # v6only=1 so the IPv6 socket does not also try to claim IPv4 (which
        # would collide with the socket above).
        sockets.append(_listen(socket.AF_INET6, ("::", PORT), v6only=1))
    except OSError as exc:
        print(f"[odysseus] IPv6 listener skipped: {exc}", file=sys.stderr)
    return sockets


def main() -> None:
    if APP_DIR not in sys.path:
        sys.path.insert(0, APP_DIR)
    try:
        os.chdir(APP_DIR)
    except OSError:
        pass

    sockets = build_sockets()
    families = ", ".join("IPv6" if s.family == socket.AF_INET6 else "IPv4" for s in sockets)
    print(f"[odysseus] listening on port {PORT} ({families})")
    # No app_dir kwarg: it is absent in some uvicorn versions. sys.path.insert
    # above (plus chdir) is what makes "app:app" resolve to /app/app.py.
    config = uvicorn.Config("app:app", log_level=os.environ.get("LOG_LEVEL", "info"))
    uvicorn.Server(config).run(sockets=sockets)


if __name__ == "__main__":
    main()