"""Отчёт по каналу ``channel_report``: фейковое соединение с очередью наборов.

Порядок наборов: слаги, доверие, судьба/происхождение, покрытие, перепосты,
вытеснения, отдача графу — тот же, в котором их читает отчёт.
"""

from __future__ import annotations

import datetime as dt
from contextlib import asynccontextmanager
from typing import Any

from src.intake.sources import report as report_mod
from src.intake.sources.report import channel_report
from src.tenancy.context import default_graph_context


class _Cur:
    def __init__(self, results):
        self.sql: list[tuple[str, Any]] = []
        self._results = list(results)
        self._cur: list[dict[str, Any]] = []

    async def execute(self, q, params=None):
        self.sql.append((str(q), params))
        self._cur = self._results.pop(0) if self._results else []

    async def fetchall(self):
        return self._cur

    async def fetchone(self):
        return self._cur[0] if self._cur else None


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self, row_factory=None):
        @asynccontextmanager
        async def cm():
            yield self.cur

        return cm()


def _sets(**over):
    s: dict[str, list[dict[str, Any]]] = {
        "slugs": [{"slug": "@new_name"}, {"slug": "old_name"}],
        "trust": [{"trust": 0.7}],
        "fate": [
            {"origin": "owner", "status": "completed", "n": 6},
            {"origin": "owner", "status": "failed", "n": 2},
            {"origin": "repost", "status": "duplicate", "n": 2},
        ],
        "cov": [{"earliest": dt.date(2026, 9, 1), "latest": dt.date(2026, 10, 1),
                 "without_doc_date": 1}],
        "reposts": [{"channel": "big", "n": 2}],
        "sup": [{"displaced_others": 1, "displaced_by_others": 3}],
        "yld": [{"entities": 40, "new_edges": 4}],
    }
    s.update(over)
    return list(s.values())


def _patch(monkeypatch, results):
    cur = _Cur(results)

    @asynccontextmanager
    async def gc(graph, timeout=None):
        yield _Conn(cur)

    monkeypatch.setattr(report_mod, "graph_connection", gc)
    return cur


async def test_documents_gathered_by_all_slugs_both_forms(monkeypatch) -> None:
    cur = _patch(monkeypatch, _sets())
    await channel_report(default_graph_context(), 42)
    slugs_param = cur.sql[2][1][0]
    assert {"new_name", "@new_name", "old_name"} <= set(slugs_param)


async def test_origin_separates_owner_from_repost(monkeypatch) -> None:
    _patch(monkeypatch, _sets())
    out = await channel_report(default_graph_context(), 42)
    assert out["origin"] == {"owner": 8, "repost": 2}
    assert out["volume"] == {"rows": 10, "documents": 8}
    assert out["fate"] == {"completed": 6, "failed": 2}


async def test_reposts_of_lists_body_owners(monkeypatch) -> None:
    _patch(monkeypatch, _sets())
    out = await channel_report(default_graph_context(), 42)
    assert out["reposts_of"] == [{"channel": "big", "count": 2}]


async def test_contradictions_count_both_directions(monkeypatch) -> None:
    _patch(monkeypatch, _sets())
    out = await channel_report(default_graph_context(), 42)
    assert out["contradictions"] == {
        "displaced_others": 1, "displaced_by_others": 3, "total": 4,
    }


async def test_graph_yield_marks_first_seen_only(monkeypatch) -> None:
    _patch(monkeypatch, _sets())
    y = (await channel_report(default_graph_context(), 42))["graph_yield"]
    assert y["entities_per_doc"] == 5.0
    assert y["new_edges_per_doc"] == 0.5
    assert y["first_seen_only"] is True


async def test_trust_keeps_set_and_measured_apart(monkeypatch) -> None:
    _patch(monkeypatch, _sets())
    t = (await channel_report(default_graph_context(), 42))["trust"]
    assert t["set"] == 0.7
    assert t["measured"] == {"repost_share": 0.2, "displacement_rate": 0.5}


async def test_unset_trust_stays_none(monkeypatch) -> None:
    _patch(monkeypatch, _sets(trust=[{"trust": None}]))
    assert (await channel_report(default_graph_context(), 42))["trust"]["set"] is None


async def test_empty_channel_gives_zeros(monkeypatch) -> None:
    _patch(monkeypatch, [[], [], [], [], [], [], []])
    out = await channel_report(default_graph_context(), 42)
    assert out["volume"] == {"rows": 0, "documents": 0}
    assert out["fate"] == {} and out["reposts_of"] == []
    assert out["contradictions"]["total"] == 0
    assert out["graph_yield"]["entities_per_doc"] == 0.0
    assert out["graph_yield"]["new_edges_per_doc"] == 0.0
    assert out["coverage"]["without_doc_date"] == 0
    assert out["trust"]["set"] is None
    assert out["trust"]["measured"] == {"repost_share": 0.0, "displacement_rate": 0.0}
