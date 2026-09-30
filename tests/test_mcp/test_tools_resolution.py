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
