"""Home Assistant add-on integration.

This module holds everything Odysseus needs to run as a Home Assistant OS
add-on:

* ingest of the Home Assistant user identity that Supervisor ingress forwards
  in ``X-Remote-User-*`` headers, mapped onto an Odysseus account, and
* validation of Home Assistant username/password credentials through the
  Supervisor ``/auth`` API for the direct-port login screen, and
* URL rewriting so the single-page app, which links assets and the API with
  root-absolute paths, keeps working when served under an ingress prefix.

The module is intentionally free of FastAPI app imports so it can be unit
tested in isolation.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from typing import Any, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from src.owner_identity import RESERVED_AUTH_USERNAMES

logger = logging.getLogger(__name__)

# Supervisor's address on the internal Home Assistant network. Ingress
# requests originate here; anything else must not be trusted to carry ingress
# user headers.
DEFAULT_TRUSTED_IPS = "172.30.32.2"

# Response content types that contain URLs worth prefixing for ingress.
_REWRITABLE_PREFIXES = (
    "text/html",
    "text/css",
    "application/javascript",
    "text/javascript",
)

_INGRESS_PATH_RE = re.compile(r"^(/api/hassio_ingress/[^/]+)")


# ---------------------------------------------------------------------------
# Environment / option helpers
# ---------------------------------------------------------------------------

def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() == "true"


def ha_ingress_auth_enabled() -> bool:
    """True when ingress user headers should be trusted and auto-signed-in."""
    return _env_flag("ODYSSEUS_HA_INGRESS_AUTH", False)


def ha_password_auth_enabled() -> bool:
    """True when Home Assistant credentials are accepted on the login screen."""
    return _env_flag("ODYSSEUS_HA_AUTH_API", False)


def ha_bootstrap_admin_enabled() -> bool:
    """True when the first Home Assistant user becomes an administrator."""
    return _env_flag("ODYSSEUS_HA_BOOTSTRAP_ADMIN", True)


def ha_admin_users() -> set[str]:
    raw = os.getenv("ODYSSEUS_HA_ADMIN_USERS", "") or ""
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def ha_trusted_ips() -> set[str]:
    raw = os.getenv("ODYSSEUS_HA_TRUSTED_IPS", DEFAULT_TRUSTED_IPS) or ""
    return {part.strip() for part in raw.split(",") if part.strip()}


# ---------------------------------------------------------------------------
# Ingress identity
# ---------------------------------------------------------------------------

def get_ha_identity(request) -> Optional[dict[str, str]]:
    """Extract the Home Assistant user identity from ingress headers.

    Supervisor forwards ``X-Remote-User-Id``, ``X-Remote-User-Name`` (the login
    username) and ``X-Remote-User-Display-Name``. Returns ``None`` when neither
    an id nor a username is present, i.e. the request did not come through
    authenticated ingress.
    """
    headers = request.headers
    user_id = (headers.get("x-remote-user-id") or "").strip()
    username = (headers.get("x-remote-user-name") or "").strip().lower()
    display_name = (headers.get("x-remote-user-display-name") or "").strip()
    if not user_id and not username:
        return None
    return {"id": user_id, "username": username, "display_name": display_name}


def is_trusted_ingress_client(request) -> bool:
    client = getattr(request, "client", None)
    host = (client.host if client else "") or ""
    return host in ha_trusted_ips()


def is_ha_ingress_request(request) -> bool:
    """True when this request is an authenticated ingress request we trust."""
    if not ha_ingress_auth_enabled():
        return False
    if not is_trusted_ingress_client(request):
        return False
    return get_ha_identity(request) is not None


def is_ingress_proxied_request(request) -> bool:
    """True when a trusted Supervisor ingress is framing this request.

    Used to relax anti-framing headers: the Home Assistant frontend embeds the
    add-on in an iframe, and a blanket ``X-Frame-Options: DENY`` would block it.
    """
    return is_trusted_ingress_client(request) and ingress_base(request) != ""


def target_username(identity: dict[str, str]) -> str:
    """Derive a stable Odysseus username from a Home Assistant identity."""
    username = (identity.get("username") or "").strip().lower()
    if username and username not in RESERVED_AUTH_USERNAMES:
        return username
    user_id = (identity.get("id") or "").strip().lower()
    if user_id:
        # Keep the derived name stable and readable; the id suffix avoids
        # collisions between users that have no username (e.g. the owner).
        return f"ha_{user_id[:8]}"
    return "ha_user"


def _should_be_admin(auth_manager, username: str) -> bool:
    if username in ha_admin_users():
        return True
    if ha_bootstrap_admin_enabled():
        users = getattr(auth_manager, "users", None) or {}
        if not users:
            return True
    return False


def provision_ha_user(auth_manager, identity: dict[str, str]) -> Optional[str]:
    """Ensure an Odysseus account exists for a Home Assistant user.

    The account has no usable password (a random one is stored) because the
    Home Assistant user never logs in locally. Admin status comes from
    ``ha_admin_users`` or, for the very first user, ``ha_bootstrap_admin``.
    """
    username = target_username(identity)
    users = getattr(auth_manager, "users", None) or {}
    if username in users:
        return username
    is_admin = _should_be_admin(auth_manager, username)
    try:
        created = auth_manager.create_user(
            username, secrets.token_urlsafe(24), is_admin=is_admin
        )
    except Exception:
        logger.warning("Failed to provision HA user '%s'", username, exc_info=True)
        return username if username in (getattr(auth_manager, "users", None) or {}) else None
    if created:
        logger.info(
            "Provisioned Odysseus account '%s' for Home Assistant user (admin=%s)",
            username, is_admin,
        )
    return username


async def verify_ha_credentials(username: str, password: str) -> bool:
    """Validate a username/password against Home Assistant via Supervisor.

    Requires ``auth_api``/``hassio_api`` in the add-on configuration and the
    automatically injected ``SUPERVISOR_TOKEN``. Returns False on any failure so
    callers can fall back to local authentication.
    """
    if not ha_password_auth_enabled():
        return False
    token = os.getenv("SUPERVISOR_TOKEN")
    if not token or not username or not password:
        return False
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "http://supervisor/auth",
                headers={"X-Supervisor-Token": token},
                json={"username": username, "password": password},
            )
        return resp.status_code == 200
    except Exception:
        logger.debug("Home Assistant credential check failed", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Ingress URL rewriting
# ---------------------------------------------------------------------------

def ingress_base(request) -> str:
    """Return the ingress URL prefix for this request, or "" outside ingress.

    Supervisor sends ``X-Ingress-Path`` (e.g. ``/api/hassio_ingress/<token>``).
    Newer/older combinations may omit it, so fall back to the ``Referer`` the
    browser sends when embedding the app in the Home Assistant iframe.
    """
    raw = (request.headers.get("x-ingress-path") or "").strip()
    if raw.startswith("/"):
        return raw.rstrip("/")
    referer = request.headers.get("referer") or ""
    if referer:
        try:
            from urllib.parse import urlsplit

            path = urlsplit(referer).path or ""
        except Exception:
            path = ""
        match = _INGRESS_PATH_RE.match(path)
        if match:
            return match.group(1).rstrip("/")
    return ""


_INGRESS_SHIM = r"""(function(){
  var BASE = "__INGRESS_BASE__";
  if (!BASE || window.__odysseusIngressInstalled) { return; }
  window.__odysseusIngressInstalled = true;
  window.__ODYSSEUS_INGRESS_BASE__ = BASE;
  function fix(u){
    try {
      if (typeof u !== "string" || u.length === 0) { return u; }
      if (u.charAt(0) !== "/" || u.charAt(1) === "/") { return u; }
      if (u === BASE || u.indexOf(BASE + "/") === 0) { return u; }
      return BASE + u;
    } catch (e) { return u; }
  }
  var _fetch = window.fetch;
  if (_fetch) {
    window.fetch = function(input, init){
      try {
        if (typeof input === "string") { input = fix(input); }
        else if (input && typeof input === "object" && input.url) {
          input = new Request(fix(input.url), input);
        }
      } catch (e) {}
      return _fetch.call(this, input, init);
    };
  }
  if (window.XMLHttpRequest && XMLHttpRequest.prototype && XMLHttpRequest.prototype.open) {
    var _open = XMLHttpRequest.prototype.open;
    XMLHttpRequest.prototype.open = function(method, url){
      try { arguments[1] = fix(url); } catch (e) {}
      return _open.apply(this, arguments);
    };
  }
  if (window.WebSocket) {
    var _WS = window.WebSocket;
    var WS = function(url, protocols){
      return protocols === undefined ? new _WS(fix(url)) : new _WS(fix(url), protocols);
    };
    WS.prototype = _WS.prototype;
    WS.CONNECTING = _WS.CONNECTING; WS.OPEN = _WS.OPEN;
    WS.CLOSING = _WS.CLOSING; WS.CLOSED = _WS.CLOSED;
    window.WebSocket = WS;
  }
  if (window.EventSource) {
    var _ES = window.EventSource;
    var ES = function(url, opts){
      return opts === undefined ? new _ES(fix(url)) : new _ES(fix(url), opts);
    };
    ES.prototype = _ES.prototype;
    window.EventSource = ES;
  }
  if (window.history && window.history.pushState) {
    var _ps = window.history.pushState, _rs = window.history.replaceState;
    window.history.pushState = function(state, title, url){ return _ps.call(this, state, title, fix(url)); };
    window.history.replaceState = function(state, title, url){ return _rs.call(this, state, title, fix(url)); };
  }
  document.addEventListener("click", function(ev){
    try {
      var el = ev.target;
      while (el && el.tagName !== "A") { el = el.parentElement; }
      if (!el) { return; }
      var href = el.getAttribute("href");
      if (href && href.charAt(0) === "/" && href.charAt(1) !== "/" && href.indexOf(BASE + "/") !== 0) {
        el.setAttribute("href", BASE + href);
      }
    } catch (e) {}
  }, true);
})();
"""


_ROOT_PATH_RE = re.compile(r"([\"'`(])(/(?:api|static)/)")


def _prefix_root_paths(text: str, base: str) -> str:
    """Prefix root-absolute application URLs with the ingress base.

    Only URLs that immediately follow a quote, backtick or ``url(`` are
    touched, so prose and regexes containing ``/api/`` are left alone. A single
    regex pass is used so an inserted base (which itself contains ``/api/``) can
    never be prefixed a second time.
    """
    return _ROOT_PATH_RE.sub(lambda m: m.group(1) + base + m.group(2), text)


def rewrite_ingress_body(body: bytes, content_type: str, base: str, nonce: str = "") -> bytes:
    """Rewrite a text response so it works under an ingress prefix."""
    if not base or not body:
        return body
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return body
    text = _prefix_root_paths(text, base)
    if content_type.startswith("text/html"):
        shim = (
            _INGRESS_SHIM.replace("__INGRESS_BASE__", base)
            .replace("__CSP_NONCE__", nonce)
        )
        tag = f'<script nonce="{nonce}">{shim}</script>'
        lowered = text.lower()
        idx = lowered.find("</head>")
        if idx != -1:
            text = text[:idx] + tag + text[idx:]
        else:
            text = tag + text
    return text.encode("utf-8")


def _rewritable(content_type: str) -> bool:
    return any(content_type.startswith(p) for p in _REWRITABLE_PREFIXES)


class IngressPathMiddleware(BaseHTTPMiddleware):
    """Make root-absolute URLs work when the app is served under ingress.

    Registered inside the gzip middleware so responses are still uncompressed,
    and inside the security-headers middleware so the CSP nonce is available for
    the injected runtime shim.
    """

    async def dispatch(self, request, call_next) -> Response:
        base = ingress_base(request)
        response = await call_next(request)
        if not base or response.status_code in (204, 304):
            return response
        content_type = response.headers.get("content-type", "")
        if not content_type or not _rewritable(content_type):
            return response
        chunks = [chunk async for chunk in response.body_iterator]
        body = b"".join(chunks)
        if not body:
            return response
        nonce = getattr(request.state, "csp_nonce", "")
        new_body = rewrite_ingress_body(body, content_type, base, nonce)
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=new_body,
            status_code=response.status_code,
            headers=headers,
        )


def ha_config_summary() -> dict[str, Any]:
    """Small summary for logging at startup."""
    return {
        "ingress_auth": ha_ingress_auth_enabled(),
        "password_auth": ha_password_auth_enabled(),
        "bootstrap_admin": ha_bootstrap_admin_enabled(),
        "admin_users": sorted(ha_admin_users()),
        "trusted_ips": sorted(ha_trusted_ips()),
    }