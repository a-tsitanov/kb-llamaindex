from __future__ import annotations

from src.graph import communities_graph_ops as cgo
from src.graph.nebula_store import entity_vid


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


# --- Nebula: community_overview (MATCH by level) ------------------------


def test_nebula_community_overview_matches_by_level():
    store = _NebulaRecStore(canned=[
        ("Community`.level ==", [{"title": "Beta", "summary": "s", "member_count": 9}])
    ])
    result = cgo.NebulaCommunitiesGraphOps(store).community_overview(0, 20)
    assert result == [{"title": "Beta", "summary": "s", "member_count": 9}]
    stmt = store.calls[0][0]
    assert "c.`Community`.level == 0" in stmt
    assert "ORDER BY member_count DESC LIMIT 20" in stmt


# --- Nebula: entity_communities (GO + FETCH) ----------------------------


def test_nebula_entity_communities_go_then_fetch():
    vid = entity_vid("Ромашка")
    store = _NebulaRecStore(canned=[
        ("OVER `IN_COMMUNITY`", [{"cvid": "abc"}, {"cvid": "def"}]),
        ("FETCH PROP ON `Community`", [
            {"level": 0, "title": "Alpha", "summary": "sa"},
            {"level": 1, "title": "Beta", "summary": "sb"},
        ]),
    ])
    result = cgo.NebulaCommunitiesGraphOps(store).entity_communities("Ромашка")
    assert result == [
        {"level": 0, "title": "Alpha", "summary": "sa"},
        {"level": 1, "title": "Beta", "summary": "sb"},
    ]
    assert vid in store.calls[0][0]  # GO uses the entity VID
    assert '"abc"' in store.calls[1][0] and '"def"' in store.calls[1][0]  # FETCH the cvids


def test_nebula_entity_communities_empty_when_no_edges():
    store = _NebulaRecStore(canned=[("OVER `IN_COMMUNITY`", [])])
    assert cgo.NebulaCommunitiesGraphOps(store).entity_communities("Ghost") == []
    assert len(store.calls) == 1  # no FETCH when no edges


def test_nebula_fail_soft():
    assert cgo.NebulaCommunitiesGraphOps(_NebulaRaisingStore()).entity_communities("X") == []


