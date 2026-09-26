"""Unit tests for GraphRetriever.awalk — bounded N-hop graph traversal.

Under nebula ``awalk`` calls ``store.subgraph(entity_vid(name), hops)`` and
maps the returned ``{entities, relations}`` rows; a fake store records the
call and returns canned rows. NO live graph: we assert the hops clamp, the
node/edge caps, rel_filter handling and the RoundGraphData mapping.
"""

from __future__ import annotations

import pytest

from src.graph.nebula_store import entity_vid
from src.graph.retriever import (
    GRAPH_WALK_EDGE_CAP,
    GRAPH_WALK_MAX_HOPS,
    GRAPH_WALK_NODE_CAP,
    GraphRetriever,
    _relation_is_live,
)


class _FakeStore:
    """Answers ``subgraph`` (the nebula walk entry) with canned rows."""

    def __init__(self, rows=None):
        self._rows = rows or []
        self.last_subgraph_call = None

    def structured_query(self, query, param_map=None):
        return []

    def subgraph(self, vid, hops, *, edge="RELATED"):
        self.last_subgraph_call = (vid, hops, edge)
        return self._rows


def _retriever_with_store(store, *, filter_polarity_temporal=True):
    """Build a GraphRetriever without touching PropertyGraphIndex."""
    r = GraphRetriever.__new__(GraphRetriever)
    r._graph_store = store
    r._filter_polarity_temporal = filter_polarity_temporal
    return r


def _rel(src, tgt, label, **props):
    return {"src": src, "tgt": tgt, "label": label, **props}


@pytest.mark.asyncio
async def test_awalk_clamps_hops_and_caps_output():
    n = max(GRAPH_WALK_NODE_CAP, GRAPH_WALK_EDGE_CAP) + 5
    rows = [{
        "entities": [{"name": f"E{i}", "label": "P", "description": ""} for i in range(n)],
        "relations": [_rel("Иванов", f"E{i}", "KNOWS") for i in range(n)],
    }]
    store = _FakeStore(rows=rows)
    r = _retriever_with_store(store)
    data = await r.awalk("Иванов", hops=99)
    vid, hops, _edge = store.last_subgraph_call
    # hops clamped to the hard max; walk starts at the named entity
    assert hops == GRAPH_WALK_MAX_HOPS
    assert vid == entity_vid("Иванов")
    # output bounded by the node / edge caps
    assert len(data.entities) == GRAPH_WALK_NODE_CAP
    assert len(data.relations) == GRAPH_WALK_EDGE_CAP


@pytest.mark.asyncio
async def test_awalk_no_rel_filter_keeps_all_labels():
    rows = [{
        "entities": [{"name": "A", "label": "P", "description": ""}],
        "relations": [_rel("A", "B", "KNOWS"), _rel("A", "C", "WORKS_AT")],
    }]
    r = _retriever_with_store(_FakeStore(rows=rows))
    data = await r.awalk("A", hops=2, rel_filter=None)
    assert {rel["label"] for rel in data.relations} == {"KNOWS", "WORKS_AT"}


@pytest.mark.asyncio
async def test_awalk_maps_rows_to_entities_and_relations():
    rows = [
        {
            "entities": [
                {"name": "A", "label": "Person", "description": "a"},
                {"name": "B", "label": "Person", "description": "b"},
            ],
            "relations": [
                {"src": "A", "tgt": "B", "label": "KNOWS"},
            ],
        }
    ]
    store = _FakeStore(rows=rows)
    r = _retriever_with_store(store)
    data = await r.awalk("A", hops=2)
    names = {e["entity_name"] for e in data.entities}
    assert names == {"A", "B"}
    assert data.relations[0]["label"] == "KNOWS"


@pytest.mark.asyncio
async def test_awalk_no_store_returns_empty():
    r = _retriever_with_store(None)
    data = await r.awalk("A", hops=2)
    assert data.entities == []
    assert data.relations == []


# ── #8: polarity + temporal-validity filtering ───────────────────────


def test_relation_is_live_polarity():
    now = "2026-06-16"
    # affirmed / uncertain / missing polarity ⇒ live
    assert _relation_is_live({"polarity": "affirmed"}, now_iso=now)
    assert _relation_is_live({"polarity": "uncertain"}, now_iso=now)
    assert _relation_is_live({}, now_iso=now)
    assert _relation_is_live({"polarity": None}, now_iso=now)
    # negated ⇒ dropped
    assert not _relation_is_live({"polarity": "negated"}, now_iso=now)


def test_relation_is_live_temporal():
    now = "2026-06-16"
    # expired (valid_to strictly before now) ⇒ dropped
    assert not _relation_is_live({"valid_to": "2020-01-01"}, now_iso=now)
    assert not _relation_is_live({"valid_to": "2020"}, now_iso=now)
    # future / today / open-ended ⇒ live
    assert _relation_is_live({"valid_to": "2030-01-01"}, now_iso=now)
    assert _relation_is_live({"valid_to": "2026-06-16"}, now_iso=now)
    assert _relation_is_live({"valid_to": None}, now_iso=now)
    assert _relation_is_live({}, now_iso=now)


@pytest.mark.asyncio
async def test_awalk_filters_negated_and_keeps_affirmed_and_missing():
    rows = [{
        "entities": [{"name": "A", "label": "P", "description": ""}],
        "relations": [
            _rel("A", "B", "OWNS", polarity="affirmed"),
            _rel("A", "C", "OWNS", polarity="negated"),
            _rel("A", "D", "OWNS"),  # no polarity prop ⇒ affirmed
        ],
    }]
    r = _retriever_with_store(_FakeStore(rows=rows))
    data = await r.awalk("A", hops=2)
    tgts = {rel["tgt_id"] for rel in data.relations}
    assert tgts == {"B", "D"}


@pytest.mark.asyncio
async def test_awalk_filters_expired_keeps_future_and_null():
    rows = [{
        "entities": [{"name": "A", "label": "P", "description": ""}],
        "relations": [
            _rel("A", "B", "OWNS", valid_to="2020-01-01"),   # expired
            _rel("A", "C", "OWNS", valid_to="2099-01-01"),   # future
            _rel("A", "D", "OWNS"),                           # open-ended
        ],
    }]
    r = _retriever_with_store(_FakeStore(rows=rows))
    data = await r.awalk("A", hops=2)
    tgts = {rel["tgt_id"] for rel in data.relations}
    assert tgts == {"C", "D"}


@pytest.mark.asyncio
async def test_awalk_exposes_polarity_and_valid_to_in_rows():
    rows = [{
        "entities": [{"name": "A", "label": "P", "description": ""}],
        "relations": [
            _rel("A", "B", "OWNS", polarity="affirmed",
                 valid_from="2015", valid_to="2099"),
        ],
    }]
    r = _retriever_with_store(_FakeStore(rows=rows))
    data = await r.awalk("A", hops=2)
    rel = data.relations[0]
    assert rel["polarity"] == "affirmed"
    assert rel["valid_from"] == "2015"
    assert rel["valid_to"] == "2099"


@pytest.mark.asyncio
async def test_awalk_opt_out_disables_filtering():
    rows = [{
        "entities": [{"name": "A", "label": "P", "description": ""}],
        "relations": [
            _rel("A", "C", "OWNS", polarity="negated"),
            _rel("A", "B", "OWNS", valid_to="2020-01-01"),
        ],
    }]
    r = _retriever_with_store(
        _FakeStore(rows=rows), filter_polarity_temporal=False,
    )
    data = await r.awalk("A", hops=2)
    tgts = {rel["tgt_id"] for rel in data.relations}
    assert tgts == {"B", "C"}
