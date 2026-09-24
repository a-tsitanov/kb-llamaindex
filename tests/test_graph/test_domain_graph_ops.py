from __future__ import annotations

from src.graph import domain_graph_ops as dgo


class _NebulaRecStore:
    """Returns canned rows keyed by first matching substring of the statement."""

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


class _NebulaRaisingStore:
    def structured_query(self, stmt, param_map=None):
        raise RuntimeError("boom")


# --- Nebula: issue_resolution_stats (two queries + Python) --------------


def test_nebula_issue_stats_computes_total_and_unresolved():
    store = _NebulaRecStore(canned=[
        ("RETURN count(*) AS total", [{"total": 5}]),
        ("RESOLVED_BY", [{"name": "Iss1"}, {"name": "Iss2"}, {"name": "Iss1"}]),
    ])
    result = dgo.NebulaDomainGraphOps(store).issue_resolution_stats()
    # 5 issues total, 2 distinct resolved -> unresolved = 3
    assert result == [{"total": 5, "unresolved": 3}]
    assert "label == 'Issue'" in store.calls[0][0]
    assert "rr.rel_type == 'RESOLVED_BY'" in store.calls[1][0]
    assert "r.`Entity`.label == 'Resolution'" in store.calls[1][0]


def test_nebula_issue_stats_clamps_unresolved_nonnegative():
    store = _NebulaRecStore(canned=[
        ("RETURN count(*) AS total", [{"total": 1}]),
        ("RESOLVED_BY", [{"name": "A"}, {"name": "B"}]),  # more resolved than total
    ])
    assert dgo.NebulaDomainGraphOps(store).issue_resolution_stats() == [{"total": 1, "unresolved": 0}]


# --- Nebula: communication_stats (undirected dedup MATCH) ---------------


def test_nebula_comms_dedup_and_rel_filter():
    store = _NebulaRecStore(canned=[
        ("interactions", [{"a": "A", "b": "B", "rel": "CONTACT", "interactions": 3}])
    ])
    result = dgo.NebulaDomainGraphOps(store).communication_stats(None, 20)
    assert result == [{"a": "A", "b": "B", "rel": "CONTACT", "interactions": 3}]
    stmt = store.calls[0][0]
    assert "r.rel_type IN ['CONTACT', 'RESPONDED_TO']" in stmt
    assert "a.`Entity`.name < b.`Entity`.name" in stmt
    assert "ORDER BY interactions DESC LIMIT 20" in stmt
    assert "name ==" not in stmt  # no name filter when None


def test_nebula_comms_adds_name_filter():
    store = _NebulaRecStore()
    dgo.NebulaDomainGraphOps(store).communication_stats("Alice", 5)
    stmt = store.calls[0][0]
    assert "a.`Entity`.name == \"Alice\" OR b.`Entity`.name == \"Alice\"" in stmt
    assert "LIMIT 5" in stmt


def test_nebula_fail_soft():
    assert dgo.NebulaDomainGraphOps(_NebulaRaisingStore()).communication_stats(None, 20) == []


