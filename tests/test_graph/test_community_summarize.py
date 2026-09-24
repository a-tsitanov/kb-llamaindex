import asyncio

import src.workflow.search.activities.community as cact
from src.graph import community_summarize as cs
from src.graph.community_writeback import community_vid
from src.graph.nebula_store import entity_vid


class _RecNebula:
    """Fake nebula store: records nGQL; returns canned rows per substring."""
    def __init__(self, read_map=None):
        self.stmts = []
        self._read_map = read_map or {}
    def structured_query(self, query, param_map=None):
        assert not param_map, "nebula summarize must inline values"
        self.stmts.append(query)
        for needle, rows in self._read_map.items():
            if needle in query:
                return rows
        return []


def test_nebula_write_report_uses_update_vertex_no_report_vec():
    s = _RecNebula()
    wb = cs.NebulaCommunitySummarize(s)
    wb.write_report(community_id="7", level=0, report="R", title="T",
                    summary="S", report_vec=[0.1, 0.2])
    cvid = community_vid("7", 0)
    joined = "\n".join(s.stmts)
    assert f'UPDATE VERTEX ON `Community` "{cvid}"' in joined
    assert "INSERT VERTEX" not in joined              # partial update, not overwrite
    assert '"R"' in joined and '"T"' in joined and '"S"' in joined
    assert "summarized_at" in joined
    assert "report_vec" not in joined and "0.1" not in joined


def test_nebula_read_child_reports_filters_blank_and_sorts_by_member_count():
    ch_a, ch_b, ch_c = community_vid("a", 2), community_vid("b", 2), community_vid("c", 2)
    s = _RecNebula(read_map={
        'OVER `PARENT_OF`': [{"child": ch_a}, {"child": ch_b}, {"child": ch_c}],
        "FETCH PROP ON `Community`": [
            {"title": "A", "summary": "sa", "report": "ra", "mc": 5},
            {"title": "B", "summary": "sb", "report": "",   "mc": 9},   # blank report -> dropped
            {"title": "C", "summary": "sc", "report": "rc", "mc": 7},
        ],
    })
    wb = cs.NebulaCommunitySummarize(s)
    rows = wb.read_child_reports(community_id="7", level=1)
    assert rows == [{"title": "C", "summary": "sc"}, {"title": "A", "summary": "sa"}]  # mc desc, blank dropped


def test_nebula_read_member_context_intra_community_filter_and_cap():
    a, b, out = entity_vid("A"), entity_vid("B"), entity_vid("Outsider")
    s = _RecNebula(read_map={
        'OVER `IN_COMMUNITY` REVERSELY': [{"m": a}, {"m": b}],
        "FETCH PROP ON `Entity`": [
            # real nebula FETCH ... YIELD id(vertex) AS vid returns the vid per
            # row; props are keyed by it (order-independent), NOT positionally.
            {"vid": b, "name": "B", "description": "db"},
            {"vid": a, "name": "A", "description": "da"},
        ],
        'OVER `RELATED`': [
            {"s": a, "d": b, "rt": "KNOWS"},        # intra-community -> counts for A and B
            {"s": a, "d": out, "rt": "IGNORED"},    # edge to non-member -> excluded
        ],
    })
    wb = cs.NebulaCommunitySummarize(s)
    rows = wb.read_member_context(community_id="7", level=0)
    by_name = {r["name"]: r for r in rows}
    assert set(by_name) == {"A", "B"}
    assert rows == sorted(rows, key=lambda r: r["name"])   # ordered by name
    assert "KNOWS" in by_name["A"]["rel_types"] and "KNOWS" in by_name["B"]["rel_types"]
    assert "IGNORED" not in by_name["A"]["rel_types"]      # non-member edge excluded
    assert len(by_name["A"]["rel_types"]) <= 10


def test_gather_context_routes_member_read_through_seam(monkeypatch):
    captured = {}

    class _FakeSumm:
        def read_member_context(self, *, community_id, level):
            captured["member"] = (community_id, level)
            return [{"name": "a", "description": "d", "rel_types": ["R"]}]
        def read_child_reports(self, *, community_id, level):
            captured["child"] = (community_id, level)
            return []
        def write_report(self, **kw):
            captured["write"] = kw

    monkeypatch.setattr(cact, "build_community_summarize", lambda store: _FakeSumm())
    p = cact.SummarizeCommunityParams(community_id="7", level=0)
    body = asyncio.run(cact._gather_context(object(), p))
    assert captured["member"] == ("7", 0)
    assert isinstance(body, str) and body            # context string built from the rows


# Cypher-content-shape guards for the 3 constants, moved here with them from
# tests/test_workflow/test_search_community.py (their new canonical home).


