from __future__ import annotations

from src.graph import dynamics_graph_ops as dgo


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


# --- Nebula: relationship_timeline (substr, name-anchored) --------------


def test_nebula_relationship_timeline_substr_and_rel_filter():
    store = _NebulaRecStore(canned=[
        ("substr(r.valid_from,0,7)", [{"period": "2026-01", "rel": "OWNS", "name": "B", "polarity": "affirmed"}])
    ])
    result = dgo.NebulaDynamicsGraphOps(store).relationship_timeline("A", "OWNS")
    assert result == [{"period": "2026-01", "rel": "OWNS", "name": "B", "polarity": "affirmed"}]
    stmt = store.calls[0][0]
    assert "e.`Entity`.name == \"A\"" in stmt
    assert "r.valid_from != ''" in stmt
    assert "r.rel_type == \"OWNS\"" in stmt
    assert "substr(r.valid_from,0,7) AS period" in stmt
    assert "ORDER BY period" in stmt


def test_nebula_polarity_evolution_optional_filters():
    store = _NebulaRecStore()
    dgo.NebulaDynamicsGraphOps(store).polarity_evolution(None, None)
    stmt = store.calls[0][0]
    assert "r.valid_from != ''" in stmt
    assert "e.`Entity`.name ==" not in stmt  # no name filter
    assert "count(*) AS n ORDER BY period" in stmt


# --- Nebula: whats_changed (window match + Python classify) -------------


def test_nebula_whats_changed_classifies_appeared_and_ended():
    rows = [
        {"name": "A", "rel": "OWNS", "other": "B", "polarity": "aff",
         "valid_from": "2026-03-01", "valid_to": ""},                     # appeared
        {"name": "C", "rel": "OWNS", "other": "D", "polarity": "aff",
         "valid_from": "2025-01-01", "valid_to": "2026-05-01"},           # ended (vf out, vt in)
    ]
    store = _NebulaRecStore(canned=[("r.rel_type != 'LIKELY_LINK'", rows)])
    result = dgo.NebulaDynamicsGraphOps(store).whats_changed(
        "2026-01", "2026-12", None, 20000, 20300, 50
    )
    assert result == [
        {"name": "C", "rel": "OWNS", "other": "D", "polarity": "aff",
         "valid_from": "2025-01-01", "valid_to": "2026-05-01", "created_at": None, "change": "ended"},
        {"name": "A", "rel": "OWNS", "other": "B", "polarity": "aff",
         "valid_from": "2026-03-01", "valid_to": "", "created_at": None, "change": "appeared"},
    ]
    stmt = store.calls[0][0]
    assert "r.rel_type != 'LIKELY_LINK'" in stmt
    assert "r.valid_from >= \"2026-01\"" in stmt


def test_nebula_whats_changed_entity_filter_and_limit():
    store = _NebulaRecStore()
    dgo.NebulaDynamicsGraphOps(store).whats_changed("2026-01", "2026-12", "Acme", None, None, 5)
    assert "e.`Entity`.name == \"Acme\"" in store.calls[0][0]


def test_nebula_fail_soft():
    assert dgo.NebulaDynamicsGraphOps(_NebulaRaisingStore()).whats_changed(
        "2026-01", "2026-12", None, None, None, 50
    ) == []


