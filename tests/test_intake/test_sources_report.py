"""Отчёт по каналу ``channel_report``: фейковое соединение с очередью наборов.

Порядок наборов: слаги, доверие, судьба/происхождение, покрытие, перепосты,
вытеснения (два набора: «вытеснил» и «вытеснен»), отдача графу — тот же,
в котором их читает отчёт.  Фейк не исполняет SQL: тесты закрепляют
параметры и текст запросов, а не результат выборки.
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
        "won": [{"n": 1}],
        "lost": [{"n": 3}],
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
    assert set(slugs_param) == {"new_name", "old_name"}


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
    _patch(monkeypatch, [[]] * 8)
    out = await channel_report(default_graph_context(), 42)
    assert out["volume"] == {"rows": 0, "documents": 0}
    assert out["fate"] == {} and out["reposts_of"] == []
    assert out["contradictions"]["total"] == 0
    assert out["graph_yield"]["entities_per_doc"] == 0.0
    assert out["graph_yield"]["new_edges_per_doc"] == 0.0
    assert out["coverage"]["without_doc_date"] == 0
    assert out["trust"]["set"] is None
    assert out["trust"]["measured"] == {"repost_share": 0.0, "displacement_rate": 0.0}


async def test_slugs_matched_case_insensitively(monkeypatch) -> None:
    cur = _patch(monkeypatch, _sets(slugs=[{"slug": "@MyChan"}, {"slug": "OLD"}]))
    await channel_report(default_graph_context(), 42)
    for sql, _params in cur.sql[2:]:
        if "source_channel" not in sql:
            continue
        assert "lower(d.source_channel) = ANY" in sql
        assert "d.source_channel = ANY" not in sql
    # слаги в параметре: нижний регистр, без «@»; фейк SQL не исполняет
    assert cur.sql[2][1][0] == ["mychan", "old"]
    assert cur.sql[5][1][0] == ["mychan", "old"]
    assert cur.sql[6][1][0] == ["mychan", "old"]


async def test_supersede_directions_are_separate_single_join_queries(monkeypatch) -> None:
    cur = _patch(monkeypatch, _sets(won=[{"n": 1}], lost=[{"n": 1}]))
    out = await channel_report(default_graph_context(), 42)
    won_sql, won_params = cur.sql[5]
    lost_sql, lost_params = cur.sql[6]
    assert "fact_supersede" in won_sql and "fact_supersede" in lost_sql
    assert "d.id::text = s.new_doc_id" in won_sql and "stored_doc_id" not in won_sql
    assert "d.id::text = s.stored_doc_id" in lost_sql and "new_doc_id" not in lost_sql
    assert " IN (" not in won_sql and " IN (" not in lost_sql
    # одно событие внутри канала: по разу в каждом направлении, не дважды в одном
    assert out["contradictions"] == {
        "displaced_others": 1, "displaced_by_others": 1, "total": 2,
    }
    assert won_params[1] == lost_params[1] == 30


async def test_supersede_windowed_on_document_age_not_decision_time(monkeypatch) -> None:
    cur = _patch(monkeypatch, _sets())
    await channel_report(default_graph_context(), 42)
    for sql, _ in cur.sql[5:7]:
        assert "d.created_at >=" in sql
        assert "decided_at" not in sql
