from __future__ import annotations

import re
from typing import ClassVar

import src.graph.community_leiden as community_leiden
from src.graph.community_leiden import extract_entity_edges
from src.graph.nebula_store import entity_vid

_AFTER = re.compile(r'`Entity`\.name > "([^"]*)"')
_LIMIT = re.compile(r"LIMIT (\d+)")
_VIDS = re.compile(r'"([0-9a-f]+)"')


class _FakeNebula:
    """Answers the nGQL the nebula ``GraphEdgeExport`` issues:

    * ``LOOKUP ON `Entity` WHERE `Entity`.name > "<after>" ... | LIMIT n`` →
      the next keyset page of ``names`` (sorted, strictly after ``after``);
    * ``GO FROM "<vid>", ... OVER `RELATED` ...`` → every edge whose source
      vid is listed, as ``{s, d, w}`` rows.
    """

    def __init__(self, names: list[str], edges: list[tuple[str, str, float]]):
        self._names = sorted(names)
        self._edges = edges
        self.stmts: list[str] = []

    def structured_query(self, query, param_map=None):
        assert not param_map, "nebula read must inline values"
        self.stmts.append(query)
        if query.startswith("LOOKUP ON `Entity`"):
            after = _AFTER.search(query).group(1)
            limit = int(_LIMIT.search(query).group(1))
            return [{"name": n} for n in self._names if n > after][:limit]
        if query.startswith("GO FROM"):
            listed = set(_VIDS.findall(query.split(" OVER ")[0]))
            return [
                {"s": entity_vid(s), "d": entity_vid(d), "w": w}
                for s, d, w in self._edges if entity_vid(s) in listed
            ]
        return []


def test_extract_returns_edges_and_all_node_names():
    store = _FakeNebula(
        names=["A", "B", "C"],
        edges=[("A", "B", 2.0), ("B", "C", 1.0)],
    )
    edges, nodes = extract_entity_edges(store, batch_size=10)
    assert ("A", "B", 2.0) in edges
    assert ("B", "C", 1.0) in edges
    assert set(nodes) == {"A", "B", "C"}      # includes isolated entities


class _FakeNebulaHighDegreeSource(_FakeNebula):
    """Source node 'A' has 4 outgoing edges; batch_size=2 forces 3 name pages
    and 3 GO chunks.  Every edge from 'A' must survive the paging."""

    _ALL_EDGES: ClassVar[list[tuple[str, str, float]]] = [
        ("A", "B", 1.0), ("A", "C", 1.0), ("A", "D", 1.0), ("A", "E", 1.0),
    ]

    def __init__(self):
        super().__init__(names=["A", "B", "C", "D", "E"], edges=self._ALL_EDGES)


def test_high_degree_source_no_edges_dropped():
    """Regression: all edges from a high-degree source must survive multi-page reads.

    With batch_size=2 and 4 edges from 'A', paging must not drop any of
    A->B..A->E.
    """
    edges, _nodes = extract_entity_edges(_FakeNebulaHighDegreeSource(), batch_size=2)
    targets = {tgt for src, tgt, _ in edges if src == "A"}
    assert targets == {"B", "C", "D", "E"}, (
        f"Expected all 4 targets of 'A', got: {targets}"
    )


# --- Seam routing: extract_entity_edges dispatches through
# build_graph_edge_export rather than owning any pagination logic itself. ---


class _FakeExport:
    """Records stream_names/stream_edges calls; canned return values."""

    def __init__(self, names, edges):
        self._names = names
        self._edges = edges
        self.stream_names_calls: list[dict] = []
        self.stream_edges_calls: list[dict] = []

    def stream_names(self, *, batch_size):
        self.stream_names_calls.append({"batch_size": batch_size})
        return self._names

    def stream_edges(self, *, batch_size, names=None):
        self.stream_edges_calls.append({"batch_size": batch_size, "names": names})
        return self._edges


def test_extract_entity_edges_routes_through_graph_edge_export_seam(monkeypatch):
    fake_names = ["A", "B", "C"]
    fake_edges = [("A", "B", 2.0), ("B", "C", 1.0)]
    fake_export = _FakeExport(fake_names, fake_edges)

    monkeypatch.setattr(
        community_leiden, "build_graph_edge_export", lambda store: fake_export,
    )

    result = extract_entity_edges(object(), batch_size=123)

    assert fake_export.stream_names_calls == [{"batch_size": 123}]
    assert fake_export.stream_edges_calls == [
        {"batch_size": 123, "names": fake_names},
    ]
    assert result == (fake_edges, fake_names)
