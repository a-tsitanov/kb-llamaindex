import pytest
from fastmcp.exceptions import ToolError

import src.mcp._shared as sh
from src.config import settings
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.authz import ALL_ACTIONS, Action
from src.tenancy.context import default_graph_context, new_graph_context


class _Reg:
    async def get(self, gid):
        return default_graph_context() if gid == "default" else new_graph_context(gid)


class _OneKey:
    def __init__(self, rec):
        self.rec = rec

    async def lookup(self, k):
        return self.rec if k == "good" else None


async def mint_token(monkeypatch, rec: ApiKeyRecord):
    """A token exactly as ``RegistryTokenVerifier`` mints one.

    Never hand-built: the claims contract then lives in the verifier alone,
    and a test that drifts from it fails here instead of passing against an
    imitation.  Shared with ``tests/test_mcp/test_tool_authz.py``."""
    monkeypatch.setattr(sh, "get_api_key_store", lambda: _OneKey(rec))
    return await sh.RegistryTokenVerifier().verify_token("good")


# Spec 2026-10-18 §3.2: the token authenticates AND carries the key's rights;
# the graph is the X-Graph header if present, else KB_MCP_GRAPH (default
# "default") — the same for HTTP with or without auth and for stdio.  The
# decision is taken on every tool call, never once at the handshake.


async def test_verifier_claims_carry_the_key_rights(monkeypatch):
    """Claims are the record flattened to JSON primitives (fastmcp may
    serialise or log them); `_record_from_token` reads them back per call."""
    tok = await mint_token(monkeypatch, ApiKeyRecord.full("acme"))
    assert tok.claims == {
        "owner": "acme",
        "tenant_id": "default",
        "scopes": sorted(ALL_ACTIONS),
        "graph_ids": None,
    }
    assert tok.scopes == sorted(ALL_ACTIONS)
    assert tok.client_id == "acme"
    assert await sh.RegistryTokenVerifier().verify_token("bad") is None


async def test_record_from_token_round_trips_a_narrowed_key(monkeypatch):
    rec = ApiKeyRecord(
        owner="a", tenant_id="t1", scopes=frozenset({"read"}), graph_ids=("g1", "g2"),
    )
    tok = await mint_token(monkeypatch, rec)
    assert tok.claims["graph_ids"] == ["g1", "g2"]  # JSON primitive, not a tuple
    assert sh._record_from_token(tok) == rec


async def test_current_graph_http_uses_header(monkeypatch):
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Reg())
    monkeypatch.setattr(sh, "get_http_headers", lambda **kw: {"x-graph": "acme_hr"})
    assert (await sh.current_graph()).id == "acme_hr"


async def test_current_graph_foreign_graph_is_tool_error(monkeypatch):
    """A graph of another tenant must answer exactly as one that does not
    exist — same string, naming no slug — or the error is an oracle."""
    monkeypatch.setattr(settings.authz, "mode", "enforce")
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Reg())
    monkeypatch.setattr(sh, "get_http_headers", lambda **kw: {"x-graph": "other"})
    tok = await mint_token(monkeypatch, ApiKeyRecord.full("acme", tenant_id="t2"))
    monkeypatch.setattr(sh, "get_access_token", lambda: tok)
    with pytest.raises(ToolError) as foreign:
        await sh.current_graph()

    from src.tenancy.registry import GraphNotFound

    class _Missing:
        async def get(self, gid):
            raise GraphNotFound(gid)
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Missing())
    with pytest.raises(ToolError) as ghost:
        await sh.current_graph()
    assert str(foreign.value) == str(ghost.value) == sh.GRAPH_NOT_FOUND_DETAIL
    assert "other" not in str(foreign.value)


async def test_current_graph_http_without_header_uses_configured_graph(monkeypatch):
    monkeypatch.delenv("KB_MCP_GRAPH", raising=False)
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Reg())
    monkeypatch.setattr(sh, "get_http_headers", lambda **kw: {})
    assert (await sh.current_graph()).id == "default"
    monkeypatch.setenv("KB_MCP_GRAPH", "acme")
    assert (await sh.current_graph()).id == "acme"


async def test_narrowed_key_without_header_binds_to_its_own_graph(monkeypatch):
    """Фидерный ключ в MCP ведёт себя как в HTTP: один граф — он и выбран.

    Без этого ``KB_MCP_GRAPH`` увёл бы такой ключ в чужой граф, и отказ
    пришёл бы там, где клиент ничего не выбирал.
    """
    monkeypatch.setenv("KB_MCP_GRAPH", "default")
    monkeypatch.setattr(settings.authz, "mode", "enforce")
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Reg())
    monkeypatch.setattr(sh, "get_http_headers", lambda **kw: {})
    rec = ApiKeyRecord(
        owner="feeder", tenant_id="default",
        scopes=frozenset({"write"}), graph_ids=("acme_hr",),
    )
    tok = await mint_token(monkeypatch, rec)
    monkeypatch.setattr(sh, "get_access_token", lambda: tok)
    assert (await sh.current_graph(Action.WRITE)).id == "acme_hr"


async def test_multi_graph_key_without_header_still_uses_configured_graph(monkeypatch):
    monkeypatch.setenv("KB_MCP_GRAPH", "acme")
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Reg())
    monkeypatch.setattr(sh, "get_http_headers", lambda **kw: {})
    rec = ApiKeyRecord(
        owner="two", tenant_id="default",
        scopes=frozenset({"read"}), graph_ids=("acme", "beta"),
    )
    tok = await mint_token(monkeypatch, rec)
    monkeypatch.setattr(sh, "get_access_token", lambda: tok)
    assert (await sh.current_graph()).id == "acme"


