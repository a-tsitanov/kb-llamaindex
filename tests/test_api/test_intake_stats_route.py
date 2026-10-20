"""``GET /api/v1/intake/stats`` — форма ответа, валидация, авторизация.

Агрегат ``IntakeRepository.intake_stats`` подменяется AsyncMock'ом: SQL
сторожится своими тестами (``tests/test_intake/test_intake_stats.py``),
здесь предмет — ручка.
"""

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import settings


def _key() -> dict[str, str]:
    return {"X-API-Key": settings.api.keys_list[0]}


def _fake() -> dict:
    return {
        "rows": 20,
        "documents": 15,
        "versions": {"completed": 1},
        "sightings": 4,
        "by_status": {"pending": 0, "processing": 0, "completed": 10,
                      "vector_only": 0, "failed": 2, "skipped": 3},
        "duplicate_share": 0.25,
        "throughput": {"arrived_1h": 5, "arrived_24h": 20,
                       "finished_1h": 4, "finished_24h": 18},
        "stuck": {"threshold_minutes": 120, "pending": 0, "processing": 1},
        "coverage": {"earliest_doc_date": dt.date(2026, 1, 1),
                     "latest_doc_date": dt.date(2026, 10, 19),
                     "without_doc_date": 7},
        "recent_errors": [{"doc_id": "11111111-1111-1111-1111-111111111111",
                           "doc_type": "pdf", "error": "boom",
                           "updated_at": dt.datetime(2026, 10, 19, 12, 0, 0)}],
        "top_reject_reasons": [{"reason": "classifier: not a document", "count": 3}],
        "top_doc_types": [{"doc_type": "pdf", "count": 9}],
    }


async def _get(url: str, headers: dict[str, str] | None = None):
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        return await ac.get(url, headers=headers or {})


@pytest.mark.asyncio
async def test_stats_shape_keeps_the_reconciliation_ladder() -> None:
    """Лестница сверки доезжает до клиента целиком.

    Ради неё ручка и нужна: ``rows`` минус версии и наблюдения даёт
    ``documents``, а разбивка показывает, сколько из них дошло до графа.
    """
    from src.intake.repository import IntakeRepository

    with patch.object(IntakeRepository, "intake_stats",
                      new=AsyncMock(return_value=_fake())):
        resp = await _get("/api/v1/intake/stats", _key())

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rows"] == 20 and body["documents"] == 15
    assert body["sightings"] == 4 and body["versions"] == {"completed": 1}
    assert body["rows"] == body["documents"] + 1 + body["sightings"]
    assert body["by_status"]["skipped"] == 3
    assert body["duplicate_share"] == 0.25
    assert body["stuck"]["threshold_minutes"] == 120
    assert body["throughput"]["finished_24h"] == 18
    assert body["coverage"]["earliest_doc_date"] == "2026-01-01"
    assert body["recent_errors"][0]["error"] == "boom"
    assert body["top_reject_reasons"][0]["count"] == 3
    assert body["top_doc_types"][0]["doc_type"] == "pdf"


@pytest.mark.asyncio
async def test_query_params_reach_the_aggregate() -> None:
    from src.intake.repository import IntakeRepository

    with patch.object(IntakeRepository, "intake_stats",
                      new=AsyncMock(return_value=_fake())) as m:
        resp = await _get("/api/v1/intake/stats?stuck_after_minutes=30&limit=3", _key())

    assert resp.status_code == 200, resp.text
    assert m.call_args.kwargs == {"stuck_after_minutes": 30, "limit": 3}


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    "stuck_after_minutes=0",
    "stuck_after_minutes=100000",
    "limit=0",
    "limit=1000",
])
async def test_out_of_range_params_are_refused(query: str) -> None:
    """Границы — у ручки, а не в SQL: отрицательный интервал и LIMIT 0
    Postgres принял бы молча и отдал бы бессмысленную сводку."""
    resp = await _get(f"/api/v1/intake/stats?{query}", _key())
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_stats_requires_api_key() -> None:
    resp = await _get("/api/v1/intake/stats")
    assert resp.status_code in (401, 403), resp.text
