"""ASGI-тесты для ``GET /api/v1/ingest/{job_id}``.

После расщепления записи (приём пишет ``documents``, обработка —
``doc_processing``) отказ классификатора строку обработки УДАЛЯЕТ.  Пока
статус читался из одной таблицы, такой документ выглядел пропавшим; здесь
проверяется, что он по-прежнему виден как 'skipped' и что два добавочных
поля объясняют, ПОЧЕМУ.

Строки собираются настоящим ``DocumentRow.from_dict`` из того же словаря,
который отдаёт выборка репозитория — иначе тест проверял бы выдуманный
объект.  Само сведение двух таблиц считает SQL ``IntakeRepository.get``, и
сторожат его тесты репозитория: здесь проверяется ответ маршрута.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.intake.repository import DocumentRow

# Семь полей, которые отдавал обработчик до появления поля приёма.  Набор
# зафиксирован списком, а не вычисляется из модели: иначе тест
# test_legacy_fields_unchanged согласился бы с любым переименованием.
_LEGACY_FIELDS = frozenset(
    {"job_id", "status", "path", "department", "doc_type", "error", "summary"},
)
_NEW_FIELDS = frozenset({"intake_status", "intake_reason"})

_DOC_ID = uuid.uuid4()
_REASON = "irrelevant: нерелевантный документ"


def _key() -> dict[str, str]:
    return {"X-API-Key": settings.api.keys_list[0]}


def _row(
    *,
    eff_status: str = "pending",
    eff_error: str = "",
    eff_summary: str = "",
    intake_status: str = "accepted",
    intake_reason: str = "",
) -> DocumentRow:
    """Строка выборки ``IntakeRepository.get``.

    ``eff_*`` — эффективные значения: сведение ``documents`` ×
    ``doc_processing`` считает SQL репозитория (его сторожит
    ``tests/test_intake/test_repository.py``), поэтому здесь они задаются
    готовыми — иначе тест маршрута пересказывал бы то же правило второй раз.
    """
    now = datetime(2026, 10, 19, 12, 0, 0)
    return DocumentRow.from_dict(
        {
            "id": _DOC_ID,
            "path": "s3://kb-uploads/default/doc/file.txt",
            "department": "qa",
            "doc_type": "txt",
            "status": "pending",
            "created_at": now,
            "updated_at": now,
            "intake_status": intake_status,
            "intake_reason": intake_reason,
            "eff_status": eff_status,
            "eff_error": eff_error,
            "eff_summary": eff_summary,
        },
    )


async def _get_status(row: DocumentRow | None):
    from src.api.main import app

    with patch(
        "src.intake.repository.IntakeRepository.get",
        new=AsyncMock(return_value=row),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            return await ac.get(f"/api/v1/ingest/{_DOC_ID}", headers=_key())


@pytest.mark.asyncio
async def test_pending_document() -> None:
    """Принятый и ещё не обработанный: приём сказал 'accepted', причины нет."""
    resp = await _get_status(_row())

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["intake_status"] == "accepted"
    assert body["intake_reason"] == ""


@pytest.mark.asyncio
async def test_rejected_document_is_visible() -> None:
    """Отклонённый классификатором документ не пропадает из выдачи.

    Строки обработки у него нет (её удалила ``IntakeRepository.reject``), но
    отвечать надо 200 и прежними значениями: 'skipped' в ``status`` и причина
    отказа в ``error`` — ровно как до расщепления записи.  Новые поля
    добавляют то, чего в прежнем ответе не было: это решение ПРИЁМА.
    """
    resp = await _get_status(
        _row(eff_status="skipped", eff_error=_REASON,
             intake_status="rejected", intake_reason=_REASON),
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "skipped"
    assert body["error"] == _REASON
    assert body["intake_status"] == "rejected"
    assert body["intake_reason"] == _REASON


@pytest.mark.asyncio
async def test_completed_document() -> None:
    """Обработанный: статус и сводка из обработки, вердикт приёма прежний."""
    resp = await _get_status(
        _row(eff_status="completed", eff_summary="краткое содержание"),
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["summary"] == "краткое содержание"
    assert body["error"] == ""
    assert body["intake_status"] == "accepted"


@pytest.mark.asyncio
async def test_unknown_job_404() -> None:
    """Неизвестный id — по-прежнему 404, а не пустой ответ приёма."""
    resp = await _get_status(None)

    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_legacy_fields_unchanged() -> None:
    """Добавление обратно совместимо: прежние семь полей плюс ровно два новых.

    Гард для чужих читателей ответа: ``deploy/offline/webui/index.html``
    смотрит только в ``status``/``error``, плагин agent-web — в
    ``job_id``/``status``.  Ни одно прежнее имя не переехало и не исчезло.
    """
    resp = await _get_status(_row())

    assert resp.status_code == 200, resp.text
    keys = set(resp.json())
    assert keys == _LEGACY_FIELDS | _NEW_FIELDS
