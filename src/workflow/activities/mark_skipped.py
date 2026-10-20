"""``mark_skipped`` — вердикт отказа классификатора + уборка за документом.

Отдельный модуль по соглашению репозитория «одна активность — один
модуль» (``fetch_source.py``, ``classify_document.py``,
``merge_and_resolve.py``).  Имя активности — ``mark_skipped`` без
аргумента декоратора: по этой строке её зовёт
``src/workflow/document_ingest.py``, и переименование сломало бы реплей
незавершённых историй.

Пишет в ДРУГУЮ таблицу, чем ``finalize``: вердикт классификатора —
решение приёма, а не терминальный статус обработки.
"""

from __future__ import annotations

import asyncio
import uuid

from loguru import logger
from temporalio import activity

# Объявленное исключение §3.2 (то же, что у classify_document): вердикт
# классификатора исполняет воркер, но записывает его приём.  Запись в
# allowlist arch-теста — tests/test_intake/test_boundaries.py.
from src.intake.repository import IntakeRepository
from src.tenancy.activity import resolve_graph_for_activity
from src.workflow.contracts import IngestResult, SkipIn
from src.workflow.staging import build_staging_store, remove_local_dir


@activity.defn
async def mark_skipped(payload: SkipIn) -> IngestResult:
    """Classifier said skip: record the intake verdict + reason and clean
    up staging / local download — no parse/index/graph."""
    activity.logger.info(
        "mark_skipped start  doc=%s  reason=%s",
        payload.ctx.doc_id, payload.reason,
    )
    activity.heartbeat({"stage": "init", "doc_id": payload.ctx.doc_id})

    graph = await resolve_graph_for_activity(payload.graph_id)
    # Не update_status('skipped'): домен doc_processing такого значения не
    # содержит, и UPDATE упал бы на CHECK с бесконечным ретраем активности.
    # Отказ — решение приёма: вердикт в documents, строка обработки удаляется.
    await IntakeRepository(graph=graph).reject(
        uuid.UUID(payload.ctx.doc_id), payload.reason,
    )

    staging = build_staging_store()
    await asyncio.to_thread(staging.delete_prefix, payload.ctx.workflow_run_id)
    await asyncio.to_thread(remove_local_dir, payload.ctx.cleanup_dir)

    logger.info(
        "mark_skipped  doc={d}  reason={r}",
        d=payload.ctx.doc_id, r=payload.reason,
    )
    # graph_status='skipped' — домен ВЫХОДА воркфлоу (``IngestOutcome``), а
    # не колонка doc_processing: см. src/workflow/contracts.py.
    return IngestResult(
        doc_id=payload.ctx.doc_id,
        chunk_count=0,
        graph_status="skipped",
        entities=0,
        relations=0,
        wikibase_status="skipped",
    )
