from __future__ import annotations

from datetime import date, timedelta

from src.mcp import tools_server
from src.mcp.tools_server import (
    _period_bounds,
    _period_in_window,
    _polarity_evolution,
    _topic_trend,
)
from src.stats.align import GRANULARITIES


def test_topic_trend_granularities_are_not_a_parallel_copy():
    """`topic_trend` supports exactly day/week/month/quarter/year, which
    is `GRANULARITIES` exactly.  The validation set must be the same
    object `src.stats.align` defines, not a hand-copied tuple that can
    silently drift out of sync with it."""
    assert tools_server.GRANULARITIES is GRANULARITIES


async def test_topic_trend_rejects_empty_topic():
    out = await _topic_trend(None, "  ", "month", None, None)
    assert "error" in out


async def test_topic_trend_rejects_bad_granularity():
    out = await _topic_trend(None, "инфляция", "fortnight", None, None)
    assert "error" in out


async def test_topic_trend_rejects_bad_dates():
    out = await _topic_trend(None, "инфляция", "month", "2026/01/01", None)
    assert "error" in out
    assert "YYYY-MM-DD" in out["error"]


async def test_polarity_evolution_requires_a_name_or_rel_type():
    out = await _polarity_evolution(None, None, None)
    assert "error" in out


def test_period_bounds_per_granularity():
    assert _period_bounds("2026", "year") == (date(2026, 1, 1), date(2026, 12, 31))
    assert _period_bounds("2026-Q2", "quarter") == (
        date(2026, 4, 1), date(2026, 6, 30),
    )
    assert _period_bounds("2026-02", "month") == (
        date(2026, 2, 1), date(2026, 2, 28),
    )
    assert _period_bounds("2024-02", "month") == (
        date(2024, 2, 1), date(2024, 2, 29),
    )
    assert _period_bounds("2026-05-04", "week") == (
        date(2026, 5, 4), date(2026, 5, 10),
    )
    assert _period_bounds("2026-05-04", "day") == (
        date(2026, 5, 4), date(2026, 5, 4),
    )


def test_period_in_window_keeps_quarters_that_overlap():
    """The bug this replaces: 'Q' sorts after every digit, so a prefix
    compare admitted every quarter under `since` and dropped every
    quarter under `until`."""
    keep = [
        q for q in ("2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4")
        if _period_in_window(q, "quarter", "2026-04-01", "2026-09-30")
    ]
    assert keep == ["2026-Q2", "2026-Q3"]


def test_period_in_window_overlap_not_containment():
    """A bucket straddling the boundary still carries mentions from
    inside the window; dropping it would silently lose them."""
    assert _period_in_window("2026-Q2", "quarter", "2026-06-25", None)
    assert _period_in_window("2026", "year", None, "2026-01-02")


def test_period_in_window_keeps_a_bucket_ending_exactly_on_since():
    """The boundary day itself is inside the window.

    `end < since` must drop; `end == since` must keep — a bucket whose
    last day IS `since` contains one day of the requested window, and
    losing it loses those mentions.  Swapping `<` for `<=` here survives
    every other window test, so this case has to be pinned explicitly.
    """
    # January's bucket ends 2026-01-31; a window opening that same day
    # still overlaps it by exactly one day.
    assert _period_in_window("2026-01", "month", "2026-01-31", None)
    # One day later there is no overlap left at all.
    assert not _period_in_window("2026-01", "month", "2026-02-01", None)


def test_period_in_window_keeps_a_bucket_starting_exactly_on_until():
    """Mirror case: `start > until` must drop, `start == until` keep."""
    # February's bucket starts 2026-02-01; a window closing that day
    # overlaps it by exactly one day.
    assert _period_in_window("2026-02", "month", None, "2026-02-01")
    # A day earlier, the bucket is entirely outside.
    assert not _period_in_window("2026-02", "month", None, "2026-01-31")


def test_period_in_window_exact_boundaries_per_granularity():
    """Same two boundaries across every bucket shape, since each one
    computes its bounds by a different branch of `_period_bounds`."""
    for period, granularity, last_day, first_day in (
        ("2026", "year", "2026-12-31", "2026-01-01"),
        ("2026-Q2", "quarter", "2026-06-30", "2026-04-01"),
        ("2026-05", "month", "2026-05-31", "2026-05-01"),
        ("2026-05-04", "week", "2026-05-10", "2026-05-04"),
        ("2026-05-04", "day", "2026-05-04", "2026-05-04"),
    ):
        assert _period_in_window(period, granularity, last_day, None), period
        assert _period_in_window(period, granularity, None, first_day), period
        after = date.fromisoformat(last_day) + timedelta(days=1)
        before = date.fromisoformat(first_day) - timedelta(days=1)
        assert not _period_in_window(
            period, granularity, after.isoformat(), None,
        ), period
        assert not _period_in_window(
            period, granularity, None, before.isoformat(),
        ), period


def test_period_in_window_open_bounds():
    assert _period_in_window("2026-05", "month", None, None)
    assert not _period_in_window("2026-05", "month", "2026-07-01", None)
    assert not _period_in_window("2026-05", "month", None, "2026-04-30")


async def test_topic_trend_errors_instead_of_returning_a_silent_zero_on_nebula():
    """Under the production backend the primitive's parameterised query
    fail-softs to `[]`, which reads as "never mentioned".  A missing
    answer is honest; a silent zero is not."""
    out = await _topic_trend(object(), "инфляция", "month", None, None)
    assert "error" in out
    assert "nebula" in out["error"]
    assert "rows" not in out


async def test_polarity_evolution_is_not_guarded_on_nebula():
    """It does NOT share topic_trend's fault: it goes through
    `build_dynamics_graph_ops`, whose nebula implementation inlines its
    literals into nGQL and never passes a `param_map`.  Guarding it too
    would suppress a working tool."""
    async def fake(store, *, name, rel_type):
        from src.analytics.catalog import PrimitiveResult
        return PrimitiveResult(cypher="", params={}, rows=[
            {"period": "2026-01", "polarity": "affirmed", "n": 4},
        ])

    out = await _polarity_evolution(object(), "инфляция", None, _fn=fake)
    assert "error" not in out
    assert out["rows"] == [{"period": "2026-01", "polarity": "affirmed", "n": 4}]


async def test_topic_trend_argument_checks_run_before_the_store_check():
    """With a real store present, a bad argument must still be reported
    as a bad argument — the previous tests passed a None store, so they
    could not tell the two branches apart."""
    out = await _topic_trend(object(), "  ", "month", None, None)
    assert "topic" in out["error"]
    out = await _topic_trend(object(), "инфляция", "fortnight", None, None)
    assert "granularity" in out["error"]
    out = await _polarity_evolution(object(), None, None)
    assert "rel_type" in out["error"]
