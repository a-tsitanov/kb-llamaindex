"""Провенанс приёма в теле события (S3 плана P2).

«Новая связь» из перепоста и «новая связь» из первоисточника — разной
ценности, а по графу они неразличимы: узлы и связи одинаковые. Различие
знает реестр приёма, и после P1 оно там есть — источник (`source_kind`,
шаг 1.4A), вердикт приёма и ссылка на владельца тела (`intake_status`,
`duplicate_of`, шаг 1.2).

Проверяется две вещи: что свип спрашивает приём ОДИН раз на пачку (а не
по документу на событие) и что ответ доезжает в `detail.provenance`.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest

from src.intake import repository as intake_repo_mod
from src.intake.repository import IntakeRepository
from src.tenancy.context import default_graph_context
from src.watch.sweep import run_watch_sweep

_DOC_A = uuid.uuid4()
_DOC_B = uuid.uuid4()


class _Repo:
    """Репозиторий наблюдения с одним журналом в одну строку."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.saved: list[dict[str, Any]] = []
        self._drained = False

    async def watched(self) -> dict[str, str]:
        return {"vid1": "Акме"}

    async def cursor(self, _journal: str) -> int:
        return 0

    async def read_journal(self, journal: str, *, after_id: int, limit: int):
        if journal != "entity_mention" or self._drained:
            return []
        self._drained = True
        return self._rows

    async def save_events(self, _journal, events, *, last_id) -> None:
        self.saved += events


def _mention(doc_id: uuid.UUID, row_id: int) -> dict[str, Any]:
    return {
        "id": row_id, "entity_vid": "vid1", "entity_name": "Акме",
        "doc_id": str(doc_id), "doc_date": None, "mention_count": 1,
        "label": "Organization", "backfill": False,
    }


@pytest.mark.asyncio
async def test_provenance_lands_in_the_event_detail() -> None:
    repo = _Repo([_mention(_DOC_A, 1)])
    asked: list[list[str]] = []

    async def provenance(doc_ids: list[str]) -> dict[str, dict]:
        asked.append(sorted(doc_ids))
        return {
            str(_DOC_A): {"source_kind": "tg:news", "intake_status": "duplicate",
                          "duplicate_of": str(_DOC_B), "doc_date": None},
        }

    await run_watch_sweep(repo, provenance=provenance)

    assert asked == [[str(_DOC_A)]]
    prov = repo.saved[0]["detail"]["provenance"]
    assert prov["source_kind"] == "tg:news"
    # Перепост: тело уже принято, и по событию это видно.
    assert prov["intake_status"] == "duplicate"
    assert prov["duplicate_of"] == str(_DOC_B)


@pytest.mark.asyncio
async def test_intake_is_asked_once_per_batch_not_per_event() -> None:
    """Пачка в тысячу строк не должна превращаться в тысячу запросов."""
    rows = [_mention(_DOC_A, 1), _mention(_DOC_B, 2), _mention(_DOC_A, 3)]
    repo = _Repo(rows)
    calls = 0

    async def provenance(doc_ids: list[str]) -> dict[str, dict]:
        nonlocal calls
        calls += 1
        return {d: {"source_kind": "upload"} for d in doc_ids}

    await run_watch_sweep(repo, provenance=provenance)

    assert calls == 1
    assert all(e["detail"]["provenance"]["source_kind"] == "upload" for e in repo.saved)


@pytest.mark.asyncio
async def test_sweep_without_a_provider_behaves_as_before() -> None:
    """Провенанс — добавка: без провайдера свип работает, как работал."""
    repo = _Repo([_mention(_DOC_A, 1)])

    await run_watch_sweep(repo)

    assert repo.saved and "provenance" not in repo.saved[0]["detail"]


@pytest.mark.asyncio
async def test_unknown_document_does_not_invent_a_provenance_key() -> None:
    """Пустой ответ приёма — не повод писать `provenance: null`.

    Ключ без значения читался бы как «источник неизвестен», тогда как
    правда — «мы не спрашивали» или «строки уже нет».
    """
    repo = _Repo([_mention(_DOC_A, 1)])

    async def provenance(_doc_ids: list[str]) -> dict[str, dict]:
        return {}

    await run_watch_sweep(repo, provenance=provenance)

    assert "provenance" not in repo.saved[0]["detail"]


@pytest.mark.asyncio
async def test_provider_failure_does_not_lose_the_events() -> None:
    """Приём недоступен — событие всё равно записывается, без провенанса.

    Событие — факт графа, а провенанс — украшение: ронять свип (и тем
    самым курсор журнала) из-за недоступного реестра значило бы терять
    уведомления ради подписи под ними.
    """
    repo = _Repo([_mention(_DOC_A, 1)])

    async def provenance(_doc_ids: list[str]) -> dict[str, dict]:
        raise RuntimeError("pg down")

    await run_watch_sweep(repo, provenance=provenance)

    assert len(repo.saved) == 1
    assert "provenance" not in repo.saved[0]["detail"]


# ── SQL чтения в приёме ──────────────────────────────────────────────


async def test_provenance_of_reads_the_intake_registry(monkeypatch) -> None:
    """Запрос один, по списку, и не трогает `doc_processing`.

    Статус обработки у наблюдения и так есть — это сам факт события;
    спрашивается именно приём: откуда документ и чем он оказался.
    """
    seen: list[tuple[str, Any]] = []

    class _Cur:
        async def execute(self, q, params=None):
            seen.append((str(q), params))

        async def fetchall(self):
            return [{"id": _DOC_A, "source_kind": "tg:news",
                     "intake_status": "accepted", "duplicate_of": None,
                     "doc_date": None}]

    class _Conn:
        def cursor(self, row_factory=None):
            @asynccontextmanager
            async def cm():
                yield _Cur()

            return cm()

    @asynccontextmanager
    async def graph_connection(graph, timeout=None):
        yield _Conn()

    monkeypatch.setattr(intake_repo_mod, "graph_connection", graph_connection)
    pg = IntakeRepository(graph=default_graph_context())

    out = await pg.provenance_of([_DOC_A, _DOC_B])

    assert len(seen) == 1
    sql, params = seen[0]
    assert "FROM documents" in sql and "doc_processing" not in sql
    assert params == ([str(_DOC_A), str(_DOC_B)],)
    assert out[str(_DOC_A)]["source_kind"] == "tg:news"
    # Неизвестного документа в ответе нет вовсе — ключ без значения
    # читался бы как «источник неизвестен».
    assert str(_DOC_B) not in out


async def test_provenance_of_empty_list_asks_nothing(monkeypatch) -> None:
    called = False

    @asynccontextmanager
    async def graph_connection(graph, timeout=None):
        nonlocal called
        called = True
        yield None

    monkeypatch.setattr(intake_repo_mod, "graph_connection", graph_connection)
    pg = IntakeRepository(graph=default_graph_context())

    assert await pg.provenance_of([]) == {}
    assert called is False