async def test_current_graph_invalid_x_graph_is_tool_error(monkeypatch):
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Reg())
    monkeypatch.setattr(sh, "get_http_headers", lambda **kw: {"x-graph": "Bad;Id"})
    with pytest.raises(ToolError, match="invalid X-Graph"):
        await sh.current_graph()


async def test_current_graph_unknown_or_not_ready_is_tool_error(monkeypatch):
    from src.tenancy.registry import GraphNotFound, GraphNotReady

    class _Bad:
        def __init__(self, exc):
            self.exc = exc

        async def get(self, gid):
            raise self.exc
    monkeypatch.setattr(sh, "get_http_headers", lambda **kw: {"x-graph": "acme"})
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Bad(GraphNotFound("acme")))
    with pytest.raises(ToolError, match="not found"):
        await sh.current_graph()
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Bad(GraphNotReady("acme", "deleting")))
    with pytest.raises(ToolError, match="deleting"):
        await sh.current_graph()


async def test_current_graph_stdio_uses_configured_graph(monkeypatch):
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Reg())
    monkeypatch.setattr(sh, "get_http_headers", lambda **kw: {})
    monkeypatch.setattr(sh, "_configured_mcp_graph", lambda: "default")
    assert (await sh.current_graph()).id == "default"


async def test_current_graph_honours_x_graph_without_access_token(monkeypatch):
    """MCP HTTP with auth disabled (no token): X-Graph IS honoured."""
    monkeypatch.delenv("KB_MCP_GRAPH", raising=False)
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Reg())
    monkeypatch.setattr(sh, "get_http_headers", lambda **kw: {"x-graph": "other"})
    assert (await sh.current_graph()).id == "other"


async def test_current_graph_real_stdio_has_no_header(monkeypatch):
    """Unpatched get_http_headers outside any HTTP request -> KB_MCP_GRAPH."""
    monkeypatch.setenv("KB_MCP_GRAPH", "acme")
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Reg())
    assert (await sh.current_graph()).id == "acme"

# ── servers: every tool call is bound via current_graph ────────────


async def test_search_tools_carry_bound_graph_into_workflow_params(monkeypatch):
    from unittest.mock import AsyncMock, patch

    from src.mcp import search_server
    from tests.test_mcp.test_search_server_dates import _fake_ctx, _outcome, _stub_client

    async def _acme():
        return new_graph_context("acme")
    monkeypatch.setattr(search_server, "current_graph", _acme)

    client = _stub_client(_outcome("drift"))
    with patch("src.mcp.search_server.get_temporal_client", new=AsyncMock(return_value=client)):
        await search_server.kb_drift_search(query="q", ctx=_fake_ctx())
    local, glob = client.start_workflow.call_args.kwargs["args"]
    assert local.graph_id == "acme" and glob.graph_id == "acme"
    assert client.start_workflow.call_args.kwargs["id"].startswith("mcp-drift-acme-")

    client = _stub_client(_outcome())
    with patch("src.mcp.search_server.get_temporal_client", new=AsyncMock(return_value=client)):
        await search_server.kb_search(query="q", ctx=_fake_ctx())
    assert client.start_workflow.call_args.args[1].graph_id == "acme"


async def test_search_tool_refusal_starts_no_workflow(monkeypatch):
    from unittest.mock import AsyncMock, patch

    from src.mcp import search_server
    from tests.test_mcp.test_search_server_dates import _fake_ctx, _outcome, _stub_client

    async def _refuse():
        raise ToolError("graph 'acme' not found")
    monkeypatch.setattr(search_server, "current_graph", _refuse)

    client = _stub_client(_outcome())
    with patch("src.mcp.search_server.get_temporal_client", new=AsyncMock(return_value=client)):
        with pytest.raises(ToolError):
            await search_server.kb_search(query="q", ctx=_fake_ctx())
    client.start_workflow.assert_not_awaited()


async def test_stats_tool_builds_repository_for_bound_graph(monkeypatch):
    from src.mcp import stats_server

    seen = {}

    class _Repo:
        def __init__(self, graph):
            seen["graph"] = graph.id

        async def list_sources(self):
            return []

    async def _acme():
        return new_graph_context("acme")
    monkeypatch.setattr(stats_server, "current_graph", _acme)
    monkeypatch.setattr(stats_server, "StatsRepository", _Repo)
    await stats_server.stat_indicators_search()
    assert seen["graph"] == "acme"


async def test_tools_server_tool_uses_bound_graph(monkeypatch):
    from unittest.mock import AsyncMock

    from src.intake.repository import IntakeRepository
    from src.mcp import tools_server

    seen = {}
    orig_init = IntakeRepository.__init__

    def _spy(self, *a, graph=None, **kw):
        seen["graph"] = graph.id
        orig_init(self, *a, graph=graph, **kw)

    async def _acme():
        return new_graph_context("acme")
    monkeypatch.setattr(tools_server, "current_graph", _acme)
    monkeypatch.setattr(IntakeRepository, "__init__", _spy)
    monkeypatch.setattr(IntakeRepository, "status_counts_by", AsyncMock(return_value=[]))
    await tools_server.channel_message_stats()
    assert seen["graph"] == "acme"
