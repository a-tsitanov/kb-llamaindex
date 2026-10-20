"""Сводка приёма ``IntakeRepository.intake_stats`` — шаг 1.5 карты контуров.

Соединения нет: ``graph_connection`` подменяется фейком, который отдаёт
результаты по ОЧЕРЕДИ — по одному набору строк на ``execute``.  Это
отличие от общего харнесса ``test_repository.py`` (там один набор на все
запросы) и оно обязательно: сводка склеивается из пяти разных выборок, и
тест, отдающий всем один набор, не поймал бы перепутанный порядок.

Проверяются две вещи, которые ломаются молча:

(а) **Лестница сверки** ``rows = documents + versions + sightings``.  Ради
    неё ручка и существует: по ней видно, почему документов в графе меньше,
    чем залито.  Строка-наблюдение перепоста и версия того же тела — разные
    вещи, и сложить их в одну корзину значило бы соврать про обе.

(б) **Статус читается из ``doc_processing``**, а не из
    ``documents.status``, где у любой новой строки навсегда DEFAULT
    'pending' (I8).
"""

from __future__ import annotations

import datetime as dt
import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest

from src.intake import repository as repo_mod
from src.intake.repository import DOC_STATUSES, IntakeRepository
from src.tenancy.context import default_graph_context

# ── фейковые курсор и соединение: результат на каждый execute ─────────


class _QueueCur:
    def __init__(self, results: list[list[dict[str, Any]]]) -> None:
        self.sql: list[tuple[str, Any]] = []
        self._results = list(results)
        self._current: list[dict[str, Any]] = []

    async def execute(self, q, params=None) -> None:
        self.sql.append((str(q), params))
        self._current = self._results.pop(0) if self._results else []

    async def fetchall(self):
        return self._current

    async def fetchone(self):
        return self._current[0] if self._current else None


class _Conn:
    def __init__(self, cur: _QueueCur) -> None:
        self.cur, self.commits = cur, 0

    def cursor(self, row_factory=None):
        @asynccontextmanager
        async def cm():
            yield self.cur

        return cm()

    async def commit(self) -> None:
        self.commits += 1


