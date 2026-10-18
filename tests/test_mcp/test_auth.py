"""Unit tests for the SSE auth provider factory."""

from __future__ import annotations

from types import SimpleNamespace

from src.mcp import _shared


def test_build_sse_auth_returns_none_when_disabled(monkeypatch):
    monkeypatch.setenv("KB_MCP_REQUIRE_AUTH", "false")
    monkeypatch.setattr(
        _shared, "settings",
        SimpleNamespace(api=SimpleNamespace(keys_list=["secret-key"])),
    )
    assert _shared.build_sse_auth() is None


def test_build_sse_auth_uses_registry_even_without_env_keys(monkeypatch):
    # R-P6: DB-only key deployments must still get auth on HTTP transports.
    monkeypatch.setenv("KB_MCP_REQUIRE_AUTH", "true")
    monkeypatch.setattr(
        _shared, "settings",
        SimpleNamespace(api=SimpleNamespace(keys_list=[])),
    )
    assert isinstance(_shared.build_sse_auth(), _shared.RegistryTokenVerifier)


def test_startup_check_does_not_exit_without_env_keys(monkeypatch):
    monkeypatch.setenv("KB_MCP_REQUIRE_AUTH", "true")
    monkeypatch.setattr(
        _shared, "settings",
        SimpleNamespace(api=SimpleNamespace(keys_list=[])),
    )
    _shared.assert_api_key_env_set()  # must not raise SystemExit


def test_build_sse_auth_builds_verifier_with_keys(monkeypatch):
    monkeypatch.setenv("KB_MCP_REQUIRE_AUTH", "true")
    monkeypatch.setattr(
        _shared, "settings",
        SimpleNamespace(api=SimpleNamespace(keys_list=["secret-key", "k2"])),
    )
    auth = _shared.build_sse_auth()
    # Bearer tokens are verified against the API-key registry (DB keys +
    # legacy env keys), not a static token table.
    assert isinstance(auth, _shared.RegistryTokenVerifier)


async def test_registry_verifier_accepts_legacy_env_key(monkeypatch):
    """An env API_KEYS key still authenticates (registry env fallback) and is
    still full-rights in tenant ``default`` — every action, every graph."""
    from src.tenancy import api_keys
    from src.tenancy.authz import ALL_ACTIONS

    async def _no_row(_h):
        return None
    monkeypatch.setattr(
        api_keys, "settings",
        SimpleNamespace(api=SimpleNamespace(keys_list=["secret-key"])),
    )
    monkeypatch.setattr(
        _shared, "get_api_key_store", lambda: api_keys.ApiKeyStore(loader=_no_row),
    )
    tok = await _shared.RegistryTokenVerifier().verify_token("secret-key")
    assert tok is not None
    assert tok.client_id == "legacy-env"
    assert tok.scopes == sorted(ALL_ACTIONS)
    assert tok.claims == {
        "owner": "legacy-env",
        "tenant_id": "default",
        "scopes": sorted(ALL_ACTIONS),
        "graph_ids": None,
    }
    assert await _shared.RegistryTokenVerifier().verify_token("wrong") is None


def test_both_servers_wire_sse_auth(monkeypatch):
    """Guard: `auth=build_sse_auth()` must stay wired into BOTH FastMCP
    server constructors. Reload the server modules with auth required +
    a key configured, and assert each module's `mcp.auth` is set."""
    import importlib

    monkeypatch.setenv("KB_MCP_REQUIRE_AUTH", "true")
    # build_sse_auth reads _shared.settings.api.keys_list — patch it so a
    # key is present regardless of the ambient environment.
    monkeypatch.setattr(
        _shared, "settings",
        SimpleNamespace(api=SimpleNamespace(keys_list=["wiring-test-key"])),
    )

    import src.mcp.search_server as search_server
    import src.mcp.tools_server as tools_server

    tools_server = importlib.reload(tools_server)
    search_server = importlib.reload(search_server)

    assert isinstance(tools_server.mcp.auth, _shared.RegistryTokenVerifier)
    assert isinstance(search_server.mcp.auth, _shared.RegistryTokenVerifier)
