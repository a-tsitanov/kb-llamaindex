from __future__ import annotations

from src.graph import centrality_graph_ops as cgo


class _NebulaRecStore:
    def __init__(self, canned=None):
        self.calls: list[tuple[str, dict | None]] = []
        self._canned = list(canned or [])

    def structured_query(self, stmt, param_map=None):
        self.calls.append((stmt, param_map))
        assert param_map is None
        for substr, rows in self._canned:
            if substr in stmt:
                return rows
        return []


class _NebulaRaisingStore:
    def structured_query(self, stmt, param_map=None):
        raise RuntimeError("boom")


def test_nebula_top_central_reads_column():
    store = _NebulaRecStore(canned=[("e.`Entity`.pagerank > 0", [{"name": "Hub", "score": 0.34}])])
    result = cgo.NebulaCentralityGraphOps(store).top_central("pagerank", "Org", 10)
    assert result == [{"name": "Hub", "score": 0.34}]
    stmt = store.calls[0][0]
    assert "e.`Entity`.pagerank > 0" in stmt
    assert "e.`Entity`.label == \"Org\"" in stmt
    assert "ORDER BY score DESC LIMIT 10" in stmt


def test_nebula_top_central_rejects_unknown_metric():
    store = _NebulaRecStore()
    assert cgo.NebulaCentralityGraphOps(store).top_central("bogus", None, 5) == []
    assert store.calls == []  # never inlines an unknown column


def test_nebula_link_prediction_empty():
    store = _NebulaRecStore()
    assert cgo.NebulaCentralityGraphOps(store).link_prediction("A", 5) == []
    assert store.calls == []  # no LIKELY_LINK edge under nebula


def test_nebula_fail_soft():
    assert cgo.NebulaCentralityGraphOps(_NebulaRaisingStore()).top_central("pagerank", None, 5) == []


