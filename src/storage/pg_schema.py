"""Per-graph Postgres schema: the DDL every graph gets in its own schema
(``public`` for `default`), plus readiness and teardown helpers used by
``setup_db`` and graph provisioning."""

from __future__ import annotations

import re

from psycopg import sql

from src.stats.align import GRANULARITIES, VALUE_KINDS
from src.tenancy.context import GraphContext

_DOCUMENTS_DDL = """
CREATE TABLE IF NOT EXISTS documents (
    id           UUID PRIMARY KEY,
    path         TEXT NOT NULL,
    department   TEXT DEFAULT '',
    doc_type     TEXT DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'processing', 'completed',
                                   'vector_only', 'failed', 'skipped')),
    error        TEXT DEFAULT '',
    summary      TEXT DEFAULT '',
    doc_date     DATE,
    source_channel TEXT NOT NULL DEFAULT '',
    source_group   TEXT NOT NULL DEFAULT '',
    original_path  TEXT,
    content_sha256 TEXT,
    intake_status  TEXT NOT NULL DEFAULT 'accepted',
    intake_reason  TEXT NOT NULL DEFAULT '',
    -- ON DELETE SET NULL, в отличие от doc_processing.doc_id (CASCADE):
    -- удаление документа не должно ни упираться во внешний ключ со стороны
    -- его версий, ни утаскивать их за собой — осиротевшая версия просто
    -- перестаёт быть версией. Канонической она при этом НЕ становится:
    -- хеша у неё нет (см. предикат documents_sha_idx ниже), то есть владельца
    -- тела у осиротевших версий не остаётся вовсе.
    duplicate_of   UUID REFERENCES documents(id) ON DELETE SET NULL,
    source_kind    TEXT NOT NULL DEFAULT 'upload',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Idempotent adds for pre-existing deployments (CREATE TABLE IF NOT EXISTS
-- does not add a new column to an already-created table).
ALTER TABLE documents ADD COLUMN IF NOT EXISTS doc_date DATE;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_channel TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_group   TEXT NOT NULL DEFAULT '';
-- s3:// URI of the uploaded original (e.g. .docx) when `path` holds the
-- converted text; NULL = only the text was uploaded (download falls back).
ALTER TABLE documents ADD COLUMN IF NOT EXISTS original_path TEXT;

-- Колонки контура приёма (intake). Историческим строкам хеш не считается
-- (это потребовало бы скачать из MinIO весь корпус), поэтому они просто не
-- участвуют в дедупе.
ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_sha256 TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS intake_status  TEXT NOT NULL DEFAULT 'accepted';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS intake_reason  TEXT NOT NULL DEFAULT '';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS duplicate_of   UUID
    REFERENCES documents(id) ON DELETE SET NULL;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_kind    TEXT NOT NULL DEFAULT 'upload';

-- 'duplicate' в домене ЗАРЕЗЕРВИРОВАНО: политика on_duplicate=replace пока не
-- реализуется (вытеснённую копию нечем убрать из Milvus и из графа), никто это
-- значение не пишет. Оно стоит в CHECK заранее, чтобы будущий шаг не требовал
-- миграции схемы.
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_intake_status_check;
ALTER TABLE documents ADD CONSTRAINT documents_intake_status_check
    CHECK (intake_status IN ('accepted', 'duplicate', 'rejected'));

-- Хеш — собственность КАНОНИЧЕСКОЙ строки: версия того же тела (политика
-- on_duplicate=version) пишется с content_sha256 IS NULL, поэтому в индекс не
-- входит и политику version не ломает (инвариант держит единственная точка
-- записи — IntakeRepository.accept_document). Нормализация ниже приводит к
-- этому инварианту строки, записанные до его появления: без неё
-- CREATE UNIQUE INDEX упал бы на дубле «канон + его версия».
UPDATE documents SET content_sha256 = NULL
 WHERE duplicate_of IS NOT NULL AND content_sha256 IS NOT NULL;

-- Предикат смотрит ТОЛЬКО на сам хеш — и это не упрощение, а требование
-- совместимости с ON DELETE SET NULL выше: предикат вида
-- `... AND duplicate_of IS NULL` сделал бы удаление канонического документа с
-- ДВУМЯ и более версиями невозможным. FK обнуляет duplicate_of у всех версий
-- ОДНИМ UPDATE'ом, после чего они одновременно входили бы в индекс с
-- одинаковым хешем, и DELETE падал бы нарушением уникальности — ровно тем,
-- чего ON DELETE SET NULL и должен был избежать.
-- Отклонённый классификатором документ остаётся в индексе (предикат не
-- смотрит на intake_status): он владелец тела, и 409 отдаёт его вердикт.
-- Уникальность действует в пределах схемы графа: глобальный индекс был бы
-- утечкой между арендаторами.
-- DROP + CREATE, а не IF NOT EXISTS: индекс с прежним предикатом
-- (`AND duplicate_of IS NULL`) уже мог быть создан, и IF NOT EXISTS оставил бы
-- его как есть. Тот же идемпотентный шаблон, что у CHECK-ограничений выше.
DROP INDEX IF EXISTS documents_sha_idx;
CREATE UNIQUE INDEX documents_sha_idx
    ON documents (content_sha256)
    WHERE content_sha256 IS NOT NULL;

CREATE INDEX IF NOT EXISTS documents_intake_status_idx
    ON documents (intake_status);

-- Widen the status domain to include 'skipped' (classifier skip, written by
-- finalize.mark_skipped) on already-created tables. The inline CHECK above is
-- auto-named documents_status_check; drop + re-add makes this idempotent.
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_status_check;
ALTER TABLE documents ADD CONSTRAINT documents_status_check
    CHECK (status IN ('pending', 'processing', 'completed',
                      'vector_only', 'failed', 'skipped'));

CREATE INDEX IF NOT EXISTS documents_status_idx
    ON documents (status);

CREATE INDEX IF NOT EXISTS documents_department_idx
    ON documents (department);

CREATE INDEX IF NOT EXISTS documents_doc_date_idx
    ON documents (doc_date);

CREATE INDEX IF NOT EXISTS documents_source_channel_idx
    ON documents (source_channel);

CREATE INDEX IF NOT EXISTS documents_source_group_idx
    ON documents (source_group);
"""


