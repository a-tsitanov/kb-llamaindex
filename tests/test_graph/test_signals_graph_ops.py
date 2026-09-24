from __future__ import annotations

from src.graph import signals_graph_ops as sgo


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


class _NebulaRaisingStore:
    def structured_query(self, stmt, param_map=None):
        raise RuntimeError("boom")


# --- Nebula: blocked -> [] ----------------------------------------------


def test_nebula_risk_score_reads_materialized_column():
    store = _NebulaRecStore(canned=[("e.`Entity`.risk_score > 0", [
        {"name": "Shell", "score": 0.8, "band": "high", "components": "{}"}])])
    result = sgo.NebulaSignalsGraphOps(store).risk_score("Shell", "high", 20)
    assert result == [{"name": "Shell", "score": 0.8, "band": "high", "components": "{}"}]
    stmt = store.calls[0][0]
    assert "e.`Entity`.risk_score > 0" in stmt
    assert "e.`Entity`.name == \"Shell\"" in stmt
    assert "e.`Entity`.risk_band == \"high\"" in stmt
    assert "ORDER BY score DESC LIMIT 20" in stmt


def test_nebula_investigate_next_reads_risk_and_completeness():
    store = _NebulaRecStore(canned=[("risk_score > 0", [
        {"name": "X", "risk": 0.9, "completeness": 0.2}])])
    result = sgo.NebulaSignalsGraphOps(store).investigate_next(20)
    assert result == [{"name": "X", "risk": 0.9, "completeness": 0.2}]
    assert "ORDER BY risk DESC, completeness ASC LIMIT 20" in store.calls[0][0]


# --- Nebula: recommended_merges (Python grouping) -----------------------


def test_nebula_recommended_merges_groups():
    rows = [{"name": "Ромашка"}, {"name": " РОМАШКА "}, {"name": "Solo"}]
    store = _NebulaRecStore(canned=[("RETURN e.`Entity`.name AS name", rows)])
    result = sgo.NebulaSignalsGraphOps(store).recommended_merges(50)
    assert result == [{"key": "ромашка", "names": ["Ромашка", " РОМАШКА "], "count": 2}]


# --- Nebula: review_queue (shell classification in Python) --------------


def test_nebula_review_queue_flags_shell_orgs():
    rows = [
        {"name": "Shell", "neighbor_labels": ["INN", "PhoneNumber"]},  # all identifiers -> shell
        {"name": "Real", "neighbor_labels": ["Person"]},              # not shell
        {"name": "Empty", "neighbor_labels": []},                     # deg 0 -> not shell
    ]
    store = _NebulaRecStore(canned=[("collect(n.`Entity`.label)", rows)])
    result = sgo.NebulaSignalsGraphOps(store).review_queue(50)
    assert result == [{"name": "Shell", "degree": 2, "flag": "shell_signal"}]


# --- Nebula: circular_ownership (var-len + Python sort) -----------------


def test_nebula_circular_ownership_sorts_by_length():
    rows = [{"cycle": ["A", "B", "A"]}, {"cycle": ["X", "Y", "Z", "X"]}]
    store = _NebulaRecStore(canned=[("RELATED`*2..6", rows)])
    result = sgo.NebulaSignalsGraphOps(store).circular_ownership(20)
    # longer cycle first
    assert result == [{"cycle": ["X", "Y", "Z", "X"]}, {"cycle": ["A", "B", "A"]}]
    stmt = store.calls[0][0]
    assert "all(rel IN e WHERE rel.rel_type == 'OWNS')" in stmt


def test_nebula_fail_soft():
    assert sgo.NebulaSignalsGraphOps(_NebulaRaisingStore()).review_queue(20) == []


