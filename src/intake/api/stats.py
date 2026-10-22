"""Сводка приёма: ``GET /intake/stats`` (шаг 1.5 карты контуров).

Одна ручка на вопрос «почему документов в графе меньше, чем залито».
Ответ устроен как ЛЕСТНИЦА СВЕРКИ — ``rows = documents + versions +
sightings`` — и дальше разбивка принятых по статусу обработки: по этим
двум уровням разница объясняется без похода в psql.

Ручка живёт в контуре приёма, а не рядом с ``/stats/messages``: реестр
``documents`` принадлежит приёму, и агрегат читает его же (весь SQL — в
``IntakeRepository.intake_stats``).  Разделение поверхностей тоже
осмысленное: ``/stats/messages`` отвечает про каналы и группы, здесь
срез графовый и строки с пустым каналом из счёта не выпадают.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src.api.graph_dep import resolve_graph
from src.intake.repository import IntakeRepository
from src.tenancy.context import GraphContext

# Без router-level зависимости графа: действие объявляет сам обработчик
# (спека §3.1), а вторая зависимость здесь разрешала бы граф дважды.
router = APIRouter(prefix="/intake", tags=["intake"])


class Throughput(BaseModel):
    arrived_1h: int
    arrived_24h: int
    finished_1h: int
    finished_24h: int


class Stuck(BaseModel):
    threshold_minutes: int
    pending: int
    processing: int


class Coverage(BaseModel):
    earliest_doc_date: date | None = None
    latest_doc_date: date | None = None
    without_doc_date: int


class RecentError(BaseModel):
    doc_id: str
    doc_type: str
    error: str
    updated_at: datetime


class RejectReason(BaseModel):
    reason: str
    count: int


class DocTypeCount(BaseModel):
    doc_type: str
    count: int


class IntakeStatsResponse(BaseModel):
    """Лестница сверки и всё, что к ней прилагается.

    ``rows`` — строк в реестре; ``documents`` — из них принятых
    документов; ``versions`` — вторых комплектов того же тела (политика
    ``on_duplicate=version``), ``{статус: сколько}``; ``sightings`` —
    наблюдений перепоста, у которых обработки нет и не будет.  Три
    корзины не складываются в одну намеренно: сумма означала бы «строк
    залито», а не «документов принято».

    ``by_status`` — эффективный статус принятых, нули включены;
    отклонённый приёмом документ виден как 'skipped'.
    """

    rows: int
    documents: int
    versions: dict[str, int] = {}
    sightings: int
    by_status: dict[str, int]
    duplicate_share: float
    # Само число повторов рядом с долей: на большом корпусе доля — это
    # пятый знак после запятой, и читать её глазами бесполезно.
    duplicates: int = 0
    throughput: Throughput
    stuck: Stuck
    coverage: Coverage
    recent_errors: list[RecentError] = []
    top_reject_reasons: list[RejectReason] = []
    top_doc_types: list[DocTypeCount] = []


@router.get("/stats", response_model=IntakeStatsResponse,
            summary="Intake reconciliation: rows vs accepted documents")
async def intake_stats(
    stuck_after_minutes: int = Query(
        120, ge=1, le=10080,
        description="Сколько минут без движения считать застреванием",
    ),
    limit: int = Query(10, ge=1, le=100, description="Длина списков в ответе"),
    graph: GraphContext = Depends(resolve_graph),
) -> IntakeStatsResponse:
    # Границы объявлены у параметров: SQL принял бы и нулевой LIMIT, и
    # отрицательный интервал, молча отдав бессмысленную сводку.
    pg = IntakeRepository(graph=graph)
    data = await pg.intake_stats(stuck_after_minutes=stuck_after_minutes, limit=limit)
    return IntakeStatsResponse(**data)
