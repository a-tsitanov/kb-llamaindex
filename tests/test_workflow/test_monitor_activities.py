"""Tests for detect_alerts activity (Arc 2 monitoring sweep)."""

from __future__ import annotations

import pytest

from src.analytics.contracts import MonitorIn
from src.graph.nebula_store import _q, entity_vid
from src.retrieval.date_filters import today_epoch_days

# Import the module under test — will fail until activities.py exists.
from src.workflow.monitor import activities as ma

# nebula has no MERGE: a new :Alert is an INSERT VERTEX (after a FETCH miss).
_ALERT_INSERT = "INSERT VERTEX `Alert` "

_WATCHED_LOOKUP = (
    "LOOKUP ON `Entity` WHERE `Entity`.watched == true "
    "YIELD id(vertex) AS vid, `Entity`.name AS name"
)
_RISK_LOOKUP = (
    "LOOKUP ON `Entity` WHERE `Entity`.watched == true "
    "YIELD `Entity`.name AS name, `Entity`.risk_score AS score, "
    "`Entity`.risk_score_prev AS prev"
)


def _go(vid, *, out):
    direction = "" if out else "REVERSELY"
    return (
        f"GO FROM {_q(vid)} OVER `RELATED` {direction} YIELD "
        f"{'dst' if out else 'src'}(edge) AS other, "
        "`RELATED`.rel_type AS rel, `RELATED`.created_at AS ca"
    )


def _fetch_names(vids):
    return (
        f"FETCH PROP ON `Entity` {', '.join(_q(v) for v in vids)} "
        "YIELD id(vertex) AS vid, `Entity`.name AS name"
    )


class _NebulaStmtStore:
    """nGQL fake keyed on the EXACT statements the nebula seam issues.

    Unknown statements answer ``[]`` (so every ``FETCH PROP ON Alert`` misses
    and the alert is INSERTed) and are still recorded in ``calls``.  Nebula
    binds no parameters, so a non-empty ``param_map`` is a test failure."""

    def __init__(self, responses=None):
        self._responses = dict(responses or {})
        self.calls: list[str] = []

    def structured_query(self, query, param_map=None):
        assert not param_map, f"nebula binds no params, got {param_map!r}"
        self.calls.append(query)
        return list(self._responses.get(query, []))


_A, _B = entity_vid("Alice"), entity_vid("Bob")