# Статус обработки — владение ЯДРА, в отличие от реестра приёма (documents).
# Домен без 'skipped': отказ классификатора — это решение приёма
# (documents.intake_status='rejected'), а не состояние обработки.
# ON DELETE CASCADE: удаление документа уносит и его обработку.
_DOC_PROCESSING_DDL = """
CREATE TABLE IF NOT EXISTS doc_processing (
    doc_id     UUID PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    status     TEXT NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending', 'processing', 'completed',
                                 'vector_only', 'failed')),
    error      TEXT DEFAULT '',
    summary    TEXT DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS doc_processing_status_idx
    ON doc_processing (status);
"""


# Журнал выдач оригиналов (§7.3 карты контуров).  Поиск отдаёт обработанные
# фрагменты, а `GET /documents/{id}` — исходный бинарник целиком, со всем,
# что в граф не попало.  Без этой записи на вопрос «что утекло» при
# компрометации ключа ответить нечем.
#
# Внешнего ключа на `documents` ЗДЕСЬ НЕТ намеренно: журнал обязан пережить
# удаление документа и самого графа-источника, иначе `ON DELETE CASCADE`
# стёр бы ровно те строки, ради которых его ведут.  По той же причине
# пишется `path`: по нему виден выданный объект, даже если строка реестра
# больше не существует.
#
# Таблица живёт в схеме графа, как и остальной реестр: журнал чужого
# арендатора не должен быть виден через общую `public`.
_DOCUMENT_DOWNLOAD_DDL = """
CREATE TABLE IF NOT EXISTS document_download (
    id        BIGSERIAL PRIMARY KEY,
    doc_id    UUID        NOT NULL,
    variant   TEXT        NOT NULL,
    path      TEXT        NOT NULL DEFAULT '',
    principal TEXT        NOT NULL DEFAULT '',
    tenant_id TEXT        NOT NULL DEFAULT '',
    at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS document_download_doc_idx
    ON document_download (doc_id, at DESC);

-- «Что выдал этот ключ» — основной запрос расследования, поэтому индекс
-- по принципалу, а не только по документу.
CREATE INDEX IF NOT EXISTS document_download_principal_idx
    ON document_download (principal, at DESC);
"""


