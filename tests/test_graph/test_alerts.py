"""Tests for src/graph/alerts.py — Alert store + watchlist helpers (nebula backend)."""

from src.graph.alert_store import alert_vid
from src.graph.alerts import alert_key, mark_watched, upsert_alert


class _Rec:
    """Nebula-shaped recorder: every statement answers ``[]`` (Alert absent)."""

    def __init__(self):
        self.calls = []

    def structured_query(self, stmt, param_map=None):
        self.calls.append((stmt, param_map or {}))
        return []


def test_alert_key_stable_and_dedup_friendly():
    assert alert_key("risk_rise", "Shell", "0.8") == alert_key("risk_rise", "Shell", "0.8")


def test_upsert_alert_param_map_carries_key():
    s = _Rec()
    upsert_alert(s, kind="risk_rise", entity="Shell", detail="0.8", created_at=19900)
    assert s.calls, "expected at least one store call"
    key = alert_key("risk_rise", "Shell", "0.8")
    insert = [c for c, _ in s.calls if "INSERT VERTEX `Alert`" in c]
    assert len(insert) == 1
    # the dedup key is both the vertex id and the stored alert_key prop
    assert alert_vid(key) in insert[0]
    assert f'"{key}"' in insert[0]


def test_mark_watched_passes_watched_flag():
    s = _Rec()
    mark_watched(s, ["X"], watched=False)
    stmt, _ = s.calls[0]
    assert "SET watched = false" in stmt


def test_mark_watched_empty_is_noop():
    s = _Rec()
    mark_watched(s, [])
    assert s.calls == []


# ── Fail-soft (never-raise) contract ─────────────────────────────────────────


class _Boom:
    def structured_query(self, *a, **kw):
        raise RuntimeError("neo4j down")


def test_upsert_alert_is_fail_soft():
    # must not raise — fail-soft per the off-loop contract
    assert upsert_alert(_Boom(), kind="x", entity="y", detail="z", created_at=0) is None


def test_mark_watched_is_fail_soft():
    # must not raise — fail-soft per the off-loop contract
    assert mark_watched(_Boom(), ["A", "B"]) is None
