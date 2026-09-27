"""Tests for materialize_activities (centrality + link prediction + risk)."""

from __future__ import annotations

import json
import re

import pytest

import src.analytics.centrality_compute as cc
from src.analytics.contracts import CentralityIn, LinkPredictionIn, RiskIn
from src.analytics.ids import ID_TYPES
from src.graph.nebula_store import entity_vid
from src.retrieval.date_filters import today_epoch_days
from src.workflow.analytics import materialize_activities as ma


class _NebulaStmtStore:
    """nGQL fake keyed on the EXACT statements the nebula seam issues.

    ``responses`` maps a full statement to its canned rows; an unknown
    statement answers ``[]`` and is still recorded in ``calls``.  Nebula
    binds no parameters, so a non-empty ``param_map`` is a test failure."""

    def __init__(self, responses=None):
        self._responses = dict(responses or {})
        self.calls: list[str] = []

    def structured_query(self, query, param_map=None):
        assert not param_map, f"nebula binds no params, got {param_map!r}"
        self.calls.append(query)
        return list(self._responses.get(query, []))


class _Store:
    def __init__(self):
        self.calls = []

    def structured_query(self, cypher, param_map=None):
        self.calls.append(cypher)
        # GDS stream → 1 row; everything else → []
        return [{"name": "A", "score": 0.5}] if "gds." in cypher and "stream" in cypher else []


@pytest.mark.asyncio
async def test_materialize_centrality_runs_each_metric(monkeypatch):
    # nebula computes every metric in-worker from ONE compute_all (igraph over
    # the edge export) and writes one UPDATE VERTEX per scored entity; each
    # metric scores one (distinct) entity here.
    computed: list[int] = []

    def _fake_compute_all(store, **_kw):
        computed.append(1)
        return {"pagerank": {"A": 0.5}, "betweenness": {"B": 0.5}, "eigenvector": {}}

    monkeypatch.setattr(cc, "compute_all", _fake_compute_all)
    store = _NebulaStmtStore()
    monkeypatch.setattr(ma, "_get_store", lambda graph: store)
    res = await ma.materialize_centrality(CentralityIn(metrics=["pagerank", "betweenness"]))
    assert res.written == 2 and res.error == ""  # 1 row each
    assert computed == [1]
    assert store.calls == [
        f'UPDATE VERTEX ON `Entity` "{entity_vid("A")}" SET pagerank = 0.5;\n'
        f'UPDATE VERTEX ON `Entity` "{entity_vid("B")}" SET betweenness = 0.5;'
    ]


@pytest.mark.asyncio
async def test_materialize_centrality_failsoft(monkeypatch):
    def _boom(graph):
        raise RuntimeError("neo4j down")

    monkeypatch.setattr(ma, "_get_store", _boom)
    res = await ma.materialize_centrality(CentralityIn())
    assert res.written == 0 and "neo4j down" in res.error


@pytest.mark.asyncio
async def test_materialize_link_prediction_runs(monkeypatch):
    monkeypatch.setattr(ma, "_get_store", lambda graph: _Store())
    res = await ma.materialize_link_prediction(LinkPredictionIn())
    # Documented no-op on NebulaGraph (no link-prediction port): nothing written.
    assert res.error == ""
    assert res.written == 0


# ---------------------------------------------------------------------------
# Task 6: materialize_risk
# ---------------------------------------------------------------------------


class _RiskStore:
    def __init__(self, rows):
        self._rows, self.writes = rows, []

    def structured_query(self, cypher, param_map=None):
        if cypher.strip().startswith("UNWIND"):  # write-back
            self.writes.append((cypher, param_map))
            return []
        return self._rows  # the component-gather read


_ID_LIST = "[" + ", ".join(f'"{t}"' for t in ID_TYPES) + "]"
_RISK_ENTS_NGQL = (
    f"MATCH (e:`Entity`) WHERE e.`Entity`.label NOT IN {_ID_LIST} "
    "RETURN e.`Entity`.name AS name, e.`Entity`.betweenness AS betweenness;"
)
_RISK_EDGES_NGQL = (
    f"MATCH (e:`Entity`)-[r:`RELATED`]-(n:`Entity`) WHERE e.`Entity`.label NOT IN {_ID_LIST} "
    "RETURN e.`Entity`.name AS name, n.`Entity`.label AS nlabel, "
    "r.polarity AS polarity, r.created_at AS created_at;"
)
_RISK_UPDATE_RE = re.compile(
    r'^UPDATE VERTEX ON `Entity` "(?P<vid>[0-9a-f]+)" '
    r"SET risk_score_prev = risk_score, risk_score = (?P<score>[0-9.eE+-]+), "
    r'risk_band = (?P<band>"(?:[^"\\]|\\.)*"), '
    r'risk_components = (?P<components>"(?:[^"\\]|\\.)*");$'
)


@pytest.mark.asyncio
async def test_materialize_risk_writes_scores(monkeypatch):
    # nebula gathers entities + their RELATED edges and aggregates per entity
    # in Python: 3 edges, all to identifier entities, 2 contested, all recent
    # → betweenness 1.0, id_links 3, deg 3, contested 2, recent 3.
    now = today_epoch_days()
    edges = [
        {"name": "Shell", "nlabel": ID_TYPES[0], "polarity": "negated", "created_at": now},
        {"name": "Shell", "nlabel": ID_TYPES[1], "polarity": "uncertain", "created_at": now},
        {"name": "Shell", "nlabel": ID_TYPES[2], "polarity": "asserted", "created_at": now},
    ]
    store = _NebulaStmtStore({
        _RISK_ENTS_NGQL: [{"name": "Shell", "betweenness": 1.0}],
        _RISK_EDGES_NGQL: edges,
    })
    monkeypatch.setattr(ma, "_get_store", lambda graph: store)
    res = await ma.materialize_risk(RiskIn())
    assert res.written == 1 and res.error == ""
    writes = [c for c in store.calls if c.startswith("UPDATE VERTEX")]
    write_stmt = writes[0]
    assert "SET risk_score_prev = risk_score, risk_score = " in write_stmt
    assert "risk_band = " in write_stmt
    m = _RISK_UPDATE_RE.match(write_stmt)
    assert m is not None and m["vid"] == entity_vid("Shell")
    rowarg = {
        "score": float(m["score"]),
        "band": json.loads(m["band"]),
        "components": json.loads(m["components"]),
    }
    assert 0.0 <= rowarg["score"] <= 1.0 and rowarg["band"] in {"low", "medium", "high"}
    json.loads(rowarg["components"])  # components serialized as JSON


@pytest.mark.asyncio
async def test_materialize_risk_empty_returns_zero(monkeypatch):
    store = _RiskStore([])
    monkeypatch.setattr(ma, "_get_store", lambda graph: store)
    res = await ma.materialize_risk(RiskIn())
    assert res.written == 0 and res.error == ""


@pytest.mark.asyncio
async def test_materialize_risk_failsoft(monkeypatch):
    def _boom(graph):
        raise RuntimeError("risk db down")

    monkeypatch.setattr(ma, "_get_store", _boom)
    res = await ma.materialize_risk(RiskIn())
    assert res.written == 0 and "risk db down" in res.error


# Task 8's risk_score_prev-before-overwrite invariant is covered directly on
# the live nebula statement by test_materialize_risk_writes_scores above
# (regex-matches "SET risk_score_prev = risk_score, risk_score = ..." in
# write order) — the neo4j-only _RISK_WRITE Cypher constant this used to
# check is gone with neo4j.