# Backfill source_channel for historical Telegram rows from the filename
# embedded in `path` ({doc_id}/tg_<channel>_<msgid>.txt). Greedy .+ so
# tg_a_b_123.txt -> channel 'a_b', msgid '123'. Only touches still-empty TG
# rows, so re-running setup is cheap and idempotent. source_group cannot be
# recovered (never recorded historically) and stays ''.
_BACKFILL_SOURCE_CHANNEL_SQL = r"""
UPDATE documents
   SET source_channel = substring(path from 'tg_(.+)_[0-9]+\.txt$')
 WHERE source_channel = ''
   AND path ~ 'tg_.+_[0-9]+\.txt$';
"""


_INGEST_METRICS_DDL = """
CREATE TABLE IF NOT EXISTS ingest_metrics (
    id              BIGSERIAL PRIMARY KEY,
    doc_id          UUID        NOT NULL,
    workflow_id     TEXT        NOT NULL,
    workflow_run_id TEXT        NOT NULL,
    activity_name   TEXT        NOT NULL,
    attempt         INT         NOT NULL DEFAULT 1,
    duration_ms     BIGINT      NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    completed_at    TIMESTAMPTZ NOT NULL,
    version_tag     TEXT,
    model           TEXT,
    env             TEXT,
    UNIQUE (workflow_run_id, activity_name, attempt)
);

CREATE INDEX IF NOT EXISTS ingest_metrics_doc_id_idx
    ON ingest_metrics (doc_id);
CREATE INDEX IF NOT EXISTS ingest_metrics_version_tag_idx
    ON ingest_metrics (version_tag);
CREATE INDEX IF NOT EXISTS ingest_metrics_completed_at_idx
    ON ingest_metrics (completed_at);
CREATE INDEX IF NOT EXISTS ingest_metrics_activity_idx
    ON ingest_metrics (activity_name);
"""

# Audit log of fact conflicts resolved at graph-write time (see
# src/graph/edge_conflicts.py).  One row per contradicting write: what the
# graph believed, what the new document claimed, which source won and why.
# The graph keeps only the winning belief; the retired one lives here.
_FACT_SUPERSEDE_DDL = """
CREATE TABLE IF NOT EXISTS fact_supersede (
    id              BIGSERIAL   PRIMARY KEY,
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    src             TEXT        NOT NULL,
    rel             TEXT        NOT NULL DEFAULT '',
    tgt             TEXT        NOT NULL,
    stored_polarity TEXT        NOT NULL DEFAULT '',
    new_polarity    TEXT        NOT NULL DEFAULT '',
    stored_trust    REAL        NOT NULL DEFAULT 0,
    new_trust       REAL        NOT NULL DEFAULT 0,
    stored_doc_id   TEXT        NOT NULL DEFAULT '',
    new_doc_id      TEXT        NOT NULL DEFAULT '',
    winner          TEXT        NOT NULL
);

CREATE INDEX IF NOT EXISTS fact_supersede_decided_at_idx
    ON fact_supersede (decided_at DESC);
CREATE INDEX IF NOT EXISTS fact_supersede_pair_idx
    ON fact_supersede (src, tgt);
"""


def _sql_in_list(values: frozenset[str]) -> str:
    """`'a', 'b', 'c'` for a SQL `IN (...)` clause — sorted so the
    generated DDL text is deterministic across runs.  The single source
    for turning a Python enum into SQL, used by both the inline CHECK
    below and the idempotent ALTER that keeps an already-created table's
    constraint in line with it (see `_STAT_INDICATOR_CONSTRAINTS_DDL`)."""
    return ", ".join(f"'{v}'" for v in sorted(values))


