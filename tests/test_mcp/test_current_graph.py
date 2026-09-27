import pytest
from fastmcp.exceptions import ToolError

import src.mcp._shared as sh
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.context import default_graph_context, new_graph_context


class _Tok:
    def __init__(self, claims):
        self.claims = claims


class _Reg:
    async def get(self, gid):
        return default_graph_context() if gid == "default" else new_graph_context(gid)


async def test_verifier_maps_key_record_to_claims(monkeypatch):
    class _Store:
        async def lookup(self, k):
            return ApiKeyRecord("acme", ("acme",), False) if k == "good" else None
    monkeypatch.setattr(sh, "get_api_key_store", lambda: _Store())
    v = sh.RegistryTokenVerifier()
    tok = await v.verify_token("good")
    assert tok.claims == {"owner": "acme", "graph_ids": ["acme"], "is_admin": False}
    assert await v.verify_token("bad") is None


async def test_current_graph_http_uses_header(monkeypatch):
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Reg())
    monkeypatch.setattr(sh, "get_access_token", lambda: _Tok({"owner": "a", "graph_ids": ["acme", "acme_hr"], "is_admin": False}))
    monkeypatch.setattr(sh, "get_http_headers", lambda **kw: {"x-graph": "acme_hr"})
    assert (await sh.current_graph()).id == "acme_hr"


async def test_current_graph_http_refuses_foreign_graph(monkeypatch):
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Reg())
    monkeypatch.setattr(sh, "get_access_token", lambda: _Tok({"owner": "a", "graph_ids": ["acme"], "is_admin": False}))
    monkeypatch.setattr(sh, "get_http_headers", lambda **kw: {"x-graph": "other"})
    with pytest.raises(ToolError):
        await sh.current_graph()


async def test_current_graph_http_multi_graph_needs_header(monkeypatch):
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Reg())
    monkeypatch.setattr(sh, "get_access_token", lambda: _Tok({"owner": "a", "graph_ids": ["acme", "b"], "is_admin": False}))
    monkeypatch.setattr(sh, "get_http_headers", lambda **kw: {})
    with pytest.raises(ToolError):
        await sh.current_graph()


async def test_current_graph_stdio_uses_configured_graph(monkeypatch):
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Reg())
    monkeypatch.setattr(sh, "get_access_token", lambda: None)
    monkeypatch.setattr(sh, "get_http_headers", lambda **kw: {})
    monkeypatch.setattr(sh, "_configured_mcp_graph", lambda: "default")
    assert (await sh.current_graph()).id == "default"


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
        raise ToolError("graph not allowed for this key")
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

    from src.mcp import tools_server
    from src.storage.postgres import AsyncPostgres

    seen = {}
    orig_init = AsyncPostgres.__init__

    def _spy(self, *a, graph=None, **kw):
        seen["graph"] = graph.id
        orig_init(self, *a, graph=graph, **kw)

    async def _acme():
        return new_graph_context("acme")
    monkeypatch.setattr(tools_server, "current_graph", _acme)
    monkeypatch.setattr(AsyncPostgres, "__init__", _spy)
    monkeypatch.setattr(AsyncPostgres, "status_counts_by", AsyncMock(return_value=[]))
    await tools_server.channel_message_stats()
    assert seen["graph"] == "acme"
