from __future__ import annotations

from src.graph import events_graph_ops as ego


class _NebulaRecStore:
    def __init__(self, canned: list[tuple[str, list[dict]]] | None = None):
        self.calls: list[tuple[str, dict | None]] = []
        self._canned = list(canned or [])

    def structured_query(self, stmt, param_map=None):
        self.calls.append((stmt, param_map))
        assert param_map is None, "nebula ops must not use param_map"
        for substr, rows in self._canned:
            if substr in stmt:
                return rows
        return []


# --- Nebula: new_entities MATCH; edges/connections -> [] ----------------


def test_nebula_new_entities_matches_created_at():
    store = _NebulaRecStore(canned=[
        ("created_at >=", [{"name": "NewCo", "type": "Organization", "created_at": 19799,
                            "first_doc_id": "d1"}])
    ])
    result = ego.NebulaEventsGraphOps(store).new_entities(19786, 25)
    assert result == [
        {"name": "NewCo", "type": "Organization", "created_at": 19799, "first_doc_id": "d1"}
    ]
    stmt = store.calls[0][0]
    assert "e.`Entity`.created_at >= 19786" in stmt
    assert "ORDER BY created_at DESC LIMIT 25" in stmt  # aliased ORDER BY


def test_nebula_new_edges_scans_and_filters_by_created_at():
    rows = [
        {"src": "A", "rel": "OWNS", "tgt": "B", "created_at": 19799, "first_doc_id": "d1"},
        {"src": "C", "rel": "OWNS", "tgt": "D", "created_at": 19700, "first_doc_id": "d2"},  # stale
        {"src": "E", "rel": "CONTACT", "tgt": "F", "created_at": 19790, "first_doc_id": "d3"},
    ]
    store = _NebulaRecStore(canned=[("MATCH (a:`Entity`)-[r:`RELATED`]->", rows)])
    result = ego.NebulaEventsGraphOps(store).new_edges(19786, 25)
    # >= 19786 kept, sorted created_at desc
    assert result == [
        {"src": "A", "rel": "OWNS", "tgt": "B", "created_at": 19799, "first_doc_id": "d1"},
        {"src": "E", "rel": "CONTACT", "tgt": "F", "created_at": 19790, "first_doc_id": "d3"},
    ]
    assert "WHERE" not in store.calls[0][0]  # full scan, no edge-property WHERE


def test_nebula_new_edges_respects_top_n():
    rows = [{"src": f"S{i}", "rel": "OWNS", "tgt": "T", "created_at": 19790 + i,
             "first_doc_id": "d"} for i in range(5)]
    store = _NebulaRecStore(canned=[("MATCH (a:`Entity`)-[r:`RELATED`]->", rows)])
    result = ego.NebulaEventsGraphOps(store).new_edges(19786, 2)
    assert len(result) == 2 and result[0]["created_at"] == 19794


def test_nebula_entity_new_connections_name_anchored():
    store = _NebulaRecStore(canned=[
        ("e.`Entity`.name ==", [{"rel": "OWNS", "other": "B", "created_at": 19799,
                                 "first_doc_id": "d1"}])
    ])
    result = ego.NebulaEventsGraphOps(store).entity_new_connections("A", 19786, 25)
    assert result == [{"rel": "OWNS", "other": "B", "created_at": 19799, "first_doc_id": "d1"}]
    stmt = store.calls[0][0]
    assert "e.`Entity`.name == \"A\"" in stmt
    assert "r.created_at >= 19786" in stmt
    assert "ORDER BY created_at DESC LIMIT 25" in stmt


class _NebulaRaisingStore:
    def structured_query(self, stmt, param_map=None):
        raise RuntimeError("boom")


def test_nebula_fail_soft():
    # ported from test_neo4j_fail_soft.
    assert ego.NebulaEventsGraphOps(_NebulaRaisingStore()).new_entities(0, 25) == []