_STAT_INDICATOR_DDL = f"""
CREATE TABLE IF NOT EXISTS stat_indicator (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source         TEXT    NOT NULL,
    code           TEXT    NOT NULL,
    title          TEXT    NOT NULL,
    question_text  TEXT    NOT NULL DEFAULT '',
    unit           TEXT    NOT NULL,
    value_kind     TEXT    NOT NULL,
    granularity    TEXT    NOT NULL,
    dims_schema    JSONB   NOT NULL DEFAULT '{{}}'::jsonb,
    entity_vid     TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, code),
    CONSTRAINT stat_indicator_value_kind_check
        CHECK (value_kind IN ({_sql_in_list(VALUE_KINDS)})),
    CONSTRAINT stat_indicator_granularity_check
        CHECK (granularity IN ({_sql_in_list(GRANULARITIES)}))
);
"""

# `stat_indicator` already exists in the live database, so the
# `CREATE TABLE IF NOT EXISTS` above is a no-op there — a value added to
# VALUE_KINDS/GRANULARITIES would otherwise be accepted by Python and
# rejected by Postgres forever, with no code path that ever fixes it.
# DROP + re-ADD (same idempotent-widen shape as documents_status_check
# above) brings an existing table's CHECK constraints back in line with
# src.stats.align on every run.
_STAT_INDICATOR_CONSTRAINTS_DDL = f"""
ALTER TABLE stat_indicator DROP CONSTRAINT IF EXISTS stat_indicator_value_kind_check;
ALTER TABLE stat_indicator ADD CONSTRAINT stat_indicator_value_kind_check
    CHECK (value_kind IN ({_sql_in_list(VALUE_KINDS)}));

ALTER TABLE stat_indicator DROP CONSTRAINT IF EXISTS stat_indicator_granularity_check;
ALTER TABLE stat_indicator ADD CONSTRAINT stat_indicator_granularity_check
    CHECK (granularity IN ({_sql_in_list(GRANULARITIES)}));
"""

# `entity_vid` and `source_doc_id` are WEAK links on purpose — no
# foreign keys — so a graph rebuild or a document re-ingest can never
# invalidate a stored number.
_STAT_OBSERVATION_DDL = """
CREATE TABLE IF NOT EXISTS stat_observation (
    indicator_id   BIGINT  NOT NULL REFERENCES stat_indicator(id) ON DELETE CASCADE,
    period_start   DATE    NOT NULL,
    period_end     DATE    NOT NULL,
    dims           JSONB   NOT NULL DEFAULT '{}'::jsonb,
    value          NUMERIC NOT NULL,
    sample_n       INTEGER,
    revision       INTEGER NOT NULL DEFAULT 0,
    source_doc_id  UUID,
    loaded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (indicator_id, period_start, dims, revision)
);
"""

