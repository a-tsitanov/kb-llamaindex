"""Document upload + ingestion-status endpoints.

Flow: hash the body and look it up by ``content_sha256`` (повторная заливка
того же тела в тот же граф дальше не идёт — ни в MinIO, ни в очередь),
upload file to MinIO (synchronous put), insert the intake pair of Postgres
rows (``documents`` + ``doc_processing``) in one transaction, then hand the
document to the ``IngestSchedulerWorkflow`` admission singleton (K = max
in-flight documents) which starts the actual processing workflow once a
slot is available.  Returns ``202 Accepted`` with the job id.  The Temporal
worker (``src.workflow.worker``) runs the activities asynchronously.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from loguru import logger
from psycopg.errors import UniqueViolation
from pydantic import BaseModel
from urllib3.exceptions import MaxRetryError

from src.api.auth import require_api_key
from src.api.graph_dep import resolve_graph, resolve_graph_write
from src.config import settings
from src.intake.queue.priorities import PRIO_LIVE
from src.intake.repository import ON_DUPLICATE, CanonicalDoc, IntakeRepository
from src.intake.submit import submit_document
from src.retrieval.date_filters import iso_to_epoch_days, today_epoch_days
from src.retrieval.groups import GROUP_SET
from src.storage.minio import MinioStorage, S3Error, build_minio_storage, graph_object_key
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.authz import Action
from src.tenancy.context import GraphContext
from src.workflow.client import get_temporal_client
from src.workflow.contracts import IngestParams

router = APIRouter(tags=["ingestion"])

# Anything outside this set in a client-supplied original filename becomes
# "_" (path separators, quotes, control chars) so it can't escape the
# `<doc_id>/original/` prefix or break the download Content-Disposition.
_UNSAFE_NAME = re.compile(r"[^\w.\- ()\[\]]+", re.UNICODE)


def _safe_filename(name: str) -> str:
    """Basename-only, separator/control-free, no leading dots."""
    base = re.split(r"[\\/]", name)[-1]
    base = _UNSAFE_NAME.sub("_", base).strip(" .")
    return base[:200] or "original"


async def _record_sighting(
    pg: IntakeRepository,
    first: CanonicalDoc,
    *,
    department: str,
    doc_type: str,
    doc_date: str | None,
    channel: str,
    group: str,
    source_kind: str,
) -> None:
    """Зафиксировать перепост уже известного тела — если есть чем.

    Пишем ТОЛЬКО атрибутированный повтор: обе группировки отчётности идут
    по каналу и группе (``GROUP_BY_COLUMN``), поэтому повтор без них ни
    одной поверхности ничего не добавил бы, а строк в ``documents``
    прибавлял бы на каждый повторный прогон документированных заливок
    (``scripts/ingest_medical.py``, loadtest).

    Наблюдение ссылается на канонический объект в MinIO и не получает
    строки обработки — в графе остаётся одна копия тела
    (``IntakeRepository.record_duplicate_sighting``).
    """
    if not channel and not group:
        return
    await pg.record_duplicate_sighting(
        uuid.uuid4(), first.id, first.path,
        department=department,
        doc_type=doc_type,
        doc_date=doc_date,
        source_channel=channel,
        source_group=group,
        source_kind=source_kind,
    )


def _duplicate_detail(
    first_id: uuid.UUID,
    first_status: str,
    *,
    disclose: bool,
) -> dict[str, str]:
    """Тело 409: кем это тело уже принято и с каким вердиктом приёма.

    ``doc_id`` и ``intake_status`` — ответ ЧТЕНИЯ, поэтому в тело они
    попадают только ключу со scope ``read``.  Права разделены по действиям
    (``src/tenancy/authz.py``), и тот же write-only принципал — фидер —
    получает 403 и на ``GET /api/v1/ingest/{doc_id}``, и на
    ``GET /api/v1/documents/{doc_id}``; раскрывать здесь то, что там
    запрещено, значило бы обходить своё же правило.  ``intake_status``
    отвечает на главный вопрос оператора (документ обработан или отклонён)
    — и ровно поэтому это ответ чтения, а не приёма.

    Без ``read`` остаётся голое ``duplicate``: что тело уже принято,
    заявителю видно по коду ответа, а идентификатор и вердикт остаются в
    журнальной строке маршрута.

    AUTHZ_MODE здесь не читается намеренно: ``scopes`` — объявленные права
    ключа, а не окно включения, и легаси-ключ из ``API_KEYS``
    (``ApiKeyRecord.full``) несёт все четыре действия, поэтому для
    существующих установок тело 409 не меняется.
    """
    if not disclose:
        return {"message": "duplicate"}
    return {
        "message": "duplicate",
        "doc_id": str(first_id),
        "intake_status": first_status,
    }


async def _discard_uploaded(
    storage: MinioStorage,
    graph: GraphContext,
    doc_id: uuid.UUID,
) -> None:
    """Убрать из MinIO объекты документа, строки для которого не будет.

    Обычный дубль до хранилища не доходит (хеш считается раньше), но гонку
    закрывает уникальный индекс — то есть уже ПОСЛЕ ``put_object``.  Без
    уборки тело и необязательный ``original`` остались бы под префиксом
    ``doc_id``, на который не ссылается ни одна строка, и попались бы только
    ``delete_prefix`` при удалении всего графа.

    Best-effort: падение уборки пишется в журнал, но не превращает честный
    409 в 500 — у клиента от этого ничего не изменится.  Требование —
    docs/superpowers/plans/2026-10-19-intake-contour.md §1a C.
    """
    prefix = graph_object_key(graph, f"{doc_id}/")
    try:
        await asyncio.to_thread(storage.delete_prefix, prefix)
    except Exception as exc:  # уборка не должна портить ответ клиенту
        logger.warning(
            "ingest dedup cleanup failed  prefix={p}  err={e}",
            p=prefix,
            e=exc,
        )


class IngestEnqueuedResponse(BaseModel):
    job_id: uuid.UUID


class JobProgressResponse(BaseModel):
    job_id: uuid.UUID
    status: str
    path: str
    department: str
    doc_type: str
    error: str
    summary: str
    # Вердикт приёма — ДОБАВОЧНОЕ измерение рядом с семью прежними полями,
    # значения которых не меняются: отклонённый документ по-прежнему
    # отвечает status='skipped' и error=<причина>, как до расщепления
    # записи.  Без этих двух полей из ответа не было видно, что 'skipped' —
    # решение ПРИЁМА (строку обработки отказ удаляет), а не исход обработки.
    # Добавление обратно совместимо: deploy/offline/webui читает только
    # status/error, плагин agent-web — только job_id/status.
    intake_status: str
    # `intake_reason` — СОЗНАТЕЛЬНЫЙ псевдоним `error` для отклонённого
    # документа, а не второй источник: отказ удаляет строку обработки, и
    # эффективный `error` вырождается в ту же причину (см. выражение
    # eff_error в IntakeRepository.get).  Расхождения между двумя полями
    # искать не нужно — его не бывает; поле названо отдельно, чтобы
    # оператор читал причину там же, где вердикт.
    intake_reason: str = ""


@router.post(
    "/ingest",
    response_model=IngestEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a document and enqueue it for ingestion",
)
async def upload_document(
    file: UploadFile = File(...),
    original: UploadFile | None = File(default=None),
    department: str = Form(default=""),
    force: bool = Form(default=False),
    document_date: str | None = Form(default=None),
    queue: str | None = Form(default=None),
    group: str = Form(default=""),
    channel: str = Form(default=""),
    priority: int | None = Form(default=None),
    # Re-ingest of already-known material: the entity-watch journals are still
    # written, but the watch sweep raises no events for these rows.
    backfill: bool = Form(default=False),
    # Что делать с повторной заливкой того же тела (I4).  Умолчание зависит
    # от вызывающего: `version` при backfill=true, иначе `reject`.  Флаг
    # `backfill` задокументирован как «Re-ingest of already-known material»
    # и его шлют операторские перезаливки (deploy/offline/loadtest/loader.py,
    # DEPLOYMENT.md) — с умолчанием reject он стал бы no-op'ом.  Явное
    # значение всегда перекрывает умолчание.
    # Устаревшее отображение force=true → on_duplicate=version (карта
    # контуров, §4 шаг 1.2) НЕ реализуется: `force` остаётся переключателем
    # ТОЛЬКО классификатора (I4), а `backfill` — другой флаг с другой
    # документированной семантикой, и это не та же поблажка.
    on_duplicate: str | None = Form(default=None),
    x_version_tag: str | None = Header(default=None, alias="X-Version-Tag"),
    # Ключ нужен маршруту САМОМУ — тело 409 раскрывает идентификаторы только
    # читателю (см. `_duplicate_detail`).  Повторной авторизации это не
    # добавляет: FastAPI кеширует зависимость по идентичности callable, а
    # `resolve_graph_write` зовёт ту же `require_api_key`.  Инвариант «ровно
    # одно действие на маршрут» тоже цел — `tests/test_api/
    # test_route_actions.py` считает графовые зависимости, а не ключевые.
    key: ApiKeyRecord = Depends(require_api_key),
    graph: GraphContext = Depends(resolve_graph_write),
) -> IngestEnqueuedResponse:
    pg = IntakeRepository(graph=graph)
    if not file.filename:
        raise HTTPException(400, "filename required")

    # Optional target ingest queue (rabbitmq backend only). Validate up
    # front against the configured queues → 422 on an unknown name. On the
    # temporal backend the field is ignored (single admission singleton).
    target_queue: str | None = None
    if settings.ingest_admission.backend == "rabbitmq" and queue is not None:
        if queue not in settings.rabbitmq.queues:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"unknown queue {queue!r}; configured: {settings.rabbitmq.queues}",
            )
        target_queue = queue

    # Optional channel group. Validate up front → 422 on an unknown name.
    if group and group not in GROUP_SET:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"unknown group {group!r}; allowed: {sorted(GROUP_SET)}",
        )

    # Optional ingest priority (rabbitmq backend only). Higher = served first;
    # manual channel reingest posts PRIO_BACKFILL (0). None → live default.
    # Validate against the queue's advertised max so an out-of-range value 422s
    # before any upload/enqueue work. Ignored on the temporal backend.
    resolved_priority = PRIO_LIVE if priority is None else priority
    if settings.ingest_admission.backend == "rabbitmq" and not (
        0 <= resolved_priority <= settings.rabbitmq.max_priority
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"priority must be 0..{settings.rabbitmq.max_priority}",
        )

    # Политика повтора: явное значение валидируется здесь, вместе с прочими
    # ранними 422 — до чтения тела и любой работы с хранилищем.  Пустое
    # значение (его шлёт любая форма с незаполненным полем) — это «не
    # указано», а не неизвестная политика: снимаем его сами, а не надеемся
    # на то, что FastAPI подменит "" на None.
    requested = (on_duplicate or "").strip()
    if requested and requested not in ON_DUPLICATE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"unknown on_duplicate {on_duplicate!r}; allowed: {ON_DUPLICATE}",
        )
    on_duplicate_policy = requested or ("version" if backfill else "reject")

    # Optional client document date (ISO YYYY-MM-DD) for date-filtered
    # search.  Validate up front so a malformed value 422s before any
    # upload/enqueue work.  inserted_at is stamped now (UTC).
    doc_date_epoch: int | None = None
    if document_date:
        try:
            doc_date_epoch = iso_to_epoch_days(document_date)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"document_date must be ISO YYYY-MM-DD: {exc}",
            ) from exc
    inserted_at_epoch = today_epoch_days()

    doc_id = uuid.uuid4()
    # Object key keeps the original filename so the worker can pick the
    # right SimpleDirectoryReader extension handler after download.
    object_key = graph_object_key(graph, f"{doc_id}/{file.filename}")

    # Read the full body into memory.  Large PDFs (~hundreds of MB)
    # should arrive via presigned URLs in a future iteration; the
    # synchronous path here matches the previous local-disk behaviour
    # in terms of memory profile.
    contents = await file.read()

    # Дедуп — ДО хранилища: головная цель контура в том, что повторная
    # заливка того же тела в тот же граф не доходит ни до MinIO (включая
    # необязательный `original`), ни до очереди.  Поэтому хеш считается
    # сразу после чтения тела, а не рядом с INSERT'ом.
    content_sha256 = hashlib.sha256(contents).hexdigest()
    # Раскрывать ли в теле 409 идентификаторы — право чтения, одно решение
    # на оба места отказа (обычный дубль ниже и гонка на UniqueViolation).
    may_read = Action.READ in key.scopes
    first = await pg.find_by_sha(content_sha256)
    doc_type = Path(file.filename).suffix.lstrip(".").lower()
    if first is not None and on_duplicate_policy == "reject":
        logger.info(
            "ingest duplicate  sha={s}  first_doc_id={f}  channel={c}",
            s=content_sha256,
            f=first.id,
            c=channel or "-",
        )
        await _record_sighting(
            pg, first, department=department, doc_type=doc_type,
            doc_date=document_date or None, channel=channel, group=group,
            source_kind=key.owner,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_duplicate_detail(
                first.id, first.intake_status, disclose=may_read,
            ),
        )
    # Под `version` работа продолжается: версия ссылается на оригинал, и
    # `accept_document` пишет ей content_sha256=NULL — в частичный уникальный
    # индекс входит только владелец тела.  Хеш маршрут передаёт всегда, одним
    # и тем же `accept_kwargs`: инвариант живёт в одной точке записи, а не в
    # каждом вызывающем (src/intake/repository.py).
    duplicate_of = first.id if first is not None else None

    # Wrap BOTH the storage init (which on cold-start probes the
    # bucket via `bucket_exists`) AND the actual `put_object` call.
    # If MinIO is down at process start, the singleton constructor
    # is the first place that touches the network and raises.
    # `S3Error` covers protocol-level rejections (auth, missing bucket,
    # bad key); `MaxRetryError` / `OSError` cover transport failures
    # when MinIO is fully unreachable (container down, DNS, refused).
    # Both surface as the same user-visible state: storage unavailable.
    try:
        storage = build_minio_storage()
        s3_uri = await asyncio.to_thread(
            storage.put_object,
            object_key,
            io.BytesIO(contents),
            len(contents),
            file.content_type or "application/octet-stream",
        )
        # Optional original binary (e.g. the .docx `file` was converted
        # from): stored next to it for download only — the pipeline never
        # reads it.  Same in-memory read as the main file.
        original_uri: str | None = None
        if original is not None and original.filename:
            orig_bytes = await original.read()
            original_uri = await asyncio.to_thread(
                storage.put_object,
                graph_object_key(
                    graph, f"{doc_id}/original/{_safe_filename(original.filename)}",
                ),
                io.BytesIO(orig_bytes),
                len(orig_bytes),
                original.content_type or "application/octet-stream",
            )
    except (S3Error, MaxRetryError, OSError) as exc:
        logger.warning(
            "minio upload failed  doc_id={d}  err={e}", d=doc_id, e=exc,
        )
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "upload storage unavailable",
        ) from exc

    accept_kwargs: dict[str, Any] = {
        "department": department,
        "doc_type": doc_type,
        "doc_date": document_date or None,
        "source_channel": channel,
        "source_group": group,
        "original_path": original_uri,
        "content_sha256": content_sha256,
        # Личность источника — владелец ключа, которым пришёл запрос
        # (``api_keys.owner``): реестр ключей и есть реестр источников
        # (шаг 1.4, вариант A).  До этого колонка была константой 'upload'
        # у всех, то есть фидера от ручной заливки отличить было нельзя.
        # Исторические строки остались с 'upload' — это и значит «принесено
        # до реестра», переписывать их задним числом нечем.
        "source_kind": key.owner,
        # Вердикт приёма здесь не называется намеренно: у принятого
        # документа — и у версии тоже — это DEFAULT 'accepted' колонки
        # `intake_status`, ровно тот вердикт, с которым документ
        # принимают.  Гард — test_accept_always_names_intake_columns
        # в tests/test_intake/test_repository.py.  Значение 'duplicate'
        # зарезервировано под нереализованную политику `replace`.
    }
    try:
        await pg.accept_document(
            doc_id,
            s3_uri,
            duplicate_of=duplicate_of,
            **accept_kwargs,
        )
    except UniqueViolation as exc:
        # Гонку двух одновременных POST'ов одного тела закрывает частичный
        # уникальный индекс, а не чтение выше: к моменту нашего INSERT'а
        # строка победителя уже есть.  Перечитываем — победителя называет БД.
        winner = await pg.find_by_sha(content_sha256)
        if winner is None:
            # Хеш конфликтует, а канонической строки нет: это не гонка
            # приёма, а настоящая аномалия — пусть всплывает как 500.
            raise
        if on_duplicate_policy == "reject":
            await _discard_uploaded(storage, graph, doc_id)
            await _record_sighting(
                pg, winner, department=department, doc_type=doc_type,
                doc_date=document_date or None, channel=channel, group=group,
                source_kind=key.owner,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_duplicate_detail(
                    winner.id, winner.intake_status, disclose=may_read,
                ),
            ) from exc
        # `version`: наш INSERT шёл с duplicate_of=NULL (чтение ничего не
        # нашло) и попал в тот же индекс.  Повторяем ОДИН раз, сославшись на
        # победителя; второй UniqueViolation — уже аномалия, не гонка.
        # Требование — тот же план, §1a B (иначе гонка под `version` отдала
        # бы 500 ровно на том случае, ради которого индекс и заводился).
        await pg.accept_document(
            doc_id,
            s3_uri,
            duplicate_of=winner.id,
            **accept_kwargs,
        )

    # Analytics labels: explicit header wins, else AnalyticsSettings default.
    # Models are auto-captured from runtime config so model swaps
    # (LITELLM_*_MODEL env changes) are reflected without operator effort.
    # All three role models are snapshotted at submit time and propagated
    # via IngestParams → FinalizeIn → ingest_metrics rows; this guarantees
    # each row's `model` column reflects the model that activity actually
    # used (per Stage 4 of the multimodel plan).
    version_tag = x_version_tag or settings.analytics.default_version_tag
    cfg = settings.litellm
    model = cfg.effective_base
    extraction_model = cfg.model_for("extraction")
    judge_model = cfg.model_for("judge")
    search_model = cfg.model_for("search")
    env_name = settings.analytics.env_name

    client = await get_temporal_client()
    params = IngestParams(
        doc_id=str(doc_id), path=s3_uri,
        version_tag=version_tag, model=model,
        extraction_model=extraction_model,
        judge_model=judge_model,
        search_model=search_model,
        env=env_name,
        # Snapshot the wiki flag here (outside the Temporal sandbox) so
        # the workflow never reads settings.wiki — constructing
        # WikiSettings touches .env, a determinism violation inside
        # @workflow.run.
        wiki_enabled=settings.wiki.enabled,
        # Same determinism reasoning: snapshot the classifier flag here,
        # ship the operator's force override.
        classifier_enabled=settings.classifier.enabled,
        force=force,
        # Date-filter snapshots (computed above, outside the sandbox).
        doc_date=document_date or "",
        doc_date_epoch=doc_date_epoch,
        inserted_at_epoch=inserted_at_epoch,
        group=group,
        graph_id=graph.id,
        backfill=backfill,
    )
    # Admission is always on: hand the document to the configured backlog
    # backend (INGEST_QUEUE_BACKEND).  Default `temporal` = signal-with-start
    # the singleton scheduler so at most K (max_inflight) documents run at
    # once, each to completion, FIFO; `rabbitmq` = publish to a durable
    # queue a consumer drains at prefetch=K.  See src/intake/submit.
    # Обработчика «такой воркфлоу уже запущен» здесь нет намеренно: на
    # temporal-ветке стартует синглтон id='ingest-scheduler' с
    # USE_EXISTING и не бросает, rabbitmq-ветка просто публикует, а per-doc
    # id куётся в воркере.  Единственный 409 приёма — дедуп по телу выше;
    # переиспользовать под него тот обработчик было бы ложью о причине
    # (гарды единственного источника 409 — tests/test_intake/test_dedup.py
    # ::test_same_body_rejected_without_upload и
    # ::test_concurrent_insert_loses_on_unique_violation).
    await submit_document(client, params, queue=target_queue, priority=resolved_priority)
    logger.info(
        "ingest enqueued  doc_id={d}  path={p}  dept={dept}  "
        "version_tag={v}  model={m}  ext={ext}  judge={j}  search={s}  env={e}",
        d=doc_id, p=s3_uri, dept=department,
        v=version_tag, m=model, ext=extraction_model,
        j=judge_model, s=search_model, e=env_name,
    )
    return IngestEnqueuedResponse(job_id=doc_id)


@router.get(
    "/ingest/{job_id}",
    response_model=JobProgressResponse,
    summary="Get ingestion job status",
)
async def job_status(
    job_id: uuid.UUID,
    graph: GraphContext = Depends(resolve_graph),
) -> JobProgressResponse:
    pg = IntakeRepository(graph=graph)
    row = await pg.get(job_id)
    if row is None:
        raise HTTPException(404, f"job {job_id} not found")
    return JobProgressResponse(
        job_id=row.id,
        status=row.status,
        path=row.path,
        department=row.department,
        doc_type=row.doc_type,
        error=row.error,
        summary=row.summary,
        intake_status=row.intake_status,
        intake_reason=row.intake_reason,
    )
