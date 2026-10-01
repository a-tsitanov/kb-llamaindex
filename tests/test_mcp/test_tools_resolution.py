"""MCP-level name resolution for the multi-name graph tools."""
import pytest

from src.graph import analysis
from src.graph.name_resolution import NameResolver
from src.mcp import tools_server as ts
from tests.test_graph.test_name_resolution import GRAPH, FakeLexicon, fetch_from


@pytest.fixture
def wired(monkeypatch):
    seen = {}

    async def resolver():
        return NameResolver(FakeLexicon(), fetch_from(GRAPH))

    async def gs():
        return object()

    async def sp(store, a, b, max_hops=6):
        seen["sp"] = (a, b)
        return {"path": [a, b], "hops": 1}

    async def ppr(store, seeds, top_n=20):
        seen["ppr"] = list(seeds)
        return [{"name": s, "score": 1.0} for s in seeds]

    monkeypatch.setattr(ts, "_resolver", resolver)
    monkeypatch.setattr(ts, "_gs", gs)
    monkeypatch.setattr(analysis, "shortest_path", sp)
    monkeypatch.setattr(analysis, "personalized_pagerank", ppr)
    return seen


def _fn(tool):
    return getattr(tool, "fn", tool)


@pytest.mark.asyncio
async def test_shortest_path_runs_between_canonical_names(wired):
    out = await _fn(ts.graph_shortest_path)("Росатом", "Alexey Likhachev")
    assert wired["sp"] == ("Rosatom", "Алексей Лихачёв") and out["hops"] == 1
    assert [r["chosen"]["name"] for r in out["resolution"]] == ["Rosatom", "Алексей Лихачёв"]


@pytest.mark.asyncio
async def test_shortest_path_with_an_unknown_end_says_which(wired):
    out = await _fn(ts.graph_shortest_path)("Росатом", "Газпромнефть")
    assert out["hops"] == -1 and out["unresolved"] == ["Газпромнефть"] and "sp" not in wired


@pytest.mark.asyncio
async def test_ppr_keeps_resolved_seeds_and_lists_the_rest(wired):
    out = await _fn(ts.graph_personalized_pagerank)(["РОСАТОМ", "Газпромнефть"])
    assert wired["ppr"] == ["Rosatom"] and out["unresolved"] == ["Газпромнефть"]


@pytest.mark.asyncio
async def test_depth_and_hops_are_clamped_with_a_note(monkeypatch):
    from src.retrieval import atomic_tools
    seen = {}

    async def fake_gs(g, *, query, depth, ranker):
        seen["depth"] = depth
        return atomic_tools.ToolResult(sources=[], observation='{"entities": []}')

    async def fake_fn(g, *, entity_name, hops, **kw):
        seen["hops"] = hops
        return atomic_tools.ToolResult(sources=[], observation='{"entities": []}')

    async def none():
        return None
    monkeypatch.setattr(atomic_tools, "graph_search", fake_gs)
    monkeypatch.setattr(atomic_tools, "find_neighbours", fake_fn)
    monkeypatch.setattr(ts, "_g", none)
    monkeypatch.setattr(ts, "_ranker", none)
    monkeypatch.setattr(ts, "_resolver", none)
    out = await _fn(ts.graph_search)("q", depth=2)
    assert seen["depth"] == 1 and "graph_walk" in out["depth_note"]
    out = await _fn(ts.find_neighbours)("X", hops=3)
    assert seen["hops"] == 1 and "depth_note" in out
    out = await _fn(ts.graph_search)("q")
    assert "depth_note" not in out