# ER verdict cache.  One row per borderline candidate pair already judged
# by the LLM, keyed on the order-insensitive `(norm, label)|(norm, label)`
# pair (`src/graph/entity_resolution.py:_verdict_key`).  It used to live in
# the graph as `:ERVerdict` vertices, where it grew to 1 395 491 — 89.5% of
# every vertex in the space — and made full scans hit Nebula's memory
# ceiling.  A unique-keyed KV cache belongs here; the PRIMARY KEY is the
# lookup index, and no secondary index is wanted (`er_key = ANY(...)` is
# the only access pattern, and nothing queries by age — see the plan's note
# on why pruning by `updated` would evict exactly the useful entries).
_ER_VERDICT_DDL = """
CREATE TABLE IF NOT EXISTS er_verdict (
    er_key   TEXT PRIMARY KEY,
    same     BOOLEAN     NOT NULL,
    updated  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


# Search mirror of the graph's entities. NOT a second source of truth —
# the graph stays canonical; this is a trigram-indexed flat copy so name
# lookup (exact/prefix/substring + label filter) runs in Postgres instead
# of scanning Nebula, which falls over on full scans. `vid` is the same
# entity_vid(name) key the graph vertex uses, so the mirror lines up by
# key. No pagerank/betweenness: those are offline and would drift.
_ENTITY_DDL = """
CREATE TABLE IF NOT EXISTS entity (
    vid           TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    label         TEXT NOT NULL DEFAULT '',
    description   TEXT NOT NULL DEFAULT '',
    mention_count INTEGER NOT NULL DEFAULT 1,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_ENTITY_INDEXES_DDL = """
CREATE INDEX IF NOT EXISTS entity_name_trgm_idx
    ON entity USING GIN (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS entity_label_idx ON entity (label);
"""

# Entity watch (docs/superpowers/specs/2026-10-15-entity-watch-design.md).
# Ingest appends to the two journals (entity_mention, edge_new) for EVERY
# entity; the monitor sweep reads them past a per-journal cursor and writes
# watch_event rows only for subscribed entities. entity_vid is the same
# entity_vid(name) key the graph vertex and the `entity` mirror use.
_WATCH_DDL = """
CREATE TABLE IF NOT EXISTS watch (
    id          BIGSERIAL PRIMARY KEY,
    owner       TEXT NOT NULL,
    entity_vid  TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    kinds       TEXT[] NOT NULL DEFAULT '{}',
    muted_until TIMESTAMPTZ,
    note        TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner, entity_vid)
);
CREATE TABLE IF NOT EXISTS entity_mention (
    entity_vid    TEXT NOT NULL,
    doc_id        UUID NOT NULL,
    entity_name   TEXT NOT NULL,
    label         TEXT NOT NULL DEFAULT '',
    doc_date      DATE,
    mention_count INTEGER NOT NULL DEFAULT 0,
    backfill      BOOLEAN NOT NULL DEFAULT false,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    id            BIGSERIAL UNIQUE,
    PRIMARY KEY (entity_vid, doc_id)
);
CREATE TABLE IF NOT EXISTS edge_new (
    id         BIGSERIAL PRIMARY KEY,
    src_vid    TEXT NOT NULL,
    src_name   TEXT NOT NULL,
    src_label  TEXT NOT NULL DEFAULT '',
    tgt_vid    TEXT NOT NULL,
    tgt_name   TEXT NOT NULL,
    tgt_label  TEXT NOT NULL DEFAULT '',
    rel        TEXT NOT NULL DEFAULT '',
    doc_id     UUID NOT NULL,
    doc_date   DATE,
    backfill   BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (src_vid, tgt_vid)
);
CREATE TABLE IF NOT EXISTS watch_event (
    id          BIGSERIAL PRIMARY KEY,
    entity_vid  TEXT NOT NULL,
    entity_name TEXT NOT NULL,
    kind        TEXT NOT NULL,
    doc_id      UUID,
    doc_date    DATE,
    detail      JSONB NOT NULL DEFAULT '{}',
    why         TEXT NOT NULL DEFAULT '',
    source_table TEXT NOT NULL DEFAULT '',
    source_id   BIGINT,
    dedup_key   TEXT NOT NULL UNIQUE,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Доставка (P2 S4).  Адресат — НА ПОДПИСКЕ: один URL на установку не мог
-- быть правильным для нескольких подписчиков, и именно он делал доставку
-- безадресной.  Пусто = не доставлять, только лента.
ALTER TABLE watch ADD COLUMN IF NOT EXISTS webhook_url TEXT NOT NULL DEFAULT '';
-- NULL = взять потолок из настроек (MONITOR_DAILY_PUSH_LIMIT).
ALTER TABLE watch ADD COLUMN IF NOT EXISTS daily_push_limit INTEGER;
-- `owner` — корзина ЛЕНТЫ, и сегодня это константа 'default' (один владелец,
-- пока у панели нет пользователей, src/mcp/tools_server.py).  Для доставки
-- этого мало: право проверяется по КЛЮЧУ, и ключа с именем 'default' в
-- `public.api_keys` нет.  Поэтому кто создал подписку пишется отдельно —
-- это и есть принципал, которому разрешают (или не разрешают) отправку.
-- Пусто (легаси-строки и stdio без токена) = push не делаем, только лента.
ALTER TABLE watch ADD COLUMN IF NOT EXISTS created_by TEXT NOT NULL DEFAULT '';

-- Сводка остатка: что не влезло в суточный потолок, уходит ОДНИМ
-- сообщением.  Своя таблица, а не строка в watch_delivery: сводок у
-- подписчика много (по одной за проход), и ключ (owner, event_id) места
-- под них не имеет.
CREATE TABLE IF NOT EXISTS watch_digest (
    id         BIGSERIAL PRIMARY KEY,
    owner      TEXT    NOT NULL,
    events     INTEGER NOT NULL DEFAULT 0,
    state      TEXT    NOT NULL DEFAULT 'pending'
               CHECK (state IN ('pending', 'delivered', 'failed')),
    last_error TEXT    NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Журнал доставки.  Первичный ключ (owner, event_id) И ЕСТЬ дедуп: одно
-- событие одному подписчику уходит один раз, сколько бы раз свип ни
-- перезапускался.  Состояние доставки живёт ОТДЕЛЬНО от watch_seen
-- (прочтение подписчиком): «отправлено» и «прочитано» — разные факты, и
-- смешав их, мы считали бы доставленным то, что человек открыл сам.
CREATE TABLE IF NOT EXISTS watch_delivery (
    owner      TEXT    NOT NULL,
    event_id   BIGINT  NOT NULL,
    state      TEXT    NOT NULL DEFAULT 'pending'
               CHECK (state IN ('pending', 'delivered', 'failed', 'suppressed')),
    attempts   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT    NOT NULL DEFAULT '',
    digest_of  BIGINT  REFERENCES watch_digest(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (owner, event_id)
);

-- «Что сегодня отправлено этому подписчику» — запрос на каждый проход.
CREATE INDEX IF NOT EXISTS watch_delivery_owner_day_idx
    ON watch_delivery (owner, state, updated_at DESC);

CREATE TABLE IF NOT EXISTS watch_seen (
    owner    TEXT NOT NULL,
    event_id BIGINT NOT NULL,
    seen_at  TIMESTAMPTZ,
    acked_at TIMESTAMPTZ,
    PRIMARY KEY (owner, event_id)
);
CREATE TABLE IF NOT EXISTS monitor_cursor (
    name       TEXT PRIMARY KEY,
    last_id    BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_WATCH_INDEXES_DDL = """
CREATE INDEX IF NOT EXISTS entity_mention_doc_idx ON entity_mention (doc_id);
CREATE INDEX IF NOT EXISTS edge_new_src_idx ON edge_new (src_vid);
CREATE INDEX IF NOT EXISTS edge_new_tgt_idx ON edge_new (tgt_vid);
CREATE INDEX IF NOT EXISTS watch_event_entity_idx
    ON watch_event (entity_vid, detected_at DESC);
CREATE INDEX IF NOT EXISTS watch_entity_idx ON watch (entity_vid);
"""

# Name resolution (src/graph/name_resolution.py). ``name_norm`` / ``name_translit`` are
# src.utils.names.norm_name / translit_key of ``name``, filled by the mirror writer and by
# scripts/backfill_entity_names.py for older rows. ``alive`` = the vertex still exists in the
# graph (ER deletes merged-away losers; the mirror keeps their rows). ``entity_alias`` keeps
# names that point at a canonical entity: ER merges, verdict backfill, manual.
_ENTITY_RESOLUTION_DDL = """
ALTER TABLE entity ADD COLUMN IF NOT EXISTS name_norm TEXT;
ALTER TABLE entity ADD COLUMN IF NOT EXISTS name_translit TEXT;
ALTER TABLE entity ADD COLUMN IF NOT EXISTS alive BOOLEAN NOT NULL DEFAULT TRUE;
CREATE INDEX IF NOT EXISTS entity_name_norm_idx ON entity (name_norm);
CREATE INDEX IF NOT EXISTS entity_name_translit_idx ON entity (name_translit);
CREATE INDEX IF NOT EXISTS entity_name_norm_trgm_idx
    ON entity USING GIN (name_norm gin_trgm_ops);
CREATE INDEX IF NOT EXISTS entity_name_translit_trgm_idx
    ON entity USING GIN (name_translit gin_trgm_ops);
CREATE TABLE IF NOT EXISTS entity_alias (
    alias          TEXT NOT NULL,
    alias_norm     TEXT NOT NULL,
    alias_translit TEXT NOT NULL DEFAULT '',
    canonical_vid  TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    source         TEXT NOT NULL,
    confidence     REAL NOT NULL DEFAULT 1.0,
    doc_id         TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (alias_norm, canonical_vid)
);
CREATE INDEX IF NOT EXISTS entity_alias_translit_idx ON entity_alias (alias_translit);
CREATE INDEX IF NOT EXISTS entity_alias_norm_trgm_idx
    ON entity_alias USING GIN (alias_norm gin_trgm_ops);
"""

_STAT_INDEXES_DDL = """
CREATE INDEX IF NOT EXISTS stat_observation_series_idx
    ON stat_observation (indicator_id, period_start);
CREATE INDEX IF NOT EXISTS stat_observation_dims_idx
    ON stat_observation USING GIN (dims);
CREATE INDEX IF NOT EXISTS stat_indicator_title_trgm_idx
    ON stat_indicator USING GIN (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS stat_indicator_question_trgm_idx
    ON stat_indicator USING GIN (question_text gin_trgm_ops);
"""


GRAPH_DDL: list[str] = [
    _DOCUMENTS_DDL,
    # Строго после _DOCUMENTS_DDL: внешний ключ doc_processing.doc_id требует
    # уже существующей таблицы documents.
    _DOC_PROCESSING_DDL,
    _DOCUMENT_DOWNLOAD_DDL,
    _INGEST_METRICS_DDL,
    _BACKFILL_SOURCE_CHANNEL_SQL,
    _FACT_SUPERSEDE_DDL,
    _STAT_INDICATOR_DDL,
    _STAT_INDICATOR_CONSTRAINTS_DDL,
    _STAT_OBSERVATION_DDL,
    _STAT_INDEXES_DDL,
    _ER_VERDICT_DDL,
    _ENTITY_DDL,
    _ENTITY_INDEXES_DDL,
    _ENTITY_RESOLUTION_DDL,
    _WATCH_DDL,
    _WATCH_INDEXES_DDL,
]


# Одноразовый перенос исторических строк из `documents` в `doc_processing`.
# Маркер ПОСХЕМНЫЙ: `public.schema_migration.name` — один глобальный PRIMARY
# KEY, а расщепление обязано отработать в КАЖДОЙ схеме графа.  Голое имя
# мигрировало бы ровно один граф — тот, что `_ready_graphs` (scripts/setup_db.py)
# вернёт первым в своём `ORDER BY id`, — и молча пропустило бы остальные.
# Прецедент `authz_grandfather_v1` (там же) глобален по своей природе — он
# правит общую `public.api_keys` — и на посхемные шаги НЕ обобщается.
_INTAKE_SPLIT_MARKER = "intake_split_v1"


def _intake_split(cur, graph: GraphContext) -> None:
    """Расщепить дорасщеплённые строки по двум таблицам: статус обработки
    уезжает в `doc_processing`, вердикт классификатора остаётся в `documents`
    как `intake_status='rejected'`.

    Вызывается из `migrate_graph_schema` один раз на схему графа.  Оба
    оператора идемпотентны ПО СУЩЕСТВУ, маркер — лишь оптимизация, поэтому он
    пишется ПОСЛЕДНИМ: соединение в autocommit, атомарности нет, падение между
    операторами чинится обычным повтором, а маркер, записанный первым,
    навсегда заблокировал бы недоделанную миграцию.
    """
    marker = f"{_INTAKE_SPLIT_MARKER}:{graph.pg_schema}"
    # Префикс `public.` обязателен: search_path указывает на схему графа, и
    # `public` в него не входит (src.storage.pg_scope.search_path_sql).
    cur.execute("SELECT 1 FROM public.schema_migration WHERE name = %s", (marker,))
    if cur.fetchall():  # не больше одной строки; пусто = ещё не прогоняли
        return
    # Предикат жёстче спеки (§1.3), и два добавочных условия — не украшение.
    # После расщепления в `documents.status` никто не пишет, и у принятого
    # документа там навсегда 'pending' (колонка с DEFAULT), а отказ приёма
    # (`IntakeRepository.reject`) УДАЛЯЕТ строку обработки.  Голый предикат
    # спеки при повторном прогоне вставил бы таким документам строку 'pending'
    # и перевернул бы их статус во всех поверхностях отчётности.
    cur.execute(
        """
        INSERT INTO doc_processing (doc_id, status, error, summary, updated_at)
        SELECT d.id, d.status, d.error, d.summary, d.updated_at
          FROM documents d
         WHERE d.status <> 'skipped'
           AND d.intake_status <> 'rejected'
           AND NOT EXISTS (SELECT 1 FROM doc_processing p WHERE p.doc_id = d.id)
        """
    )
    # `intake_reason` берётся из `documents.error`, а литерал — только
    # фолбэк: до расщепления причину отказа писал туда `mark_skipped`
    # (UPDATE documents SET status='skipped', error=<причина>), и голый
    # литерал затёр бы её НАВСЕГДА для всех исторических строк.  Строки
    # обработки у отклонённого документа нет (её не вставляет INSERT выше и
    # удаляет `IntakeRepository.reject`), поэтому выражение eff_error
    # вырождается в `intake_reason` — то есть и `error`, и `intake_reason`
    # в ответе API отдавали бы заглушку вместо причины, вопреки инварианту
    # «отклонённый документ отвечает error=<причина отказа> ровно как до
    # расщепления».  Идемпотентность сохраняется: предикат
    # `intake_status <> 'rejected'` не пускает второй прогон, а сама
    # колонка `documents.error` не трогается.
    cur.execute(
        """
        UPDATE documents
           SET intake_status = 'rejected',
               intake_reason = COALESCE(NULLIF(error, ''), 'classifier (pre-split)')
         WHERE status = 'skipped'
           AND intake_status <> 'rejected'
        """
    )
    cur.execute(
        "INSERT INTO public.schema_migration (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
        (marker,),
    )


def migrate_graph_schema(cur, graph: GraphContext) -> None:
    """Create (idempotently) one graph's tables in its own schema."""
    from src.storage.pg_scope import search_path_sql

    if graph.pg_schema != "public":
        cur.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(graph.pg_schema)),
        )
    cur.execute(search_path_sql(graph))
    for stmt in GRAPH_DDL:
        cur.execute(stmt)
    # Строго после GRAPH_DDL (обеим таблицам надо существовать) и до RESET
    # (запросы без префикса схемы опираются на search_path графа).
    _intake_split(cur, graph)
    cur.execute("RESET search_path")


_CREATE_TABLE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+([a-z_][a-z0-9_]*)", re.IGNORECASE)


def graph_tables() -> list[str]:
    """Every table GRAPH_DDL creates, in DDL order, without duplicates."""
    seen: list[str] = []
    for stmt in GRAPH_DDL:
        for name in _CREATE_TABLE.findall(stmt):
            if name not in seen:
                seen.append(name)
    return seen


def missing_graph_tables(cur, graph: GraphContext) -> list[str]:
    """Tables of GRAPH_DDL absent from ``graph``'s schema (empty = complete).
    Provisioning sets a graph `ready` only when this is empty."""
    cur.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
        (graph.pg_schema,),
    )
    present = {r[0] for r in cur.fetchall()}
    return [t for t in graph_tables() if t not in present]


def drop_graph_schema(cur, graph: GraphContext) -> None:
    """``DROP SCHEMA … CASCADE`` for a non-default graph.  Refuses `default`
    and anything not named ``g_<id>`` — this must never touch `public`."""
    if graph.is_default or graph.pg_schema != f"g_{graph.id}":
        raise ValueError(f"refusing to drop schema {graph.pg_schema!r} of graph {graph.id!r}")
    cur.execute(
        sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(graph.pg_schema)),
    )
