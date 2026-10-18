"""Smoke tests for the MCP-1 search server.

We don't talk to a real Temporal cluster here — only assert that:
  * `_list_tools` exposes the four orchestrated search tools (kb_search
    + kb_global_search + kb_drift_search + kb_auto_search) with the
    right names + description excerpt,
  * each tool's input schema exposes the `query` parameter and no legacy
    `mode` selector (R7b: the local flow submits the plan-execute
    ``SearchOrchestratorWorkflow``),
  * the startup auth check passes when KB_MCP_REQUIRE_AUTH=false (an
    empty API_KEYS env no longer exits — R-P6, see test_auth.py).
"""

from __future__ import annotations

import pytest

_EXPECTED_SEARCH_TOOLS = {
    "kb_search",
    "kb_global_search",
    "kb_drift_search",
    "kb_auto_search",
    "kb_analyze",
}


@pytest.mark.asyncio
async def test_search_server_lists_all_search_tools():
    from src.mcp import search_server
    tools = await search_server.mcp._list_tools()
    by_name = {t.name: t for t in tools}
    assert set(by_name) == _EXPECTED_SEARCH_TOOLS
    assert "knowledge base" in by_name["kb_search"].description.lower()
    assert "global" in by_name["kb_global_search"].description.lower()


@pytest.mark.asyncio
async def test_search_tools_schema_includes_query_param():
    from src.mcp import search_server
    tools = await search_server.mcp._list_tools()
    by_name = {t.name: t for t in tools}
    # R7b: orchestrator is local-only — `mode` is gone; `query` is the
    # required input on every search tool.
    for name in _EXPECTED_SEARCH_TOOLS:
        props = by_name[name].parameters.get("properties", {})
        assert "query" in props, f"{name} missing query param"
        assert "mode" not in props, f"{name} should not expose mode"


def test_auth_gate_passes_when_disabled(monkeypatch):
    monkeypatch.setenv("KB_MCP_REQUIRE_AUTH", "false")
    import src.mcp._shared as shared
    # Should not raise even with empty keys.
    shared.assert_api_key_env_set()
