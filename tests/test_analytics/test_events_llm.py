"""E2 event read primitives — event_dossier + event_timeline + trending."""

from __future__ import annotations

import pytest

from src.analytics.primitives import events_llm
from tests.test_analytics.conftest import _NebulaStmtStore, _ngql_list


class _FakeOps:
    """Records (method, args); returns canned rows per method name."""

    def __init__(self, **returns):
        self.calls: dict[str, tuple] = {}
        self._returns = returns

    def event_core(self, name):
        self.calls["event_core"] = (name,)
        return self._returns.get("event_core", [])

    def event_actors(self, name, top_n):
        self.calls["event_actors"] = (name, top_n)
        return self._returns.get("event_actors", [])

    def event_timeline(self, entity, since_secs, top_n):
        self.calls["event_timeline"] = (entity, since_secs, top_n)
        return self._returns.get("event_timeline", [])


def _patch(monkeypatch, ops):
    monkeypatch.setattr(events_llm, "build_events_llm_graph_ops", lambda store: ops)


@pytest.mark.asyncio
async def test_event_dossier_assembles_core_and_actors(monkeypatch):
    ops = _FakeOps(
        event_core=[{"name": "Murder of Sergei", "event_type": "ASSASSINATION",
                     "event_ts_raw": 1234567890, "polarity": "negated"}],
        event_actors=[{"actor_name": "Ivan", "rel": "VICTIM"},
                      {"actor_name": "Boris", "rel": "SUSPECT"}],
    )
    _patch(monkeypatch, ops)
    res = await events_llm.event_dossier(object(), name="Murder of Sergei")
    row = res.rows[0]
    assert row["core"]["event_type"] == "ASSASSINATION"
    assert len(row["actors"]) == 2 and row["actors"][0]["actor_name"] == "Ivan"
    assert ops.calls["event_core"] == ("Murder of Sergei",)
    assert res.params["name"] == "Murder of Sergei"


@pytest.mark.asyncio
async def test_event_dossier_empty_core_short_circuits(monkeypatch):
    ops = _FakeOps(event_core=[])  # not an event
    _patch(monkeypatch, ops)
    res = await events_llm.event_dossier(object(), name="Nobody")
    assert res.rows == []
    assert "event_actors" not in ops.calls  # no actor fetch when core empty


@pytest.mark.asyncio
async def test_event_dossier_empty_actors(monkeypatch):
    ops = _FakeOps(
        event_core=[{"name": "Market Rally", "event_type": "MARKET_EVENT"}],
        event_actors=[],
    )
    _patch(monkeypatch, ops)
    res = await events_llm.event_dossier(object(), name="Market Rally")
    assert res.rows[0]["core"]["name"] == "Market Rally"
    assert res.rows[0]["actors"] == []


@pytest.mark.asyncio
async def test_event_dossier_top_n_clamped_into_seam(monkeypatch):
    ops = _FakeOps(event_core=[{"name": "X"}], event_actors=[])
    _patch(monkeypatch, ops)
    await events_llm.event_dossier(object(), name="X", top_n=5000)
    assert ops.calls["event_actors"][1] <= 200  # top_n clamp reaches the seam


@pytest.mark.asyncio
async def test_event_dossier_fail_soft_none_store():
    assert (await events_llm.event_dossier(None, name="X")).rows == []


@pytest.mark.asyncio
async def test_event_timeline_routes_and_threads_window(monkeypatch):
    monkeypatch.setattr(events_llm, "today_epoch_days", lambda: 19900)
    ops = _FakeOps(event_timeline=[
        {"name": "Event A", "event_type": "PROTEST", "event_start_epoch": 2000},
        {"name": "Event B", "event_type": "ARREST", "event_start_epoch": 1000},
    ])
    _patch(monkeypatch, ops)
    res = await events_llm.event_timeline(object(), entity="John", window_days=30)
    assert len(res.rows) == 2 and res.rows[0]["name"] == "Event A"
    entity, since_secs, _top_n = ops.calls["event_timeline"]
    assert entity == "John"
    assert since_secs == (19900 - 30) * 86400  # window -> since_secs threaded
    assert res.params["since_secs"] == (19900 - 30) * 86400


@pytest.mark.asyncio
async def test_event_timeline_no_window_passes_none(monkeypatch):
    ops = _FakeOps(event_timeline=[])
    _patch(monkeypatch, ops)
    await events_llm.event_timeline(object(), entity="Jane")
    assert ops.calls["event_timeline"][1] is None  # since_secs None when no window


@pytest.mark.asyncio
async def test_event_timeline_top_n_clamped(monkeypatch):
    ops = _FakeOps(event_timeline=[])
    _patch(monkeypatch, ops)
    await events_llm.event_timeline(object(), entity="test", top_n=5000)
    assert ops.calls["event_timeline"][2] <= 200


@pytest.mark.asyncio
async def test_event_timeline_fail_soft_none_store():
    assert (await events_llm.event_timeline(None, entity="X")).rows == []


# --- trending_events ------------------------------------------------------


@pytest.mark.asyncio
async def test_trending_events_windows_and_shape(monkeypatch):
    monkeypatch.setattr(events_llm, "today_epoch_days", lambda: 19900)
    # Acme took part in 6 lawsuit events inside the 7-day window and 4 in the
    # 4-window baseline before it: recent=6, baseline_rate=1.0, burst=6.0.
    since_baseline = 19900 - 7 * (4 + 1)
    events = [{"vid": f"ev{i}", "event_type": "lawsuit", "created_at": 19895}
              for i in range(6)]
    events += [{"vid": f"ev{i}", "event_type": "lawsuit", "created_at": 19870}
               for i in range(6, 10)]
    store = _NebulaStmtStore({
        "MATCH (e:`Entity`) WHERE e.`Entity`.label == 'EventOrAction' "
        f"AND e.`Entity`.created_at >= {since_baseline} "
        "RETURN id(e) AS vid, e.`Entity`.event_type AS event_type, "
        "e.`Entity`.created_at AS created_at;": events,
        f"GO FROM {_ngql_list(e['vid'] for e in events)} OVER `RELATED` "
        "WHERE `RELATED`.rel_type == 'PARTICIPATED_IN' "
        "AND `RELATED`.polarity != 'negated' "
        "YIELD src(edge) AS ev, dst(edge) AS p;": [
            {"ev": e["vid"], "p": "acme"} for e in events
        ],
        'FETCH PROP ON `Entity` "acme" YIELD id(vertex) AS vid, `Entity`.name AS name;': [
            {"vid": "acme", "name": "Acme"},
        ],
    })
    res = await events_llm.trending_events(store, window_days=7, baseline_windows=4)
    assert res.params["since_recent"] == 19900 - 7
    assert res.params["since_baseline"] == 19900 - 7 * (4 + 1)
    assert "burst_score" in res.cypher
    assert res.rows[0]["event_type"] == "lawsuit"


@pytest.mark.asyncio
async def test_trending_events_fail_soft_none_store():
    assert (await events_llm.trending_events(None)).rows == []