def _kinds(**over: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Пять наборов в том порядке, в котором их читает ``intake_stats``."""
    sets: dict[str, list[dict[str, Any]]] = {
        "kinds": [
            {"kind": "document", "status": "completed", "n": 10},
            {"kind": "document", "status": "failed", "n": 2},
            {"kind": "document", "status": "skipped", "n": 3},
            {"kind": "version", "status": "completed", "n": 1},
            {"kind": "sighting", "status": "duplicate", "n": 4},
        ],
        "scalars": [
            {
                "arrived_1h": 5, "arrived_24h": 20,
                "finished_1h": 4, "finished_24h": 18,
                "stuck_pending": 0, "stuck_processing": 1,
                "earliest_doc_date": dt.date(2026, 1, 1),
                "latest_doc_date": dt.date(2026, 10, 19),
                "without_doc_date": 7,
            }
        ],
        "errors": [
            {
                "doc_id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
                "doc_type": "pdf", "error": "boom",
                "updated_at": dt.datetime(2026, 10, 19, 12, 0, 0),
            }
        ],
        "rejects": [{"reason": "classifier: not a document", "n": 3}],
        "doc_types": [{"doc_type": "pdf", "n": 9}],
    }
    sets.update(over)
    return [sets["kinds"], sets["scalars"], sets["errors"],
             sets["rejects"], sets["doc_types"]]


def _patch(monkeypatch, results: list[list[dict[str, Any]]]) -> _Conn:
    conn = _Conn(_QueueCur(results))

    @asynccontextmanager
    async def graph_connection(graph, timeout=None):
        yield conn

    monkeypatch.setattr(repo_mod, "graph_connection", graph_connection)
    return conn


@pytest.fixture
def pg() -> IntakeRepository:
    return IntakeRepository(graph=default_graph_context())


# ── лестница сверки ──────────────────────────────────────────────────


async def test_ladder_separates_documents_versions_and_sightings(monkeypatch, pg) -> None:
    """`rows` — строк залито, `documents` — документов принято.

    Разница и есть ответ на вопрос «почему в графе меньше»: версии и
    наблюдения перепоста занимают строки, но вторым документом не
    становятся.
    """
    _patch(monkeypatch, _kinds())
    out = await pg.intake_stats()

    assert out["documents"] == 15  # 10 + 2 + 3
    assert out["versions"] == {"completed": 1}
    assert out["sightings"] == 4
    assert out["rows"] == 20
    assert out["rows"] == out["documents"] + sum(out["versions"].values()) + out["sightings"]


async def test_by_status_covers_every_status_and_counts_rejected_as_skipped(
    monkeypatch, pg,
) -> None:
    """Разбивка — по эффективному статусу и только по документам.

    Нули не опускаются: оператор смотрит в сводку глазами, и
    отсутствующий ключ читался бы как «такого статуса не бывает».
    Отклонённый приёмом документ виден как 'skipped' — тем же правилом,
    которым его показывает ``/stats/messages``.
    """
    _patch(monkeypatch, _kinds())
    out = await pg.intake_stats()

    assert set(out["by_status"]) == set(DOC_STATUSES)
    assert out["by_status"]["completed"] == 10
    assert out["by_status"]["failed"] == 2
    assert out["by_status"]["skipped"] == 3
    assert out["by_status"]["pending"] == 0
    # 'duplicate' не статус обработки: наблюдение живёт отдельным числом.
    assert "duplicate" not in out["by_status"]


async def test_duplicate_share_counts_both_kinds_of_repeat(monkeypatch, pg) -> None:
    _patch(monkeypatch, _kinds())
    out = await pg.intake_stats()

    assert out["duplicate_share"] == pytest.approx(5 / 20)


async def test_empty_graph_gives_zeros_not_division_error(monkeypatch, pg) -> None:
    _patch(monkeypatch, [[], [], [], [], []])
    out = await pg.intake_stats()

    assert out["rows"] == 0 and out["documents"] == 0
    assert out["duplicate_share"] == 0.0
    assert out["by_status"] == dict.fromkeys(DOC_STATUSES, 0)
    assert out["versions"] == {} and out["sightings"] == 0
    # Пустая выборка скаляров — не повод отдавать None вместо чисел.
    assert out["throughput"]["arrived_1h"] == 0
    assert out["stuck"]["processing"] == 0
    assert out["coverage"]["earliest_doc_date"] is None


# ── остальные поля ───────────────────────────────────────────────────


async def test_scalars_land_in_their_sections(monkeypatch, pg) -> None:
    _patch(monkeypatch, _kinds())
    out = await pg.intake_stats(stuck_after_minutes=90)

    assert out["throughput"] == {
        "arrived_1h": 5, "arrived_24h": 20, "finished_1h": 4, "finished_24h": 18,
    }
    assert out["stuck"] == {"threshold_minutes": 90, "pending": 0, "processing": 1}
    assert out["coverage"]["without_doc_date"] == 7
    assert out["coverage"]["latest_doc_date"] == dt.date(2026, 10, 19)
    assert out["recent_errors"][0]["error"] == "boom"
    assert out["recent_errors"][0]["doc_id"] == "11111111-1111-1111-1111-111111111111"
    assert out["top_reject_reasons"] == [
        {"reason": "classifier: not a document", "count": 3},
    ]
    assert out["top_doc_types"] == [{"doc_type": "pdf", "count": 9}]


# ── эмитируемый SQL ──────────────────────────────────────────────────


async def test_status_comes_from_processing_table(monkeypatch, pg) -> None:
    """Ни одна выборка статуса не читает ``documents.status`` в одиночку."""
    conn = _patch(monkeypatch, _kinds())
    await pg.intake_stats()

    kinds_sql = conn.cur.sql[0][0]
    assert "doc_processing" in kinds_sql
    assert repo_mod.EFFECTIVE_STATUS in kinds_sql
    # Наблюдение опознаётся ДО версии: у него тоже стоит duplicate_of, и
    # обратный порядок ветвей CASE сложил бы его в версии.
    assert kinds_sql.index("'sighting'") < kinds_sql.index("'version'")


async def test_thresholds_and_limits_bind_as_parameters(monkeypatch, pg) -> None:
    conn = _patch(monkeypatch, _kinds())
    await pg.intake_stats(stuck_after_minutes=45, limit=3)

    _, scalar_params = conn.cur.sql[1]
    assert scalar_params == (45, 45)
    for sql, params in conn.cur.sql[2:]:
        assert "LIMIT %s" in sql and params[-1] == 3


async def test_one_connection_and_no_writes(monkeypatch, pg) -> None:
    """Сводка — чтение: одно соединение, пять выборок, ни одного commit."""
    conn = _patch(monkeypatch, _kinds())
    await pg.intake_stats()

    assert len(conn.cur.sql) == 5 and conn.commits == 0
    assert all(sql.lstrip().upper().startswith("SELECT") for sql, _ in conn.cur.sql)
