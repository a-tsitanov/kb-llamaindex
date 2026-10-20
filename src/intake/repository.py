"""Реестр приёма: весь SQL по таблице ``documents``.

Перенесён из ``src/storage/postgres.py`` без изменения текста запросов —
``documents`` описывает принятые документы, то есть принадлежит контуру
приёма, а не общей инфраструктуре хранения.  В ``AsyncPostgres`` остались
``update_status`` (статус обработки) и ``record_fact_conflicts``
(аудит ``fact_supersede``) — к приёму они отношения не имеют.

Запись расщеплена на две таблицы: приём пишет ``documents``, обработка —
``doc_processing``.  Читатели сводят их обратно выражением эффективного
статуса (``EFFECTIVE_STATUS``): наружу — в ``/stats/messages``, в CLI и в
MCP — отчётный словарь статусов остаётся прежним.

Схему инициализирует ``scripts/setup_db.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NamedTuple

import psycopg
from psycopg.rows import dict_row

from src.storage.pg_scope import graph_connection, search_path_sql
from src.tenancy.context import GraphContext

DOC_STATUSES: tuple[str, ...] = (
    "pending", "processing", "completed", "vector_only", "failed", "skipped",
)

# Эффективный статус документа после расщепления: строка обработки; если её
# нет — вердикт приёма ('rejected' → отчётное 'skipped': отказ классификатора
# строку обработки УДАЛЯЕТ); если нет и его — дорасщеплённая колонка
# documents.status, которую мы не удаляли (I8).
#
# ЕДИНСТВЕННОЕ место, где записано это правило: и построчное чтение (`get`),
# и агрегат (`status_counts_by`), и CLI (scripts/check_ingestion.py) считают
# статус этим выражением, а не каждый своим.  Поэтому имя публичное.
# Наблюдение перепоста (``intake_status='duplicate'``, см.
# ``record_duplicate_sighting``) обработки не имеет и не получит, поэтому у
# него собственное имя статуса.  Без этой ветки выражение упало бы на
# ``documents.status``, где у любой новой строки навсегда DEFAULT 'pending'
# (I8), и наблюдение выглядело бы вечно ждущим обработки.
EFFECTIVE_STATUS = (
    "COALESCE(p.status, CASE WHEN d.intake_status = 'rejected' "
    "THEN 'skipped' WHEN d.intake_status = 'duplicate' "
    "THEN 'duplicate' ELSE d.status END)"
)

# Политики повтора (I4), в порядке перечисления в 422.  `reject` — умолчание
# приёма; `version` выбирает документированная операторская перезаливка — POST
# с `backfill=true` (DEPLOYMENT.md, deploy/offline/loadtest/loader.py) и ручной
# `scripts/tg_ingest.py --reingest`, который шлёт `version` явно: смысл режима —
# перечитать окно канала заново, и с умолчанием он стал бы no-op'ом.  Обычный
# проход синка политику не шлёт: там 409 — успех, а не ошибка.
#
# `replace` из §2.2 спеки сюда НЕ входит и отвечает 422 вместе с прочими
# неизвестными значениями: ни один путь чтения не смотрит в `documents`, так
# что три Postgres-оператора вытеснения не убрали бы ни одного чанка из Milvus
# и ни одного узла из графа — обе копии остались бы одинаково находимыми, а
# Postgres объявлял бы одну дубликатом.  Значение 'duplicate' в CHECK колонки
# `intake_status` занято наблюдением перепоста
# (`record_duplicate_sighting`), а не отложенной политикой.
ON_DUPLICATE: tuple[str, ...] = ("reject", "version")

_DIMENSIONS = {"source_channel", "source_group"}
_DATE_FIELDS = {"created_at", "doc_date"}
GROUP_BY_COLUMN = {"channel": "source_channel", "group": "source_group"}


class CanonicalDoc(NamedTuple):
    """Владелец тела: строка, у которой есть ``content_sha256``.

    ``path`` нужен наблюдению перепоста — оно ссылается на тот же объект в
    MinIO; ``intake_status`` уезжает в тело 409, чтобы повторная заливка
    видела вердикт первого документа, а не просто «уже есть».
    """

    id: uuid.UUID
    intake_status: str
    path: str


@dataclass
class DocumentRow:
    id: uuid.UUID
    path: str
    department: str
    doc_type: str
    status: str
    error: str
    summary: str
    created_at: datetime
    updated_at: datetime
    # s3:// URI of the uploaded original binary; None = text-only upload.
    original_path: str | None = None
    # Вердикт приёма — измерение, отдельное от статуса обработки: документ
    # может быть принят и ещё не обработан, а может быть не принят вовсе.
    intake_status: str = "accepted"
    intake_reason: str = ""

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> DocumentRow:
        """Собрать строку из выборки ``IntakeRepository.get``.

        `status`/`error`/`summary` приезжают УЖЕ эффективными, под
        псевдонимами ``eff_*``: сводит две таблицы SQL — тем же выражением
        ``EFFECTIVE_STATUS``, которым считают агрегаты.  Здесь остаётся
        только раскладка по полям, без второй копии правила.
        """
        return cls(
            id=row["id"],
            path=row["path"],
            department=row["department"] or "",
            doc_type=row["doc_type"] or "",
            status=row["eff_status"],
            error=row["eff_error"] or "",
            summary=row["eff_summary"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            # .get: the column is absent until setup_db adds it.
            original_path=row.get("original_path") or None,
            intake_status=row.get("intake_status") or "accepted",
            intake_reason=row.get("intake_reason") or "",
        )


class IntakeRepository:
    """Чтение и запись реестра принятых документов.

    Connections come from the per-process pool
    (``src/storage/pg_pool.py``) so high-volume status updates reuse
    connections instead of opening one per call.  Passing an explicit
    ``dsn`` (e.g. a one-off script pointed at another database) keeps
    the legacy connect-per-call path.
    """

    def __init__(self, dsn: str | None = None, *, graph: GraphContext) -> None:
        # None → shared pool; explicit dsn → legacy direct connect.
        self._dsn = dsn
        self._graph = graph

    @asynccontextmanager
    async def _conn(self) -> AsyncIterator[psycopg.AsyncConnection]:
        if self._dsn is None:
            async with graph_connection(self._graph) as conn:
                yield conn
        else:
            async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
                await conn.execute(search_path_sql(self._graph))
                await conn.commit()
                yield conn

    async def accept_document(
        self, doc_id: uuid.UUID, path: str,
        department: str = "", doc_type: str = "",
        doc_date: str | None = None,
        source_channel: str = "", source_group: str = "",
        original_path: str | None = None,
        content_sha256: str | None = None,
        duplicate_of: uuid.UUID | None = None,
        source_kind: str = "upload",
    ) -> None:
        """Принять документ: строка реестра и строка его обработки.

        Обе вставки идут ОДНОЙ транзакцией.  Внешний ключ
        ``doc_processing.doc_id`` делает их одним актом приёма, и это не
        косметика: двумя отдельными транзакциями падение между ними
        оставило бы документ без строки обработки — визуально неотличимым
        от отклонённого, а ровно на эту неотличимость опирается предикат
        миграции ``intake_split_v1``.

        Колонка ``documents.status`` не называется: у принятого документа
        там навсегда остаётся ``NOT NULL DEFAULT 'pending'`` (I8), а живой
        статус живёт в ``doc_processing``.  По той же причине не называется
        ``intake_status``: его ``DEFAULT 'accepted'`` — ровно тот вердикт, с
        которым документ принимают, а 'duplicate' зарезервировано под
        нереализованную политику ``replace`` и никем не пишется.

        ``duplicate_of`` — ссылка на канонический документ с тем же телом
        (политика ``version``).  ЕДИНСТВЕННОЕ место, где записан инвариант
        «хеш принадлежит канонической строке»: у версии ``content_sha256``
        пишется NULL, что бы ни передал вызывающий, поэтому в предикат
        частичного уникального индекса ``documents_sha_idx`` она не входит
        и конфликта по телу не даёт.  Провенанс тела у версии читается
        через ``duplicate_of``, а не через собственный хеш.

        Обнулять хеш, а не исключать версии предикатом индекса, обязывает
        ``ON DELETE SET NULL`` у самого ``duplicate_of``: предикат
        ``AND duplicate_of IS NULL`` ломал бы удаление канонического
        документа с двумя и более версиями — FK обнулил бы ссылки одним
        UPDATE'ом, и версии одновременно вошли бы в индекс с одинаковым
        хешем (см. комментарий у индекса в ``src/storage/pg_schema.py``).

        Колонки приёма называются ВСЕГДА: ``content_sha256`` и
        ``duplicate_of`` nullable, у ``source_kind`` в схеме
        ``NOT NULL DEFAULT 'upload'`` — то же значение, что умолчание
        аргумента, так что обычная заливка пишет ровно ту же строку, что и
        раньше.  Условной остаётся одна ``original_path``.
        """
        cols = ["id", "path", "department", "doc_type", "doc_date",
                "source_channel", "source_group",
                "content_sha256", "duplicate_of", "source_kind"]
        vals: list[Any] = [str(doc_id), path, department, doc_type, doc_date,
                           source_channel, source_group,
                           None if duplicate_of else content_sha256,
                           str(duplicate_of) if duplicate_of else None,
                           source_kind]
        # Only name the column when there is a value, so text-only ingests
        # keep working on a DB that setup_db hasn't migrated yet.
        if original_path is not None:
            cols.append("original_path")
            vals.append(original_path)
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"INSERT INTO documents ({', '.join(cols)}) "
                    f"VALUES ({', '.join(['%s'] * len(cols))})",
                    tuple(vals),
                )
                await cur.execute(
                    "INSERT INTO doc_processing (doc_id) VALUES (%s)",
                    (str(doc_id),),
                )
            await conn.commit()

    async def find_by_sha(self, content_sha256: str) -> CanonicalDoc | None:
        """Каноническая строка с таким телом или None.

        ``path`` в выборке — для наблюдения перепоста: оно ссылается на ТОТ
        ЖЕ объект в MinIO, поэтому второй копии тела в хранилище не
        появляется (``record_duplicate_sighting``).

        Предикат — ровно предикат частичного уникального индекса
        ``documents_sha_idx``: один непустой хеш, одна строка.  Условия по
        ``duplicate_of`` здесь нет и не нужно: хеш есть только у
        канонической строки (``accept_document``), поэтому выборка не может
        вернуть версию, и цепочка ``duplicate_of`` не ветвится — все версии
        одного тела ссылаются на один и тот же оригинал.

        Отклонённый классификатором документ из выборки НЕ исключается: он
        остаётся владельцем хеша, и повторная заливка того же тела должна
        получить 409 с его вердиктом, а не завести второй документ, который
        отклонят точно так же.

        Уникальность — строго в пределах схемы графа: соединение приходит
        из ``graph_connection``, глобального индекса по хешу нет (он был бы
        утечкой между арендаторами).
        """
        async with self._conn() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT id, intake_status, path FROM documents "
                "WHERE content_sha256 = %s",
                (content_sha256,),
            )
            row = await cur.fetchone()
        return CanonicalDoc(row[0], row[1], row[2]) if row else None

    async def record_duplicate_sighting(
        self, doc_id: uuid.UUID, canonical_id: uuid.UUID, path: str,
        department: str = "", doc_type: str = "",
        doc_date: str | None = None,
        source_channel: str = "", source_group: str = "",
        source_kind: str = "upload",
    ) -> None:
        """Записать ПОЯВЛЕНИЕ уже известного тела у нового источника.

        Фидер читает каналы независимо, и дословный перепост — обычное дело.
        Тело при этом уже принято, второй копии в графе не нужно (решение
        пользователя), но канал-получатель обязан остаться в числах: без
        этой строки ``/stats/messages`` и лента недосчитывали бы перепосты
        по нему, и восстановить их было бы нечем — факт перепоста не
        записан нигде.

        Отличие от политики ``version``: версия идёт в пайплайн и даёт
        второй комплект чанков и узлов, наблюдение — нет. Поэтому
        ``doc_processing`` у него НЕ создаётся: отсутствие строки обработки
        и есть признак «работы по нему не было и не будет», и его же читает
        выражение эффективного статуса (``EFFECTIVE_STATUS`` отдаёт
        'duplicate').

        ``path`` — путь КАНОНИЧЕСКОЙ строки: объект в MinIO один, выдача
        оригинала по наблюдению отдаёт то же тело.  ``content_sha256`` не
        называется: хеш — собственность канонической строки, иначе
        наблюдение вошло бы в частичный уникальный индекс
        ``documents_sha_idx`` и INSERT упал бы на дубле (тот же инвариант,
        что у версии в ``accept_document``).
        """
        cols = ["id", "path", "department", "doc_type", "doc_date",
                "source_channel", "source_group", "source_kind",
                "intake_status", "duplicate_of"]
        vals: list[Any] = [str(doc_id), path, department, doc_type, doc_date,
                           source_channel, source_group, source_kind,
                           "duplicate", str(canonical_id)]
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"INSERT INTO documents ({', '.join(cols)}) "
                    f"VALUES ({', '.join(['%s'] * len(cols))})",
                    tuple(vals),
                )
            await conn.commit()

    async def reject(self, doc_id: uuid.UUID, reason: str) -> None:
        """Отказ приёма: вердикт в ``documents`` и УДАЛЕНИЕ строки обработки.

        Отказ классификатора — решение приёма, а не состояние обработки,
        поэтому строка в ``doc_processing`` не переводится в терминальный
        статус, а исчезает: домен этой таблицы намеренно не содержит
        'skipped' (``src/storage/pg_schema.py``), и UPDATE туда упал бы на
        CHECK.  Наружу отклонённый документ по-прежнему виден как
        'skipped' — это считает выражение эффективного статуса
        (``EFFECTIVE_STATUS``), а не колонка.

        Удаление намеренное, и у него есть следствие за пределами метода:
        повторный прогон миграции ``intake_split_v1`` обязан проверять и
        ``intake_status``, и ``NOT EXISTS`` по ``doc_processing`` — голый
        предикат «строки обработки нет» воскресил бы отклонённому документу
        строку 'pending'.

        Обе записи идут ОДНОЙ транзакцией, как и приём: падение между ними
        оставило бы документ с вердиктом отказа и живой строкой обработки,
        то есть ровно тем расхождением двух источников истины, ради
        устранения которого запись и расщепили.
        """
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE documents
                       SET intake_status = 'rejected',
                           intake_reason = %s,
                           updated_at = NOW()
                     WHERE id = %s
                    """,
                    (reason, str(doc_id)),
                )
                await cur.execute(
                    "DELETE FROM doc_processing WHERE doc_id = %s",
                    (str(doc_id),),
                )
            await conn.commit()

    async def list_id_path(self) -> list[tuple[str, str]]:
        """Return `(doc_id, path)` for every registered document.

        Used by the legacy `doc_id` backfill to map a chunk's stored
        `file_path` back to its document id."""
        async with self._conn() as conn, conn.cursor() as cur:
            await cur.execute("SELECT id, path FROM documents")
            rows = await cur.fetchall()
        return [(str(r[0]), r[1]) for r in rows]

    async def get(self, doc_id: uuid.UUID) -> DocumentRow | None:
        async with (
            self._conn() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            # Сведение двух таблиц считает SQL — тем же выражением, что у
            # агрегатов, поэтому правило в модуле записано один раз.
            # Псевдонимы eff_* обязательны: status/error/summary есть в обеих
            # таблицах, и dict_row схлопнул бы каждую пару в один ключ.
            # `error`: пустое значение в строке обработки — не ответ, поэтому
            # NULLIF пропускает его к вердикту приёма (так же, как делал
            # прежний ``or`` в Python).
            await cur.execute(
                f"SELECT d.*, {EFFECTIVE_STATUS} AS eff_status, "
                "COALESCE(NULLIF(p.error, ''), d.intake_reason) AS eff_error, "
                "COALESCE(p.summary, '') AS eff_summary "
                "FROM documents d "
                "LEFT JOIN doc_processing p ON p.doc_id = d.id "
                "WHERE d.id = %s",
                (str(doc_id),),
            )
            row = await cur.fetchone()
        return DocumentRow.from_dict(row) if row else None

    async def status_counts_by(
        self,
        dimension: str,
        since: object | None = None,
        until: object | None = None,
    ) -> list[dict]:
        """Per-key (channel or group) count of each pipeline status.

        `dimension` MUST be 'source_channel' or 'source_group' — validated
        against a hardcoded set before interpolation. Empty keys (non-TG
        docs) are excluded. `since`/`until` bound `created_at` (inclusive /
        exclusive). Returns dicts with a count per status in DOC_STATUSES plus
        `total`, sorted by total desc.

        Канонические и неканонические строки считаются РАЗДЕЛЬНО.  `total` и
        разбивка по статусам — только канонические документы: иначе `total`
        означал бы «строк залито», а не «документов принято», и числа
        разъехались бы с дорасщеплёнными (у любой строки до миграции
        ``duplicate_of IS NULL``).  Версии того же тела (политика
        ``on_duplicate=version``, её шлёт документированный реингест) идут
        в добавочное поле ``versions`` — ``{статус: сколько}`` без нулей.
        Поле именно добавочное: форма расширяется обратно совместимо, как
        ``JobProgressResponse.intake_status``, и исход реингеста перестаёт
        быть невидимым (версия идёт в пайплайн наравне с документом, и её
        `failed` оператору нужен ровно затем, зачем он реингестил).

        Ключ, у которого в окне есть ТОЛЬКО версии, попадает в ответ с
        ``total=0`` и непустым ``versions`` — в хвост сортировки.
        """
        if dimension not in _DIMENSIONS:
            raise ValueError(f"bad dimension {dimension!r}")
        where = [f"d.{dimension} <> ''"]
        params: list[object] = []
        if since is not None:
            where.append("d.created_at >= %s")
            params.append(since)
        if until is not None:
            where.append("d.created_at < %s")
            params.append(until)
        # GROUP BY повторяет ВЫРАЖЕНИЕ, а не псевдоним: неоднозначное имя в
        # GROUP BY Postgres разрешает в пользу входной колонки, то есть
        # `GROUP BY status` молча сгруппировал бы по d.status.  Признак
        # каноничности повторяется выражением по той же причине — чтобы
        # правило «в GROUP BY только выражения» не приходилось держать в
        # голове с исключениями.
        canonical = "(d.duplicate_of IS NULL)"
        sql = (
            f"SELECT d.{dimension} AS key, {EFFECTIVE_STATUS} AS status, "
            f"{canonical} AS canonical, COUNT(*) AS n "
            f"FROM documents d "
            f"LEFT JOIN doc_processing p ON p.doc_id = d.id "
            f"WHERE {' AND '.join(where)} "
            f"GROUP BY key, {EFFECTIVE_STATUS}, {canonical}"
        )
        async with self._conn() as conn, conn.cursor() as cur:
            await cur.execute(sql, params)
            raw = await cur.fetchall()
        agg: dict[str, dict] = {}
        for key, status, is_canonical, n in raw:
            row = agg.setdefault(
                key,
                {"key": key, "total": 0, **{s: 0 for s in DOC_STATUSES},
                 "versions": {}},
            )
            if not is_canonical:
                # Неканоническая строка не влияет ни на `total`, ни на
                # разбивку: она не отдельный документ, но и не пустое место.
                row["versions"][status] = row["versions"].get(status, 0) + n
                continue
            # `total` is deliberately the count of ALL rows for the key, not
            # just the ones matching a known status: every status the DB
            # CHECK permits is already in DOC_STATUSES, so the `if` guard
            # below never drops a real status. Keeping `total` unconditional
            # means it stays the true per-key row count even if the status
            # domain is later widened before DOC_STATUSES is updated to match.
            # Сверка с DOC_STATUSES, а не с ключами строки: иначе статус,
            # случайно названный как служебный ключ ('key', 'versions'),
            # затёр бы его.
            if status in DOC_STATUSES:
                row[status] = n
            row["total"] += n
        return sorted(agg.values(), key=lambda r: r["total"], reverse=True)

    async def timeline_counts(
        self,
        date_field: str = "created_at",
        group_by: str | None = None,
        channel: str | None = None,
        group: str | None = None,
        since: object | None = None,
        until: object | None = None,
    ) -> list[dict]:
        """Daily message counts. `date_field` ∈ {'created_at','doc_date'};
        `group_by` ∈ {None,'channel','group'} adds a per-key breakdown.
        Optional `channel`/`group` filter to one key. All identifiers are
        allowlisted; values bind as parameters. Ordered by day."""
        if date_field not in _DATE_FIELDS:
            raise ValueError(f"bad date_field {date_field!r}")
        keycol = None
        if group_by is not None:
            if group_by not in GROUP_BY_COLUMN:
                raise ValueError(f"bad group_by {group_by!r}")
            keycol = GROUP_BY_COLUMN[group_by]
        select = [f"date_trunc('day', {date_field})::date AS day"]
        group_cols = ["day"]
        if keycol:
            select.append(f"{keycol} AS key")
            group_cols.append("key")
        # Все колонки ленты живут в documents — join'ить обработку незачем.
        # Предикат различает две неканонические вещи. ВЕРСИЯ (политика
        # `version`) — второй комплект чанков того же сообщения, она не
        # добавляет дню ещё одного сообщения, иначе числа разъехались бы с
        # дорасщеплёнными (у любой строки до миграции `duplicate_of IS NULL`).
        # НАБЛЮДЕНИЕ (`intake_status='duplicate'`) — отдельное сообщение
        # отдельного канала с уже известным телом; без него канал, живущий
        # перепостами, показывал бы в ленте ноль. Разбивки статусов у ленты
        # нет вовсе, поэтому прятать здесь больше нечего
        # (docs/runbook/message-stats.md).
        where = [
            f"{date_field} IS NOT NULL",
            "(duplicate_of IS NULL OR intake_status = 'duplicate')",
        ]
        params: list[object] = []
        if channel is not None:
            where.append("source_channel = %s")
            params.append(channel)
        if group is not None:
            where.append("source_group = %s")
            params.append(group)
        if since is not None:
            where.append(f"{date_field} >= %s")
            params.append(since)
        if until is not None:
            where.append(f"{date_field} < %s")
            params.append(until)
        sql = (
            f"SELECT {', '.join(select)}, COUNT(*) AS n "
            f"FROM documents WHERE {' AND '.join(where)} "
            f"GROUP BY {', '.join(group_cols)} ORDER BY day"
        )
        async with self._conn() as conn, conn.cursor() as cur:
            await cur.execute(sql, params)
            raw = await cur.fetchall()
        out: list[dict] = []
        for rec in raw:
            if keycol:
                day, key, n = rec
                out.append({"day": day, "key": key, "count": n})
            else:
                day, n = rec
                out.append({"day": day, "count": n})
        return out

    async def intake_stats(
        self,
        *,
        stuck_after_minutes: int = 120,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Сводка приёма по графу: почему документов меньше, чем залито.

        Отвечает на операторский вопрос одной выдачей, а не тремя
        запросами в psql.  Устройство ответа — ЛЕСТНИЦА СВЕРКИ:

            rows = documents + versions + sightings

        ``rows`` — строк в реестре, ``documents`` — принятых документов
        (канонических), ``versions`` — вторых комплектов того же тела
        (политика ``on_duplicate=version``), ``sightings`` — наблюдений
        перепоста (``record_duplicate_sighting``).  Три корзины разделены
        намеренно: сложенные вместе, они дали бы «строк залито» под именем
        «документов» — расхождение, из-за которого и появился этот шаг
        (``docs/superpowers/plans/2026-10-17-project-boundaries.md``, 1.5).

        ``documents`` совпадает с суммой ``total`` в ``/stats/messages`` с
        одной оговоркой: та поверхность отбрасывает строки с пустым
        каналом, а здесь срез графовый и считаются все.

        Статус берётся выражением ``EFFECTIVE_STATUS``, то есть из
        ``doc_processing``; отклонённый приёмом документ виден как
        'skipped'.  Читать ``documents.status`` здесь нельзя: у любой
        новой строки там навсегда DEFAULT 'pending' (I8).

        Пять выборок идут на ОДНОМ соединении и ни одна не пишет:
        транзакция у них общая, поэтому лестница сверки не разъезжается
        из-за заливки, случившейся между запросами.
        """
        # Корзина строки. Наблюдение проверяется ПЕРВЫМ: у него тоже стоит
        # duplicate_of, и обратный порядок ветвей зачислил бы его в версии.
        kind = (
            "CASE WHEN d.intake_status = 'duplicate' THEN 'sighting' "
            "WHEN d.duplicate_of IS NOT NULL THEN 'version' "
            "ELSE 'document' END"
        )
        # Терминальные статусы обработки: по ним считается пропускная
        # способность. 'skipped' здесь нет — это вердикт приёма, работы по
        # нему не было (``reject`` строку обработки удаляет).
        terminal = "('completed','vector_only','failed')"
        async with (
            self._conn() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            # (1) Лестница и разбивка по статусам. GROUP BY повторяет
            # ВЫРАЖЕНИЯ, а не псевдонимы: неоднозначное имя Postgres
            # разрешает в пользу входной колонки, то есть `GROUP BY status`
            # сгруппировал бы по d.status (та же причина, что в
            # ``status_counts_by``).
            await cur.execute(
                f"SELECT {kind} AS kind, {EFFECTIVE_STATUS} AS status, "
                "COUNT(*) AS n FROM documents d "
                "LEFT JOIN doc_processing p ON p.doc_id = d.id "
                f"GROUP BY {kind}, {EFFECTIVE_STATUS}"
            )
            kinds = await cur.fetchall()
            # (2) Скаляры: приток, завершения, застрявшие, покрытие датами.
            # Порог застревания — параметр, а не литерал интервала: у
            # оператора он зависит от того, чем забита очередь.
            await cur.execute(
                "SELECT "
                "COUNT(*) FILTER (WHERE d.created_at >= NOW() - INTERVAL '1 hour') "
                "  AS arrived_1h, "
                "COUNT(*) FILTER (WHERE d.created_at >= NOW() - INTERVAL '24 hours') "
                "  AS arrived_24h, "
                f"COUNT(*) FILTER (WHERE p.status IN {terminal} "
                "  AND p.updated_at >= NOW() - INTERVAL '1 hour') AS finished_1h, "
                f"COUNT(*) FILTER (WHERE p.status IN {terminal} "
                "  AND p.updated_at >= NOW() - INTERVAL '24 hours') AS finished_24h, "
                "COUNT(*) FILTER (WHERE p.status = 'pending' "
                "  AND p.updated_at < NOW() - make_interval(mins => %s)) AS stuck_pending, "
                "COUNT(*) FILTER (WHERE p.status = 'processing' "
                "  AND p.updated_at < NOW() - make_interval(mins => %s)) AS stuck_processing, "
                "MIN(d.doc_date) AS earliest_doc_date, "
                "MAX(d.doc_date) AS latest_doc_date, "
                "COUNT(*) FILTER (WHERE d.doc_date IS NULL) AS without_doc_date "
                "FROM documents d "
                "LEFT JOIN doc_processing p ON p.doc_id = d.id",
                (stuck_after_minutes, stuck_after_minutes),
            )
            scalars = await cur.fetchone() or {}
            # (3) Последние отказы пайплайна — с текстом ошибки.
            await cur.execute(
                "SELECT d.id AS doc_id, d.doc_type, p.error, p.updated_at "
                "FROM documents d JOIN doc_processing p ON p.doc_id = d.id "
                "WHERE p.status = 'failed' AND p.error <> '' "
                "ORDER BY p.updated_at DESC LIMIT %s",
                (limit,),
            )
            errors = await cur.fetchall()
            # (4) Причины отказов ПРИЁМА — агрегатом, а не списком: вердикт
            # классификатора повторяется дословно, и оператору нужно
            # «чего отсекли больше всего», а не последние десять строк.
            await cur.execute(
                "SELECT COALESCE(NULLIF(intake_reason, ''), '(без причины)') AS reason, "
                "COUNT(*) AS n FROM documents WHERE intake_status = 'rejected' "
                "GROUP BY reason ORDER BY n DESC LIMIT %s",
                (limit,),
            )
            rejects = await cur.fetchall()
            # (5) Типы документов — только по принятым: версия того же тела
            # удвоила бы свой тип, наблюдение — тоже.
            await cur.execute(
                "SELECT doc_type, COUNT(*) AS n FROM documents "
                "WHERE duplicate_of IS NULL AND intake_status <> 'duplicate' "
                "AND doc_type <> '' "
                "GROUP BY doc_type ORDER BY n DESC LIMIT %s",
                (limit,),
            )
            doc_types = await cur.fetchall()

        by_status = dict.fromkeys(DOC_STATUSES, 0)
        versions: dict[str, int] = {}
        documents = sightings = rows = 0
        for rec in kinds:
            n = rec["n"]
            rows += n
            if rec["kind"] == "sighting":
                sightings += n
            elif rec["kind"] == "version":
                versions[rec["status"]] = versions.get(rec["status"], 0) + n
            else:
                documents += n
                # Сверка с DOC_STATUSES: статус вне домена CHECK в разбивку
                # не попадает, но из `documents` не исчезает — иначе
                # лестница сверки перестала бы сходиться.
                if rec["status"] in by_status:
                    by_status[rec["status"]] += n
        repeats = sightings + sum(versions.values())
        return {
            "rows": rows,
            "documents": documents,
            "versions": versions,
            "sightings": sightings,
            "by_status": by_status,
            "duplicate_share": round(repeats / rows, 4) if rows else 0.0,
            "throughput": {
                k: int(scalars.get(k) or 0)
                for k in ("arrived_1h", "arrived_24h", "finished_1h", "finished_24h")
            },
            "stuck": {
                "threshold_minutes": stuck_after_minutes,
                "pending": int(scalars.get("stuck_pending") or 0),
                "processing": int(scalars.get("stuck_processing") or 0),
            },
            "coverage": {
                "earliest_doc_date": scalars.get("earliest_doc_date"),
                "latest_doc_date": scalars.get("latest_doc_date"),
                "without_doc_date": int(scalars.get("without_doc_date") or 0),
            },
            "recent_errors": [
                {
                    "doc_id": str(r["doc_id"]),
                    "doc_type": r["doc_type"] or "",
                    "error": r["error"],
                    "updated_at": r["updated_at"],
                }
                for r in errors
            ],
            "top_reject_reasons": [
                {"reason": r["reason"], "count": r["n"]} for r in rejects
            ],
            "top_doc_types": [
                {"doc_type": r["doc_type"], "count": r["n"]} for r in doc_types
            ],
        }

    async def record_download(
        self, doc_id: uuid.UUID, variant: str, path: str,
        principal: str = "", tenant_id: str = "",
    ) -> None:
        """Записать ВЫДАЧУ исходного документа (§7.3 карты контуров).

        Поиск отдаёт обработанные фрагменты, а ``GET /documents/{id}`` —
        исходный бинарник целиком: персональные данные, метаданные файла,
        всё, что в граф не попало.  Поэтому выдача — событие, которое
        нужно уметь перечислить: без журнала на вопрос «что утекло» при
        компрометации ключа ответить нечем.

        ``variant`` — ЭФФЕКТИВНЫЙ вариант ('original' или 'text'), а не то,
        что прислал клиент: по умолчанию маршрут отдаёт оригинал, если он
        есть, и текст, если нет, и запись «variant=None» не отвечала бы,
        что именно ушло.  ``path`` — выданный объект: по нему видно тело,
        даже если строка реестра к моменту расследования удалена (внешнего
        ключа у журнала нет, см. DDL).

        ``principal`` — ``owner`` ключа, которым пришёл запрос, то есть то
        же имя, под которым источник пишется в ``documents.source_kind``
        (шаг 1.4A).  Один словарь имён на приём и на выдачу.
        """
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO document_download "
                    "(doc_id, variant, path, principal, tenant_id) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (str(doc_id), variant, path, principal, tenant_id),
                )
            await conn.commit()

    async def downloads_of(
        self, doc_id: uuid.UUID, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Кто и когда получал этот документ — для ответа на «что утекло».

        Чтение журнала намеренно НЕ выставлено в HTTP: это материал
        расследования, и выдавать его тем же правом `read`, которым
        пользуется обычный поиск, значило бы показать подозреваемому его
        собственный след.  Метод существует для операторского скрипта и
        psql-сессии.
        """
        async with (
            self._conn() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                "SELECT variant, path, principal, tenant_id, at "
                "FROM document_download WHERE doc_id = %s "
                "ORDER BY at DESC LIMIT %s",
                (str(doc_id), limit),
            )
            return list(await cur.fetchall())
