"""Квота приёма на граф (шаг 1.6 карты контуров).

Честность приёма между арендаторами живёт в приёме: потолок — сколько
НЕОБРАБОТАННЫХ документов арендатор может держать в общем пайплайне.
Значение берётся из `public.graphs.max_inflight`; NULL означает «квоты
нет», и это умолчание — существующая установка своего поведения не
меняет.

Отказ — 429 с `Retry-After`, а не 503 и не тихая постановка в очередь:
фидер обязан отличать «сейчас нет места» от «сломалось», иначе он либо
теряет документ, либо долбит в цикле.
"""

from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import graph_dep
from src.config import settings
from src.intake.repository import IntakeRepository
from src.tenancy.context import default_graph_context
from src.tenancy.registry import _COLS, _context_from_row

_BODY = b"a body nobody has seen before"


def _key_header() -> dict[str, str]:
    return {"X-API-Key": settings.api.keys_list[0]}


class _Reg:
    """Реестр, отдающий граф с заданной квотой."""

    def __init__(self, max_inflight: int | None) -> None:
        self._ctx = dataclasses.replace(
            default_graph_context(), max_inflight=max_inflight,
        )

    async def get(self, _gid: str):
        return self._ctx


@dataclass
class _Run:
    resp: Any
    storage: MagicMock
    inflight: AsyncMock
    accept: AsyncMock
    submit: AsyncMock


async def _post(
    *,
    max_inflight: int | None,
    inflight: int = 0,
    duplicate: bool = False,
    body: bytes = _BODY,
) -> _Run:
    from src.api.main import app

    storage = MagicMock()
    storage.put_object.side_effect = lambda key, *_a, **_k: f"s3://kb-uploads/{key}"
    canonical = None
    if duplicate:
        from src.intake.repository import CanonicalDoc

        canonical = CanonicalDoc(uuid.uuid4(), "accepted", "s3://kb-uploads/c/t.txt")
    count = AsyncMock(return_value=inflight)
    accept, submit = AsyncMock(), AsyncMock()
    with (
        patch.object(graph_dep, "get_graph_registry", lambda: _Reg(max_inflight)),
        patch("src.intake.api.ingest.build_minio_storage", MagicMock(return_value=storage)),
        patch.object(IntakeRepository, "find_by_sha", new=AsyncMock(return_value=canonical)),
        patch.object(IntakeRepository, "inflight_count", count),
        patch.object(IntakeRepository, "accept_document", accept),
        patch.object(IntakeRepository, "record_duplicate_sighting", new=AsyncMock()),
        patch("src.intake.api.ingest.get_temporal_client",
              new=AsyncMock(return_value=MagicMock())),
        patch("src.intake.api.ingest.submit_document", submit),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/ingest",
                headers=_key_header(),
                files={"file": ("t.txt", body, "text/plain")},
            )
    return _Run(resp, storage, count, accept, submit)


# ── поведение квоты ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_quota_set_means_no_counting() -> None:
    """NULL в колонке — не «ноль мест», а «квоты нет».

    Проверяется и то, что лишнего запроса к Postgres на каждый приём не
    появилось: у установки без квот горячий путь остался прежним.
    """
    run = await _post(max_inflight=None, inflight=10**6)

    assert run.resp.status_code == 202, run.resp.text
    run.inflight.assert_not_awaited()
    run.submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_under_the_cap_passes() -> None:
    run = await _post(max_inflight=5, inflight=4)

    assert run.resp.status_code == 202, run.resp.text
    run.inflight.assert_awaited_once()
    run.submit.assert_awaited_once()


@pytest.mark.asyncio
async def test_at_the_cap_refuses_without_touching_storage() -> None:
    """Отказ ДО хранилища и очереди: иначе квота стоила бы диска."""
    run = await _post(max_inflight=5, inflight=5)

    assert run.resp.status_code == 429, run.resp.text
    run.storage.put_object.assert_not_called()
    run.accept.assert_not_awaited()
    run.submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_refusal_tells_the_feeder_when_to_come_back() -> None:
    run = await _post(max_inflight=1, inflight=99)

    assert run.resp.status_code == 429
    assert int(run.resp.headers["Retry-After"]) > 0
    detail = run.resp.json()["detail"]
    # Потолок свой, арендатор свой — скрывать его не от кого; по числу
    # видно, что отказ квотный, а не случайный.
    assert "1" in detail


@pytest.mark.asyncio
async def test_duplicate_is_still_a_409_even_over_the_cap() -> None:
    """Повтор не занимает места в пайплайне, поэтому квота его не касается.

    Порядок проверок важен ровно здесь: ответь маршрут 429, фидер пришёл
    бы с тем же телом снова и снова, вместо того чтобы узнать, что тело
    уже принято.
    """
    run = await _post(max_inflight=1, inflight=99, duplicate=True)

    assert run.resp.status_code == 409, run.resp.text
    run.storage.put_object.assert_not_called()


# ── квота доезжает из реестра ────────────────────────────────────────


def test_registry_reads_max_inflight() -> None:
    """Квота приезжает тем же чтением, что и физические имена графа.

    Иначе на каждый приём был бы второй запрос в `public.graphs` — а
    горячий путь приёма и так читает Postgres дважды.
    """
    assert "max_inflight" in _COLS
    row = {
        "id": "acme", "nebula_space": "g_acme", "nebula_partition_num": 10,
        "chunks_collection": "g_acme_chunks", "er_vec_collection": "g_acme_er_vec",
        "report_vec_collection": "g_acme_report_vec", "pg_schema": "g_acme",
        "generation": 0, "tenant_id": "t1", "max_inflight": 7,
    }
    assert _context_from_row(row).max_inflight == 7
    # Старый ряд (фикстуры и рукописный SELECT в setup_db) колонки не
    # содержит — это «квоты нет», а не падение.
    del row["max_inflight"]
    assert _context_from_row(row).max_inflight is None


async def test_inflight_count_reads_processing_table(monkeypatch) -> None:
    """Счёт идёт по `doc_processing`, а не по `documents.status`.

    В `documents.status` у любой новой строки навсегда DEFAULT 'pending'
    (I8), и квота по ней считала бы весь граф необработанным.
    """
    from contextlib import asynccontextmanager

    from src.intake import repository as repo_mod

    seen: list[str] = []

    class _Cur:
        async def execute(self, q, params=None):
            seen.append(str(q))

        async def fetchone(self):
            return (3,)

    class _Conn:
        def cursor(self, row_factory=None):
            @asynccontextmanager
            async def cm():
                yield _Cur()

            return cm()

    @asynccontextmanager
    async def graph_connection(graph, timeout=None):
        yield _Conn()

    monkeypatch.setattr(repo_mod, "graph_connection", graph_connection)
    pg = IntakeRepository(graph=default_graph_context())

    assert await pg.inflight_count() == 3
    assert "doc_processing" in seen[0]
    assert "pending" in seen[0] and "processing" in seen[0]
