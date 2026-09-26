from __future__ import annotations

from src.graph import events_llm_graph_ops as ego
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


# --- Nebula: event_core (FETCH by vid + EventOrAction filter) -----------


def test_nebula_event_core_fetches_event_fields():
    vid = entity_vid("Murder")
    store = _NebulaRecStore(canned=[("FETCH PROP ON `Entity`", [
        {"vid": vid, "name": "Murder", "label": "EventOrAction", "event_type": "ASSASSINATION",
         "event_ts_raw": "2026", "event_start_epoch": 100, "event_end_epoch": 0,
         "event_ts_precision": "year"},
    ])])
    result = ego.NebulaEventsLlmGraphOps(store).event_core("Murder")
    assert result == [{
        "name": "Murder", "event_type": "ASSASSINATION", "event_ts_raw": "2026",
        "event_start_epoch": 100, "event_end_epoch": 0, "event_ts_precision": "year",
        "polarity": None,
    }]
    assert vid in store.calls[0][0]


def test_nebula_event_core_empty_when_not_event():
    vid = entity_vid("Bob")
    store = _NebulaRecStore(canned=[("FETCH PROP ON `Entity`", [
        {"vid": vid, "name": "Bob", "label": "Person", "event_type": ""},
    ])])
    # label != EventOrAction -> filtered out -> []
    assert ego.NebulaEventsLlmGraphOps(store).event_core("Bob") == []


# --- Nebula: event_actors (GO + FETCH names) ----------------------------


def test_nebula_event_actors_go_then_fetch_names():
    ev_vid = entity_vid("Murder")
    ivan = entity_vid("Ivan")
    store = _NebulaRecStore(canned=[
        # 1st call: _fetch_events confirms the anchor is an event
        ("YIELD id(vertex) AS vid, `Entity`.name AS name, `Entity`.label AS label",
         [{"vid": ev_vid, "name": "Murder", "label": "EventOrAction"}]),
        # GO neighbours
        ("OVER `RELATED` BIDIRECT YIELD", [{"nbr": ivan, "s": ev_vid, "rel": "VICTIM"}]),
        # _fetch_names
        ("`Entity`.name AS name;", [{"vid": ivan, "name": "Ivan"}]),
    ])
    result = ego.NebulaEventsLlmGraphOps(store).event_actors("Murder", 25)
    assert result == [{"actor_name": "Ivan", "rel": "VICTIM"}]


# --- Nebula: event_timeline (GO PARTICIPATED_IN + Python window/sort) ----


def test_nebula_event_timeline_orders_untimed_last_and_filters_window():
    john = entity_vid("John")
    ev_a, ev_b, ev_c = entity_vid("A"), entity_vid("B"), entity_vid("C")
    store = _NebulaRecStore(canned=[
        ("rel_type == 'PARTICIPATED_IN'",
         [{"d": ev_a, "s": john}, {"d": ev_b, "s": john}, {"d": ev_c, "s": john}]),
        ("FETCH PROP ON `Entity`", [
            {"vid": ev_a, "name": "A", "label": "EventOrAction", "event_start_epoch": 2000},
            {"vid": ev_b, "name": "B", "label": "EventOrAction", "event_start_epoch": 0},   # untimed
            {"vid": ev_c, "name": "C", "label": "EventOrAction", "event_start_epoch": 1000},  # < since
        ]),
    ])
    result = ego.NebulaEventsLlmGraphOps(store).event_timeline("John", 1500, 50)
    names = [r["name"] for r in result]
    # C (1000) dropped by window; A (2000) then B (untimed, last)
    assert names == ["A", "B"]


def test_nebula_fail_soft():
    assert ego.NebulaEventsLlmGraphOps(_NebulaRaisingStore()).event_core("E") == []


# --- trending_events -----------------------------------------------------


def test_nebula_trending_computes_burst_in_python():
    p = entity_vid("Acme")
    e_recent, e_recent2, e_old = entity_vid("E1"), entity_vid("E2"), entity_vid("E0")
    store = _NebulaRecStore(canned=[
        # event scan (label + created_at >= since_baseline)
        ("label == 'EventOrAction'", [
            {"vid": e_recent, "event_type": "lawsuit", "created_at": 100},
            {"vid": e_recent2, "event_type": "lawsuit", "created_at": 100},
            {"vid": e_old, "event_type": "lawsuit", "created_at": 50},
        ]),
        # PARTICIPATED_IN pairs (event -> participant)
        ("rel_type == 'PARTICIPATED_IN'", [
            {"ev": e_recent, "p": p}, {"ev": e_recent2, "p": p}, {"ev": e_old, "p": p},
        ]),
        # participant name fetch
        ("`Entity`.name AS name;", [{"vid": p, "name": "Acme"}]),
    ])
    # since_recent=90 -> E1,E2 recent (2), E0 baseline (1); baseline_windows=1 ->
    # baseline_rate=1.0; burst=2/1=2.0; min_count=2, ratio=1.0 -> passes.
    result = ego.NebulaEventsLlmGraphOps(store).trending_events(90, 0, 1, 2, 1.0, 20)
    assert result == [{"entity": "Acme", "event_type": "lawsuit", "recent": 2,
                       "baseline_rate": 1.0, "burst_score": 2.0}]


def test_nebula_trending_counts_distinct_events():
    # A doubled PARTICIPATED_IN edge (same event -> same participant) must
    # not double-count that event for the (entity, event_type) pair.
    p = entity_vid("Acme")
    e1, e2 = entity_vid("E1"), entity_vid("E2")
    store = _NebulaRecStore(canned=[
        ("label == 'EventOrAction'", [
            {"vid": e1, "event_type": "lawsuit", "created_at": 100},
            {"vid": e2, "event_type": "lawsuit", "created_at": 100},
        ]),
        ("rel_type == 'PARTICIPATED_IN'", [
            {"ev": e1, "p": p}, {"ev": e1, "p": p}, {"ev": e2, "p": p},
        ]),
        ("`Entity`.name AS name;", [{"vid": p, "name": "Acme"}]),
    ])
    result = ego.NebulaEventsLlmGraphOps(store).trending_events(90, 0, 1, 2, 1.0, 20)
    assert [r["recent"] for r in result] == [2]


def test_nebula_trending_filters_below_min_count():
    p = entity_vid("Acme")
    e1 = entity_vid("E1")
    store = _NebulaRecStore(canned=[
        ("label == 'EventOrAction'", [{"vid": e1, "event_type": "lawsuit", "created_at": 100}]),
        ("rel_type == 'PARTICIPATED_IN'", [{"ev": e1, "p": p}]),
        ("`Entity`.name AS name;", [{"vid": p, "name": "Acme"}]),
    ])
    # 1 recent event but min_count=2 -> filtered out
    assert ego.NebulaEventsLlmGraphOps(store).trending_events(90, 0, 1, 2, 1.0, 20) == []


def test_nebula_trending_empty_when_no_events():
    store = _NebulaRecStore()  # scan returns []
    assert ego.NebulaEventsLlmGraphOps(store).trending_events(90, 0, 1, 2, 1.0, 20) == []


