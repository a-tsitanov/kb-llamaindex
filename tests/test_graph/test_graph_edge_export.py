from __future__ import annotations

from src.graph import graph_edge_export as gee
from src.graph.nebula_store import entity_vid


class _RecNebula:
    """Fake nebula store: records nGQL (asserts inline, no param_map);
    returns canned pages per call, popped in call order, keyed by
    statement kind (LOOKUP vs GO)."""

    def __init__(self, lookup_pages=None, go_pages=None):
        self.stmts: list[str] = []
        self._lookup_pages = list(lookup_pages or [])
        self._go_pages = list(go_pages or [])

    def structured_query(self, query, param_map=None):
        assert not param_map, "nebula read must inline values"
        self.stmts.append(query)
        if query.startswith("LOOKUP ON `Entity`"):
            return self._lookup_pages.pop(0) if self._lookup_pages else []
        if query.startswith("GO FROM"):
            return self._go_pages.pop(0) if self._go_pages else []
        return []


# --- Nebula: nGQL keyset LOOKUP + batched GO ----------------------------


def test_nebula_stream_names_keyset_lookup_advances_after_and_stops():
    pages = [
        [{"name": "A"}, {"name": "B"}],   # full page (== batch_size) -> continue
        [{"name": "C"}],                  # short page -> stop
    ]
    store = _RecNebula(lookup_pages=pages)
    exp = gee.NebulaGraphEdgeExport(store)

    names = exp.stream_names(batch_size=2)

    assert names == ["A", "B", "C"]
    # nebula requires LIMIT as its OWN pipe stage (`| LIMIT n`), not a trailing
    # clause after ORDER BY — the missing pipe was a live SyntaxError near LIMIT.
    assert store.stmts == [
        'LOOKUP ON `Entity` WHERE `Entity`.name > "" YIELD `Entity`.name AS name '
        "| ORDER BY $-.name ASC | LIMIT 2;",
        'LOOKUP ON `Entity` WHERE `Entity`.name > "B" YIELD `Entity`.name AS name '
        "| ORDER BY $-.name ASC | LIMIT 2;",
    ]


def test_nebula_stream_names_no_param_map():
    store = _RecNebula(lookup_pages=[[]])
    gee.NebulaGraphEdgeExport(store).stream_names(batch_size=5)
    # _RecNebula.structured_query already asserts param_map is falsy; if we
    # got here without AssertionError, the seam is inline-only as required.


def test_nebula_stream_edges_with_names_skips_internal_name_scan():
    # Single-scan path: caller already streamed `names` (the real usage via
    # extract_entity_edges) -> stream_edges must NOT re-issue the LOOKUP
    # name-scan, only the GO edge queries.
    vid_a, vid_b = entity_vid("A"), entity_vid("B")
    dangling_vid = entity_vid("ghost")  # not a member of the exported name set

    go_pages = [[
        {"s": vid_a, "d": vid_b, "w": 3.0},        # known edge, explicit weight
        {"s": vid_a, "d": dangling_vid, "w": 2.0},  # dangling endpoint -> dropped
        {"s": vid_b, "d": vid_a, "w": None},        # known edge, weight defaults to 1.0
    ]]
    store = _RecNebula(go_pages=go_pages)  # no lookup_pages: LOOKUP must never fire
    exp = gee.NebulaGraphEdgeExport(store)

    edges = exp.stream_edges(batch_size=10, names=["A", "B"])

    assert edges == [("A", "B", 3.0), ("B", "A", 1.0)]
    lookup_stmts = [s for s in store.stmts if s.startswith("LOOKUP ON")]
    go_stmts = [s for s in store.stmts if s.startswith("GO FROM")]
    assert lookup_stmts == [], "names was supplied — must not re-scan via LOOKUP"
    assert len(go_stmts) == 1
    assert "OVER `RELATED` YIELD" in go_stmts[0]
    assert "src(edge) AS s, dst(edge) AS d, `RELATED`.weight AS w" in go_stmts[0]


def test_nebula_stream_edges_names_none_falls_back_to_internal_stream_names():
    # Fallback path: names=None -> stream_edges internally calls
    # stream_names(...) (today's behaviour), issuing the LOOKUP scan.
    vid_a, vid_b = entity_vid("A"), entity_vid("B")
    dangling_vid = entity_vid("ghost")

    lookup_pages = [[{"name": "A"}, {"name": "B"}]]  # single page, short -> stop
    go_pages = [[
        {"s": vid_a, "d": vid_b, "w": 3.0},
        {"s": vid_a, "d": dangling_vid, "w": 2.0},  # dangling endpoint -> dropped
        {"s": vid_b, "d": vid_a, "w": None},
    ]]
    store = _RecNebula(lookup_pages=lookup_pages, go_pages=go_pages)
    exp = gee.NebulaGraphEdgeExport(store)

    edges = exp.stream_edges(batch_size=10)

    assert edges == [("A", "B", 3.0), ("B", "A", 1.0)]
    lookup_stmts = [s for s in store.stmts if s.startswith("LOOKUP ON")]
    go_stmts = [s for s in store.stmts if s.startswith("GO FROM")]
    assert len(lookup_stmts) == 1, "names=None must fall back to the internal LOOKUP scan"
    assert len(go_stmts) == 1


def test_nebula_stream_edges_chunks_go_calls_by_batch_size():
    vid_a, vid_b, vid_c = entity_vid("A"), entity_vid("B"), entity_vid("C")
    go_pages = [
        [{"s": vid_a, "d": vid_b, "w": 1.0}],  # first chunk of 2 vids
        [{"s": vid_c, "d": vid_a, "w": 5.0}],  # second chunk of 1 vid
    ]
    store = _RecNebula(go_pages=go_pages)
    exp = gee.NebulaGraphEdgeExport(store)

    edges = exp.stream_edges(batch_size=2, names=["A", "B", "C"])

    assert edges == [("A", "B", 1.0), ("C", "A", 5.0)]
    go_stmts = [s for s in store.stmts if s.startswith("GO FROM")]
    assert len(go_stmts) == 2


