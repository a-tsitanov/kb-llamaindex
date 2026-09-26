"""Tests for E1 — ON-CREATE-emulated first_seen stamping.

Nebula issues per-entity ``UPDATE VERTEX ... WHEN created_at == 0`` and
per-relation ``UPDATE EDGE ... WHEN created_at == 0`` (rank 0).
"""

from src.graph.first_seen import stamp_first_seen
from src.graph.nebula_store import entity_vid


class _Rec:
    def __init__(self):
        self.calls = []

    def structured_query(self, cypher, param_map=None):
        self.calls.append((cypher, param_map or {}))
        return []


# ── nebula backend dispatch ──────────────────────────────────────────────────


def test_stamp_nebula_issues_update_vertex_when_created_at_zero():
    store = _Rec()
    stamp_first_seen(
        store,
        entity_names=["A", "B"],
        relations=[("x", "L", "y")],
        ingest_epoch=42,
        doc_id="doc9",
    )

    update_calls = [c for c in store.calls if "UPDATE VERTEX ON `Entity`" in c[0]]
    assert len(update_calls) == 2

    vid_a, vid_b = entity_vid("A"), entity_vid("B")
    stmt_by_vid = {vid_a: None, vid_b: None}
    for cypher, _ in update_calls:
        for vid in stmt_by_vid:
            if f'"{vid}"' in cypher:
                stmt_by_vid[vid] = cypher

    for vid, cypher in stmt_by_vid.items():
        assert cypher is not None, f"missing UPDATE VERTEX for vid {vid}"
        assert 'SET created_at = 42, first_doc_id = "doc9" WHEN created_at == 0' in cypher

    # rel first-seen: one UPDATE EDGE for ("x","L","y") on rank 0, guarded
    edge_calls = [c for c in store.calls if "UPDATE EDGE ON `RELATED`" in c[0]]
    assert len(edge_calls) == 1
    vid_x, vid_y = entity_vid("x"), entity_vid("y")
    assert f'"{vid_x}" -> "{vid_y}"@0' in edge_calls[0][0]
    assert 'SET created_at = 42, first_doc_id = "doc9" WHEN created_at == 0' in edge_calls[0][0]

    # nebula path uses inline nGQL, not param_map
    assert all(param_map == {} for _, param_map in store.calls)


def test_stamp_nebula_relations_only_issues_update_edge():
    store = _Rec()
    stamp_first_seen(
        store,
        entity_names=[],
        relations=[("x", "L", "y")],
        ingest_epoch=42,
        doc_id="doc9",
    )
    assert len(store.calls) == 1
    stmt = store.calls[0][0]
    assert "UPDATE EDGE ON `RELATED`" in stmt
    assert f'"{entity_vid("x")}" -> "{entity_vid("y")}"@0' in stmt
    assert "WHEN created_at == 0" in stmt


def test_stamp_nebula_fail_soft_on_store_error():

    class _Bad:
        def structured_query(self, cypher, param_map=None):
            raise RuntimeError("boom")

    # must not raise
    stamp_first_seen(
        _Bad(),
        entity_names=["A"],
        relations=[],
        ingest_epoch=1,
        doc_id="d",
    )


def test_stamp_noop_on_empty_nebula():
    store = _Rec()
    stamp_first_seen(store, entity_names=[], relations=[], ingest_epoch=1, doc_id="d")
    assert store.calls == []


def test_stamp_entities_only_no_relations_nebula():
    """When relations list is empty, only the entity pass fires."""
    store = _Rec()
    stamp_first_seen(store, entity_names=["Z"], relations=[], ingest_epoch=5, doc_id="d3")
    assert len(store.calls) == 1
    assert "UPDATE VERTEX ON `Entity`" in store.calls[0][0]
    assert f'"{entity_vid("Z")}"' in store.calls[0][0]