@pytest.mark.asyncio
async def test_detect_alerts_writes_both_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    """One edge row + one risk row → one alert of each kind."""
    # Alice (watched) -[KNOWS]-> Bob (not watched), created inside the window.
    store = _NebulaStmtStore({
        _WATCHED_LOOKUP: [{"vid": _A, "name": "Alice"}],
        _go(_A, out=True): [{"other": _B, "rel": "KNOWS", "ca": today_epoch_days()}],
        _fetch_names([_B]): [{"vid": _B, "name": "Bob"}],
        _RISK_LOOKUP: [{"name": "Alice", "score": 0.8, "prev": None}],
    })
    monkeypatch.setattr(ma, "_get_store", lambda: store)

    result = await ma.detect_alerts(MonitorIn(window_days=7, risk_rise_delta=0.1))

    assert result.new_connection_alerts == 1
    assert result.risk_rise_alerts == 1
    assert result.error == ""

    # Verify two Alert upserts (nebula: INSERT VERTEX) were recorded on the fake store.
    merge_calls = [stmt for stmt in store.calls if stmt.startswith(_ALERT_INSERT)]
    assert len(merge_calls) == 2, f"Expected 2 MERGE calls, got {len(merge_calls)}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "nebula behaves differently (src bug, not ported away): "
        "_read_watched_edges walks RELATED from EVERY watched anchor in both "
        "directions, so an edge whose endpoints are both watched is read twice "
        "(out from src + REVERSELY from tgt) and counted 4x, not 2x "
        "(upsert dedups the Alert vertices by key; the count does not). "
        "src/workflow/monitor/activities.py _read_watched_edges"
    ),
)
@pytest.mark.asyncio
async def test_detect_alerts_both_watched_emits_two_connection_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both endpoints are watched, two new_connection alerts are emitted."""

    # ONE edge Alice -[KNOWS]-> Bob, both endpoints watched.  A faithful
    # nebula graph answers it from BOTH anchors: outbound from Alice and
    # REVERSELY (inbound) from Bob.
    ca = today_epoch_days()
    store = _NebulaStmtStore({
        _WATCHED_LOOKUP: [{"vid": _A, "name": "Alice"}, {"vid": _B, "name": "Bob"}],
        _go(_A, out=True): [{"other": _B, "rel": "KNOWS", "ca": ca}],
        _go(_B, out=False): [{"other": _A, "rel": "KNOWS", "ca": ca}],
    })
    monkeypatch.setattr(ma, "_get_store", lambda: store)
    result = await ma.detect_alerts(MonitorIn(window_days=7, risk_rise_delta=0.1))
    assert result.new_connection_alerts == 2
    assert result.risk_rise_alerts == 0


@pytest.mark.asyncio
async def test_detect_alerts_failsoft(monkeypatch: pytest.MonkeyPatch) -> None:
    """If _get_store raises, detect_alerts must return error and not propagate."""

    def _boom() -> None:
        raise RuntimeError("neo4j gone")

    monkeypatch.setattr(ma, "_get_store", _boom)
    result = await ma.detect_alerts(MonitorIn())
    assert result.error != ""
    assert "neo4j gone" in result.error
    assert result.new_connection_alerts == 0
    assert result.risk_rise_alerts == 0


_BURST_ROW = {
    "entity": "Acme",
    "event_type": "lawsuit",
    "recent": 6,
    "baseline_rate": 1.0,
    "burst_score": 6.0,
}


def _is_known_stmt(stmt: str) -> bool:
    """The nebula reads/writes detect_alerts issues today besides burst: the
    watched-edge / risk LOOKUPs and the Alert upsert (FETCH/INSERT/UPDATE)."""
    return (
        stmt in (_WATCHED_LOOKUP, _RISK_LOOKUP)
        or stmt.startswith("FETCH PROP ON `Alert`")
        or stmt.startswith(_ALERT_INSERT)
        or stmt.startswith("UPDATE VERTEX ON `Alert`")
    )


class _NebulaBurstStore:
    """Nebula fake for the burst sub-check: no watched entities (edges/risk
    reads empty), every Alert FETCH misses (so an alert is INSERTed), and ANY
    other statement — i.e. a future nebula burst read, whatever its nGQL —
    answers the burst row.  Nebula binds no params."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def structured_query(self, query: str, param_map: dict | None = None) -> list[dict]:
        assert not param_map, f"nebula binds no params, got {param_map!r}"
        self.calls.append(query)
        if _is_known_stmt(query):
            return []
        return [dict(_BURST_ROW)]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "nebula gap: watched_only burst detection is not ported — "
        "_read_burst returns [] under nebula without issuing any query "
        "(src/workflow/monitor/activities.py _read_burst), so no burst alert "
        "is raised even when gated on.  The fake answers the burst row to ANY "
        "non-watched/risk/Alert statement, so porting the read flips this to XPASS"
    ),
)
@pytest.mark.asyncio
async def test_detect_alerts_burst_gated_on(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _NebulaBurstStore()
    monkeypatch.setattr(ma, "_get_store", lambda: store)
    monkeypatch.setattr(ma.settings.monitor, "burst_enabled", True, raising=False)
    result = await ma.detect_alerts(MonitorIn(window_days=7, risk_rise_delta=0.1))
    assert result.burst_alerts == 1
    inserts = [c for c in store.calls if c.startswith(_ALERT_INSERT)]
    assert len(inserts) == 1  # one burst alert upserted (nebula: INSERT VERTEX)


@pytest.mark.asyncio
async def test_detect_alerts_burst_gated_off(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _NebulaBurstStore()
    monkeypatch.setattr(ma, "_get_store", lambda: store)
    monkeypatch.setattr(ma.settings.monitor, "burst_enabled", False, raising=False)
    result = await ma.detect_alerts(MonitorIn())
    assert result.burst_alerts == 0
    # burst query never issued: only the watched/risk reads ran.
    assert [c for c in store.calls if not _is_known_stmt(c)] == []
