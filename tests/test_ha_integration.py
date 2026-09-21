"""Unit tests for the Home Assistant add-on integration bridge.

These cover the pieces that turn Home Assistant into an auth provider:
identity extraction from ingress headers, account provisioning/admin rules,
credential validation gating, and ingress URL rewriting.
"""

import json
from types import SimpleNamespace

import pytest
from starlette.datastructures import Headers

from core.auth import AuthManager
from src import ha_integration as ha


class FakeRequest:
    def __init__(self, headers=None, host="172.30.32.2"):
        self.headers = Headers(headers or {})
        self.client = SimpleNamespace(host=host)
        self.state = SimpleNamespace()


@pytest.fixture
def auth_manager(tmp_path):
    return AuthManager(auth_path=str(tmp_path / "auth.json"))


@pytest.fixture(autouse=True)
def _clear_ha_env(monkeypatch):
    for key in (
        "ODYSSEUS_HA_INGRESS_AUTH",
        "ODYSSEUS_HA_AUTH_API",
        "ODYSSEUS_HA_BOOTSTRAP_ADMIN",
        "ODYSSEUS_HA_ADMIN_USERS",
        "ODYSSEUS_HA_TRUSTED_IPS",
        "SUPERVISOR_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Identity + trust
# ---------------------------------------------------------------------------

def test_target_username_prefers_ha_username():
    assert ha.target_username({"id": "abc", "username": "alice"}) == "alice"


def test_target_username_falls_back_for_reserved_and_missing():
    assert ha.target_username({"id": "abcdef1234", "username": "api"}) == "ha_abcdef12"
    assert ha.target_username({"id": "abcdef1234", "username": ""}) == "ha_abcdef12"
    assert ha.target_username({"id": "", "username": ""}) == "ha_user"


def test_get_ha_identity_reads_headers():
    request = FakeRequest({
        "X-Remote-User-Id": "uid-1",
        "X-Remote-User-Name": "Alice",
        "X-Remote-User-Display-Name": "Alice Smith",
    })
    assert ha.get_ha_identity(request) == {
        "id": "uid-1",
        "username": "alice",
        "display_name": "Alice Smith",
    }


def test_get_ha_identity_without_headers_is_none():
    assert ha.get_ha_identity(FakeRequest()) is None


def test_is_ha_ingress_request_requires_flag_trust_and_identity(monkeypatch):
    request = FakeRequest({"X-Remote-User-Name": "alice"})
    assert ha.is_ha_ingress_request(request) is False  # disabled

    monkeypatch.setenv("ODYSSEUS_HA_INGRESS_AUTH", "true")
    assert ha.is_ha_ingress_request(request) is True

    untrusted = FakeRequest({"X-Remote-User-Name": "alice"}, host="10.0.0.5")
    assert ha.is_ha_ingress_request(untrusted) is False

    no_identity = FakeRequest()
    assert ha.is_ha_ingress_request(no_identity) is False


# ---------------------------------------------------------------------------
# Provisioning
# ---------------------------------------------------------------------------

def test_provision_first_user_becomes_admin(auth_manager):
    username = ha.provision_ha_user(auth_manager, {"id": "u1", "username": "alice"})
    assert username == "alice"
    assert auth_manager.is_admin("alice") is True
    assert auth_manager.is_configured is True


def test_provision_second_user_is_not_admin(auth_manager):
    ha.provision_ha_user(auth_manager, {"id": "u1", "username": "alice"})
    ha.provision_ha_user(auth_manager, {"id": "u2", "username": "bob"})
    assert auth_manager.is_admin("alice") is True
    assert auth_manager.is_admin("bob") is False


def test_provision_honors_admin_users_option(auth_manager, monkeypatch):
    monkeypatch.setenv("ODYSSEUS_HA_ADMIN_USERS", "alice,carol")
    ha.provision_ha_user(auth_manager, {"id": "u1", "username": "alice"})
    ha.provision_ha_user(auth_manager, {"id": "u2", "username": "bob"})
    ha.provision_ha_user(auth_manager, {"id": "u3", "username": "carol"})
    assert auth_manager.is_admin("alice") is True
    assert auth_manager.is_admin("carol") is True
    assert auth_manager.is_admin("bob") is False


def test_provision_is_idempotent(auth_manager):
    first = ha.provision_ha_user(auth_manager, {"id": "u1", "username": "alice"})
    second = ha.provision_ha_user(auth_manager, {"id": "u1", "username": "alice"})
    assert first == second == "alice"
    assert len(auth_manager.users) == 1


def test_bootstrap_can_be_disabled(auth_manager, monkeypatch):
    monkeypatch.setenv("ODYSSEUS_HA_BOOTSTRAP_ADMIN", "false")
    ha.provision_ha_user(auth_manager, {"id": "u1", "username": "alice"})
    assert auth_manager.is_admin("alice") is False


# ---------------------------------------------------------------------------
# Credential validation gate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_ha_credentials_disabled_by_default():
    assert await ha.verify_ha_credentials("alice", "secret") is False


@pytest.mark.asyncio
async def test_verify_ha_credentials_without_supervisor_token(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_HA_AUTH_API", "true")
    assert await ha.verify_ha_credentials("alice", "secret") is False


# ---------------------------------------------------------------------------
# Ingress base detection
# ---------------------------------------------------------------------------

def test_ingress_base_from_header():
    request = FakeRequest({"X-Ingress-Path": "/api/hassio_ingress/tok123/"})
    assert ha.ingress_base(request) == "/api/hassio_ingress/tok123"


def test_ingress_base_from_referer_fallback():
    request = FakeRequest({
        "Referer": "https://ha.local/api/hassio_ingress/tok123/static/app.js",
    })
    assert ha.ingress_base(request) == "/api/hassio_ingress/tok123"


def test_ingress_base_empty_outside_ingress():
    assert ha.ingress_base(FakeRequest()) == ""


def test_is_ingress_proxied_request_requires_trust_and_prefix():
    trusted = FakeRequest({"X-Ingress-Path": "/api/hassio_ingress/tok"})
    assert ha.is_ingress_proxied_request(trusted) is True
    assert ha.is_ingress_proxied_request(
        FakeRequest({"X-Ingress-Path": "/api/hassio_ingress/tok"}, host="10.0.0.5")
    ) is False
    assert ha.is_ingress_proxied_request(FakeRequest()) is False


# ---------------------------------------------------------------------------
# Body rewriting
# ---------------------------------------------------------------------------

def test_rewrite_html_prefixes_urls_and_injects_nonce_shim():
    html = (
        '<html><head>'
        '<link rel="stylesheet" href="/static/style.css">'
        '</head><body><script>fetch("/api/version")</script></body></html>'
    ).encode("utf-8")
    out = ha.rewrite_ingress_body(html, "text/html", "/api/hassio_ingress/tok", "nonce1")
    text = out.decode("utf-8")
    assert 'href="/api/hassio_ingress/tok/static/style.css"' in text
    assert 'fetch("/api/hassio_ingress/tok/api/version")' in text
    assert '<script nonce="nonce1">' in text
    assert "__odysseusIngressInstalled" in text
    assert text.count("/api/hassio_ingress/tok/api/version") == 1  # no double prefix


def test_rewrite_js_prefixes_quoted_paths():
    js = "const a = '/api/x'; const b = `/static/y`;".encode("utf-8")
    text = ha.rewrite_ingress_body(js, "application/javascript", "/base").decode()
    assert "'/base/api/x'" in text
    assert "`/base/static/y`" in text


def test_rewrite_js_prefixes_origin_interpolated_urls():
    js = (
        "fetch(`${API_BASE}/api/sessions`);"
        "window.open(`${API_BASE}/api/research/report/1`);"
        "new URL(`${window.location.origin}/api/history/1`);"
    ).encode("utf-8")
    text = ha.rewrite_ingress_body(js, "application/javascript", "/base").decode()
    assert "${API_BASE}/base/api/sessions" in text
    assert "${API_BASE}/base/api/research/report/1" in text
    assert "${window.location.origin}/base/api/history/1" in text
    assert text.count("/base/base/") == 0


def test_shim_covers_absolute_origin_urls_and_window_open():
    out = ha.rewrite_ingress_body(b"<head></head>", "text/html", "/base", "n").decode()
    assert "window.location.origin" in out
    assert "function fixArg" in out
    assert "window.open" in out


def test_rewrite_css_prefixes_url_function():
    css = b"@font-face{src:url(/static/fonts/x.woff2)}"
    text = ha.rewrite_ingress_body(css, "text/css", "/base").decode()
    assert "url(/base/static/fonts/x.woff2)" in text


def test_rewrite_leaves_other_types_untouched():
    body = b"binary\xffdata"
    assert ha.rewrite_ingress_body(body, "image/png", "/base") == body


def test_rewrite_empty_base_is_noop():
    body = b'fetch("/api/version")'
    assert ha.rewrite_ingress_body(body, "text/html", "") == body


def test_ha_config_summary_shape(monkeypatch):
    monkeypatch.setenv("ODYSSEUS_HA_INGRESS_AUTH", "true")
    monkeypatch.setenv("ODYSSEUS_HA_ADMIN_USERS", "alice, bob")
    summary = ha.ha_config_summary()
    assert summary["ingress_auth"] is True
    assert summary["admin_users"] == ["alice", "bob"]