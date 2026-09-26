"""Trust-based fact-conflict resolution (src/graph/edge_conflicts.py)."""

from types import SimpleNamespace

import pytest

from src.graph.edge_conflicts import (
    StoredEdge,
    decide,
    load_stored_edges,
    resolve_edge_conflicts,
)


def _rel(src: str, tgt: str, label: str = "WORKS_AT", polarity: str = "affirmed"):
    return SimpleNamespace(
        source_id=src, target_id=tgt, label=label,
        properties={"polarity": polarity, "description": "d"},
    )


# ── policy ──────────────────────────────────────────────────────────────────

def test_same_polarity_is_not_a_conflict():
    assert decide(
        stored_polarity="affirmed", stored_trust=0.9,
        new_polarity="affirmed", new_trust=0.1,
    ) == "new"


def test_missing_polarity_never_blocks_the_write():
    assert decide(
        stored_polarity="", stored_trust=0.9, new_polarity="negated", new_trust=0.1,
    ) == "new"


def test_higher_trust_source_keeps_the_belief():
    assert decide(
        stored_polarity="affirmed", stored_trust=0.9,
        new_polarity="negated", new_trust=0.4,
    ) == "stored"


def test_equal_trust_falls_back_to_recency():
    assert decide(
        stored_polarity="affirmed", stored_trust=0.5,
        new_polarity="negated", new_trust=0.5,
    ) == "new"


# ── resolution over a batch ─────────────────────────────────────────────────

def test_low_trust_flip_is_held_back_but_edge_still_updates():
    rel = _rel("Иванов", "ООО Ромашка", polarity="negated")
    stored = {("Иванов", "ООО Ромашка"): StoredEdge("affirmed", 0.9, "doc-old")}

    rels, conflicts = resolve_edge_conflicts(
        [rel], stored, doc_trust=0.2, doc_id="doc-new", ingest_epoch=20000,
    )

    assert len(rels) == 1, "a losing write must not drop the edge"
    assert rel.properties["polarity"] == "affirmed", "stored belief survives"
    assert rel.properties["source_trust"] == pytest.approx(0.9)
    assert rel.properties["superseded_at"] == 0
    assert [(c.winner, c.stored_doc_id, c.new_doc_id) for c in conflicts] == [
        ("stored", "doc-old", "doc-new"),
    ]


def test_high_trust_flip_wins_and_stamps_supersede():
    rel = _rel("Иванов", "ООО Ромашка", polarity="negated")
    stored = {("Иванов", "ООО Ромашка"): StoredEdge("affirmed", 0.3, "doc-old")}

    _, conflicts = resolve_edge_conflicts(
        [rel], stored, doc_trust=0.9, doc_id="doc-new", ingest_epoch=20000,
    )

    assert rel.properties["polarity"] == "negated"
    assert rel.properties["source_trust"] == pytest.approx(0.9)
    assert rel.properties["superseded_at"] == 20000
    assert [c.winner for c in conflicts] == ["new"]


def test_agreement_keeps_the_strongest_trust_seen():
    rel = _rel("Иванов", "ООО Ромашка", polarity="affirmed")
    stored = {("Иванов", "ООО Ромашка"): StoredEdge("affirmed", 0.9, "doc-old")}

    _, conflicts = resolve_edge_conflicts(
        [rel], stored, doc_trust=0.2, doc_id="doc-new", ingest_epoch=20000,
    )

    assert conflicts == []
    assert rel.properties["source_trust"] == pytest.approx(0.9)


def test_unknown_edge_is_written_with_this_documents_trust():
    rel = _rel("Петров", "МУП Заря")

    _, conflicts = resolve_edge_conflicts(
        [rel], {}, doc_trust=0.4, doc_id="doc-new", ingest_epoch=20000,
    )

    assert conflicts == []
    assert rel.properties["source_trust"] == pytest.approx(0.4)
    assert rel.properties["superseded_at"] == 0


# ── read-back ───────────────────────────────────────────────────────────────

def test_load_stored_edges_is_fail_open():

    class _Broken:
        def structured_query(self, *_a, **_kw):
            raise RuntimeError("graphd down")

    assert load_stored_edges(_Broken(), [_rel("a", "b")]) == {}


def test_load_stored_edges_nebula_keys_by_pair():
    from src.graph.nebula_store import entity_vid

    seen = {}

    class _Store:
        def structured_query(self, query, param_map=None):
            seen["query"] = query
            return [{
                "s": entity_vid("Иванов"), "d": entity_vid("ООО Ромашка"),
                "polarity": "affirmed", "source_trust": 0.7, "first_doc_id": "doc-old",
            }]

    out = load_stored_edges(_Store(), [_rel("Иванов", "ООО Ромашка")])

    # nebula collapses every label of a pair onto one rank-0 RELATED edge,
    # so the edge is read — and keyed — by (src, tgt).
    assert seen["query"].startswith("FETCH PROP ON `RELATED`")
    assert f'"{entity_vid("Иванов")}"->"{entity_vid("ООО Ромашка")}"' in seen["query"]
    assert out[("Иванов", "ООО Ромашка")] == StoredEdge(
        "affirmed", 0.7, "doc-old",
    )
