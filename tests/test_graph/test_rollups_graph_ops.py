from __future__ import annotations

from src.graph import rollups_graph_ops as rgo


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


def test_nebula_amount_edges_matches_amount_label():
    store = _NebulaRecStore(canned=[("label == 'Amount'", [{"counterparty": "A", "amount": "500"}])])
    result = rgo.NebulaRollupsGraphOps(store).amount_edges(None)
    assert result == [{"counterparty": "A", "amount": "500"}]
    stmt = store.calls[0][0]
    assert "a.`Entity`.label == 'Amount'" in stmt
    assert "e.`Entity`.name ==" not in stmt  # no cp filter


def test_nebula_amount_edges_adds_cp_filter():
    store = _NebulaRecStore()
    rgo.NebulaRollupsGraphOps(store).amount_edges("Acme")
    assert "e.`Entity`.name == \"Acme\"" in store.calls[0][0]


def test_nebula_fail_soft():
    class _NebulaRaisingStore:
        def structured_query(self, stmt, param_map=None):
            raise RuntimeError("boom")

    assert rgo.NebulaRollupsGraphOps(_NebulaRaisingStore()).amount_edges(None) == []


