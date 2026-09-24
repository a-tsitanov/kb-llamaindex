"""Unit tests for GraphRetriever per-call ``path_depth`` (nebula backend).

Under nebula ``aretrieve`` seeds entities (vector kNN + entity table) and
subgraph-expands each one via ``awalk``; ``path_depth`` is the walk's hop
count.  A fake store records the hops each ``subgraph`` call receives — no
live store / LLM.  Asserts: the default depth is 1, a per-call depth reaches
the walk, and out-of-range depths are clamped to ``[1, GRAPH_PATH_DEPTH_MAX]``.
"""

from __future__ import annotations

import pytest

from src.graph.nebula_store import entity_vid
from src.graph.retriever import (
    GRAPH_PATH_DEPTH_MAX,
    GraphRetriever,
    RoundGraphData,
)


class _FakeStore:
    def __init__(self) -> None:
        self.subgraph_calls: list[tuple[str, int]] = []

    def structured_query(self, query, param_map=None):
        return []

    def subgraph(self, vid, hops, *, edge="RELATED"):
        self.subgraph_calls.append((vid, hops))
        return []  # empty walk → empty RoundGraphData


def _build(monkeypatch):
    store = _FakeStore()
    r = GraphRetriever.for_store(store, similarity_top_k=10)

    async def _knn(_q):
        return ["Seed"]

    async def _no_table(_q):
        return []

    monkeypatch.setattr(r, "_nebula_knn_names", _knn)
    monkeypatch.setattr(r, "_entity_table_names", _no_table)
    return store, r


def _hops(store):
    return [h for _vid, h in store.subgraph_calls]


@pytest.mark.asyncio
async def test_default_depth_is_one(monkeypatch):
    store, r = _build(monkeypatch)
    out = await r.aretrieve("q")  # path_depth=None → default
    assert isinstance(out, RoundGraphData)
    assert store.subgraph_calls == [(entity_vid("Seed"), 1)]


@pytest.mark.asyncio
async def test_per_call_depth_reaches_walk(monkeypatch):
    store, r = _build(monkeypatch)
    await r.aretrieve("q", path_depth=2)
    assert _hops(store) == [2]


@pytest.mark.asyncio
async def test_depth_clamped_to_max(monkeypatch):
    store, r = _build(monkeypatch)
    await r.aretrieve("q", path_depth=99)
    assert _hops(store) == [GRAPH_PATH_DEPTH_MAX]


@pytest.mark.asyncio
async def test_depth_clamped_to_min(monkeypatch):
    store, r = _build(monkeypatch)
    await r.aretrieve("q", path_depth=0)
    assert _hops(store) == [1]
