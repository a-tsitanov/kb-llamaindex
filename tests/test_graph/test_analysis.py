"""Unit tests for read-only graph analysis (Track 7b) — backend-agnostic
fail-soft / empty-input behaviour. Result shaping under nebula lives in
tests/test_graph/test_analysis_nebula.py.

A fake store returns canned rows keyed by a statement fragment.
"""

from __future__ import annotations

import pytest

from src.graph.analysis import (
    components,
    graph_stats,
    pagerank,
    personalized_pagerank,
    shortest_path,
)


class _FakeStore:
    """Returns canned rows depending on the statement fragment seen."""

    def __init__(self, *, rows_by_fragment=None, raise_on=None):
        self._rows = rows_by_fragment or {}
        self._raise_on = raise_on
        self.calls: list[str] = []

    def structured_query(self, cypher, param_map=None):
        self.calls.append(cypher)
        if self._raise_on and self._raise_on in cypher:
            raise RuntimeError("boom")
        for fragment, rows in self._rows.items():
            if fragment in cypher:
                return rows
        return []


# ── personalized pagerank ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_personalized_pagerank_empty_seeds_is_empty():
    # No seeds → no personalization target → empty (and no projection run).
    store = _FakeStore(rows_by_fragment={"`Entity`": [{"name": "X", "score": 1.0}]})
    assert await personalized_pagerank(store, [], top_n=5) == []
    assert await personalized_pagerank(store, ["  "], top_n=5) == []
    assert store.calls == []


@pytest.mark.asyncio
async def test_personalized_pagerank_none_store_failsafe():
    assert await personalized_pagerank(None, ["A"]) == []


# ── shortest path ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_shortest_path_none_when_disconnected():
    store = _FakeStore(rows_by_fragment={})  # no path row
    out = await shortest_path(store, "A", "B")
    assert out["path"] == []
    assert out["hops"] == -1


# ── fail-soft ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_none_store_is_failsafe():
    assert await pagerank(None) == []
    assert (await components(None))["component_count"] == 0
    assert (await shortest_path(None, "A", "B"))["hops"] == -1
    # No store is not a measurement of zero entities.
    out = await graph_stats(None)
    assert out["entities"] is None
    assert out["errors"]["store"]


@pytest.mark.asyncio
async def test_store_error_is_failsafe():
    store = _FakeStore(raise_on="`Entity`.pagerank")
    assert await pagerank(store) == []
