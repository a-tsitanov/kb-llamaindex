import pytest

import src.analytics.centrality_compute as cc
from src.analytics import materialize as m
from src.graph.nebula_store import entity_vid
from tests.test_analytics.conftest import _FakeStore, _NebulaStmtStore


@pytest.mark.asyncio
async def test_write_centrality_pagerank_shape(monkeypatch):
    # Nebula computes centrality in-worker (compute_all over the edge export)
    # and writes one UPDATE VERTEX per scored entity.
    computed: list[int] = []

    def _fake_compute_all(store, **_kw):
        computed.append(1)
        return {"pagerank": {"A": 0.9, "B": 0.1}, "betweenness": {}, "eigenvector": {}}

    monkeypatch.setattr(cc, "compute_all", _fake_compute_all)
    store = _NebulaStmtStore()
    n = await m.write_centrality(store, "g1", "pagerank")
    assert n == 2
    assert computed == [1]  # the in-worker compute ran (once)
    # metric inlined into write-back
    assert store.calls == [
        f'UPDATE VERTEX ON `Entity` "{entity_vid("A")}" SET pagerank = 0.9;\n'
        f'UPDATE VERTEX ON `Entity` "{entity_vid("B")}" SET pagerank = 0.1;'
    ]


@pytest.mark.asyncio
async def test_write_centrality_rejects_unknown_metric():
    store = _FakeStore(rows=[])
    with pytest.raises(ValueError):
        await m.write_centrality(store, "g1", "bogus; DROP")  # allowlist guard


@pytest.mark.asyncio
async def test_write_link_prediction_is_a_noop_on_nebula():
    # gds.nodeSimilarity has no in-worker port: under nebula link prediction
    # is a documented no-op (src/analytics/materialize.py) -- nothing is
    # written and the store is never touched.
    store = _NebulaStmtStore()
    n = await m.write_link_prediction(store, "g1", top_k=10, min_score=0.5)
    assert n == 0
    assert store.calls == []


@pytest.mark.asyncio
async def test_failsoft_none_store():
    assert await m.write_centrality(None, "g", "pagerank") == 0
