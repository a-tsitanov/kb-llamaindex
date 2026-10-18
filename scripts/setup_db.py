"""Idempotent DB initialisation.

Stage 1 scope:
  * Postgres — create ``documents`` table tracking ingestion job
    status (mirrors enterprise-kb schema for easy diffing).
  * Milvus — connectivity ping.  The actual collection is created
    by ``llama_index.vector_stores.milvus.MilvusVectorStore`` on
    first insert (Stage 3).

Graph (Nebula) provisioning is handled separately by
``scripts/nebula_bootstrap.py`` / lazy schema creation on first write.

Usage::

    python -m scripts.setup_db
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from loguru import logger

from src.config import settings
from src.storage.pg_schema import (  # noqa: F401 — re-exported for tests/ops
    _BACKFILL_SOURCE_CHANNEL_SQL,
    _DOCUMENTS_DDL,
    _ENTITY_DDL,
    _ENTITY_INDEXES_DDL,
    _ENTITY_RESOLUTION_DDL,
    _ER_VERDICT_DDL,
    _FACT_SUPERSEDE_DDL,
    _INGEST_METRICS_DDL,
    _STAT_INDEXES_DDL,
    _STAT_INDICATOR_CONSTRAINTS_DDL,
    _STAT_INDICATOR_DDL,
    _STAT_OBSERVATION_DDL,
    _WATCH_DDL,
    _WATCH_INDEXES_DDL,
    GRAPH_DDL,
    migrate_graph_schema,
)
from src.utils.logging import configure_logging

# ── Postgres ─────────────────────────────────────────────────────────


# pg_trgm lives in its own `extensions` schema so a graph's search_path
# (`<schema>, extensions`) never includes `public` (R-P5).  Existing
# deployments created it in `public`; move it (indexes keep working — they
# reference the opclass by OID).
_PG_TRGM_DDL = """
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA extensions;
DO $$
BEGIN
    IF (SELECT n.nspname FROM pg_extension e
        JOIN pg_namespace n ON n.oid = e.extnamespace
        WHERE e.extname = 'pg_trgm') <> 'extensions' THEN
        ALTER EXTENSION pg_trgm SET SCHEMA extensions;
    END IF;
END $$;
"""


def _set_database_search_path(cur) -> None:
    """Default path for connections that never pin a graph (bot, registry,
    RESET after a graph checkout): keep `public`, add `extensions` so
    trigram functions still resolve."""
    cur.execute(
        "DO $$ BEGIN EXECUTE format("
        "'ALTER DATABASE %I SET search_path TO \"$user\", public, extensions', "
        "current_database()); END $$;"
    )


# Telegram bot: who may use it, and what everyone asked.
#
# `bot_user.status` is the admission boundary and the ONLY one — every
# approved client sees the same corpus the operator does (the service has
# no data-level access control: `SearchRequest.department` / `user_id` are
# RESERVED and the group filters carry an explicit "NOT an access-control
# boundary" warning).  So this table decides who gets in, nothing more.
_BOT_USER_DDL = """
CREATE TABLE IF NOT EXISTS public.bot_user (
    telegram_id  BIGINT PRIMARY KEY,
    username     TEXT        NOT NULL DEFAULT '',
    status       TEXT        NOT NULL DEFAULT 'pending',
    role         TEXT        NOT NULL DEFAULT 'client',
    daily_quota  INTEGER     NOT NULL DEFAULT 20,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at  TIMESTAMPTZ,
    approved_by  BIGINT,
    CONSTRAINT bot_user_status_check
        CHECK (status IN ('pending', 'active', 'blocked')),
    CONSTRAINT bot_user_role_check
        CHECK (role IN ('client', 'admin'))
);
"""

# One row per request, written BEFORE the work starts and completed after —
# including refusals (quota, busy, denied).  An audit that records only
# successes is not an audit.
#
# Deliberately NO foreign key to `bot_user`: the record of what someone
# asked must outlive the account being deleted.
_BOT_REQUEST_DDL = """
CREATE TABLE IF NOT EXISTS public.bot_request (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    telegram_id  BIGINT      NOT NULL,
    chat_id      BIGINT      NOT NULL,
    command      TEXT        NOT NULL,
    args         TEXT        NOT NULL DEFAULT '',
    status       TEXT        NOT NULL DEFAULT 'running',
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    answer       TEXT        NOT NULL DEFAULT '',
    sources      JSONB       NOT NULL DEFAULT '[]'::jsonb,
    error        TEXT        NOT NULL DEFAULT '',
    CONSTRAINT bot_request_status_check
        CHECK (status IN ('running', 'done', 'failed', 'denied'))
);
"""

# Serves both `/history` (newest-first per user) and the daily quota count.
# No other index is wanted: every read of this table is scoped to one user.
_BOT_INDEXES_DDL = """
CREATE INDEX IF NOT EXISTS bot_request_user_time_idx
    ON public.bot_request (telegram_id, started_at DESC);
"""

# Tenants own graphs and keys (spec 2026-10-18 §1).  The `default` row is the
# pre-tenancy world and MUST exist before any `REFERENCES public.tenants(id)`
# runs — the FK arrives by ALTER on tables that already hold rows, so an empty
# `tenants` would fail the ALTER on every existing graph/key.  Hence the INSERT
# inside this multi-statement block (GLOBAL_DDL runs in order, and all of it
# before `_bootstrap_registry`), exactly like `_PG_TRGM_DDL`.
#
# `schema_migration` records one-off data migrations that must not repeat —
# today only `_grandfather_scopes`.
_TENANTS_DDL = """
CREATE TABLE IF NOT EXISTS public.tenants (
    id          TEXT PRIMARY KEY,
    name        TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO public.tenants (id, name) VALUES ('default', 'Default tenant')
    ON CONFLICT (id) DO NOTHING;
CREATE TABLE IF NOT EXISTS public.schema_migration (
    name        TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

# Multi-graph registry (Plan A).  Lives in `public` regardless of which
# schema a given graph's own tables live in — this is the directory that
# maps a graph id to its physical storage names, not per-graph data.
_GRAPHS_DDL = """
CREATE TABLE IF NOT EXISTS public.graphs (
    id                     TEXT PRIMARY KEY,
    owner                  TEXT NOT NULL,
    status                 TEXT NOT NULL,
    status_error           TEXT NOT NULL DEFAULT '',
    nebula_space           TEXT NOT NULL,
    nebula_partition_num   INTEGER NOT NULL DEFAULT 10,
    chunks_collection      TEXT NOT NULL,
    er_vec_collection      TEXT NOT NULL,
    report_vec_collection  TEXT NOT NULL,
    pg_schema              TEXT NOT NULL,
    max_inflight           INTEGER,
    generation             BIGINT NOT NULL DEFAULT 0,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE public.graphs ADD COLUMN IF NOT EXISTS generation BIGINT NOT NULL DEFAULT 0;
ALTER TABLE public.graphs ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'
    REFERENCES public.tenants(id);
CREATE INDEX IF NOT EXISTS graphs_tenant_idx ON public.graphs (tenant_id);
"""

# API keys, sha256-hashed at rest — never the raw key.  Global (public), and
# since the 2026-10-18 spec a key also carries its rights: the tenant it
# belongs to, the actions it may perform and an optional narrowing to named
# graphs (NULL = every graph of its tenant).  `is_admin` does NOT come back —
# the `admin` scope replaces it.
#
# Additive migration only (ADD COLUMN IF NOT EXISTS with a DEFAULT), so code
# still running `SELECT owner` keeps working against the new schema.  The
# `scopes` default is the WEAKEST right: a row written by something that does
# not know about scopes must not arrive with powers.  Rows that predate the
# column are handled once by `_grandfather_scopes`.
_API_KEYS_DDL = """
CREATE TABLE IF NOT EXISTS public.api_keys (
    key_hash    TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE public.api_keys ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'
    REFERENCES public.tenants(id);
ALTER TABLE public.api_keys ADD COLUMN IF NOT EXISTS scopes TEXT[] NOT NULL DEFAULT '{read}';
ALTER TABLE public.api_keys ADD COLUMN IF NOT EXISTS graph_ids TEXT[];
CREATE INDEX IF NOT EXISTS api_keys_tenant_idx ON public.api_keys (tenant_id);
"""

# Every action, as a SQL literal.  Spelled out rather than built from
# `src.tenancy.authz.Action` so the emitted SQL is stable and greppable;
# `tests/test_scripts/test_setup_db_authz.py` guards the two against drift.
_FULL_SCOPES_SQL = "ARRAY['read', 'write', 'download_original', 'admin']"

# One-off: keys that predate the `scopes` column keep every action, so the
# migration itself revokes nothing.  Guarded by a marker row rather than
# being idempotent by nature — an unguarded blanket UPDATE would hand back,
# on every later `setup_db` run, exactly the rights an operator had just
# revoked by hand.
_GRANDFATHER_MARKER = "authz_grandfather_v1"


def _grandfather_scopes(cur) -> None:
    """Give every pre-migration key the full scope set; a no-op once the
    marker row sits in `public.schema_migration`.

    Read-then-write, not one atomic statement: under READ COMMITTED two init
    containers can both find no marker and both write the same blanket grant
    (harmless — identical set), which is why the claim carries `ON CONFLICT
    DO NOTHING` so the loser does not abort setup_db on the duplicate.  What
    the marker really protects is the LATER run, after an operator has
    narrowed a key by hand.
    """
    cur.execute(
        "SELECT 1 FROM public.schema_migration WHERE name = %s",
        (_GRANDFATHER_MARKER,),
    )
    if cur.fetchall():  # at most one row; empty means "never ran"
        return
    cur.execute(f"UPDATE public.api_keys SET scopes = {_FULL_SCOPES_SQL}")
    cur.execute(
        "INSERT INTO public.schema_migration (name) VALUES (%s) "
        "ON CONFLICT (name) DO NOTHING",
        (_GRANDFATHER_MARKER,),
    )
    logger.info("authz: existing api_keys grandfathered to full scopes")


def _bootstrap_registry(cur) -> None:
    """Idempotent: register `default` under its legacy names and the env
    API_KEYS as `legacy-env` keys."""
    from src.tenancy.api_keys import hash_api_key
    from src.tenancy.context import default_graph_context

    # Before anything this run inserts — those rows carry their scopes.
    _grandfather_scopes(cur)
    d = default_graph_context()
    cur.execute(
        "INSERT INTO public.graphs (id, owner, status, nebula_space, nebula_partition_num, "
        "chunks_collection, er_vec_collection, report_vec_collection, pg_schema) "
        "VALUES (%s, %s, 'ready', %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
        (d.id, "system", d.nebula_space, d.nebula_partition_num, d.chunks_collection,
         d.er_vec_collection, d.report_vec_collection, d.pg_schema),
    )
    env_hashes = [
        hash_api_key(k.strip()) for k in settings.api.keys.split(",") if k.strip()
    ]
    for key_hash in env_hashes:
        # Rights spelled out, never left to the column DEFAULT '{read}':
        # that would quietly strip tg_ingest, the offline webui and
        # graph_refresh.sh of ingest rights on the very next run.
        cur.execute(
            "INSERT INTO public.api_keys (key_hash, owner, tenant_id, scopes) "
            f"VALUES (%s, 'legacy-env', 'default', {_FULL_SCOPES_SQL}) "
            "ON CONFLICT (key_hash) DO NOTHING",
            (key_hash,),
        )
    # R-P7: API_KEYS is the source of truth for legacy-env rows — a key
    # rotated out of / removed from the env is revoked on this run.
    if env_hashes:
        cur.execute(
            "DELETE FROM public.api_keys WHERE owner = 'legacy-env' "
            "AND NOT (key_hash = ANY(%s))",
            (env_hashes,),
        )
    else:
        cur.execute("DELETE FROM public.api_keys WHERE owner = 'legacy-env'")


_ANALYTICS_SEARCH_ATTRS: dict[str, str] = {
    "VersionTag":      "KEYWORD",
    "Model":           "KEYWORD",   # global default snapshot
    "ExtractionModel": "KEYWORD",   # per-role snapshot
    "JudgeModel":      "KEYWORD",
    "SearchModel":     "KEYWORD",
    "Env":             "KEYWORD",
}


def setup_temporal_search_attributes() -> None:
    """Register the three custom Search Attributes used by the
    analytics layer (Stage 4 of the Grafana plan) via the Temporal
    SDK OperatorService.  Idempotent — AlreadyExists is logged as
    a no-op; other failures are warnings (the workflow falls back
    to no search-attribute filtering in Temporal UI, but the
    Postgres ingest_metrics path is unaffected).
    """
    import asyncio

    from temporalio.api.enums.v1 import IndexedValueType
    from temporalio.api.operatorservice.v1 import AddSearchAttributesRequest
    from temporalio.client import Client

    name_to_enum = {
        name: getattr(IndexedValueType, f"INDEXED_VALUE_TYPE_{kind}")
        for name, kind in _ANALYTICS_SEARCH_ATTRS.items()
    }

    async def _register() -> None:
        client = await Client.connect(
            settings.temporal.target,
            namespace=settings.temporal.namespace,
        )
        op = client.operator_service
        req = AddSearchAttributesRequest(
            namespace=settings.temporal.namespace,
            search_attributes=name_to_enum,
        )
        try:
            await op.add_search_attributes(req)
            logger.info(
                "search-attrs registered  names={n}",
                n=list(_ANALYTICS_SEARCH_ATTRS.keys()),
            )
        except Exception as exc:
            msg = str(exc).lower()
            if "already exists" in msg or "alreadyexist" in msg:
                logger.info("search-attrs already registered (no-op)")
            elif "advanced visibility" in msg or "not supported" in msg:
                logger.warning(
                    "Temporal visibility store does not support custom "
                    "search attrs (Postgres visibility — needs ES for advanced).  "
                    "Skipping — analytics still works via ingest_metrics. "
                    "err={e}", e=exc,
                )
            else:
                logger.warning("search-attr register failed  err={e}", e=exc)

    asyncio.run(_register())


def setup_temporal_retention() -> None:
    """Enforce the configured closed-workflow retention on the namespace.

    Bounds Postgres history growth: without this, per-document
    DocumentIngest / GraphBuild histories pile up in the shared DB.
    Idempotent (UpdateNamespace is a no-op when the TTL already
    matches); failures are warnings so init never blocks on it.
    ``namespace_retention_days <= 0`` leaves the namespace untouched.
    """
    days = settings.temporal.namespace_retention_days
    if days <= 0:
        logger.info("temporal retention unset (days<=0) — leaving namespace as-is")
        return

    import asyncio

    from google.protobuf.duration_pb2 import Duration
    from temporalio.api.namespace.v1 import NamespaceConfig
    from temporalio.api.workflowservice.v1 import UpdateNamespaceRequest
    from temporalio.client import Client

    async def _update() -> None:
        client = await Client.connect(
            settings.temporal.target,
            namespace=settings.temporal.namespace,
        )
        req = UpdateNamespaceRequest(
            namespace=settings.temporal.namespace,
            config=NamespaceConfig(
                workflow_execution_retention_ttl=Duration(
                    seconds=days * 24 * 3600,
                ),
            ),
        )
        try:
            await client.workflow_service.update_namespace(req)
            logger.info(
                "temporal retention set  namespace={ns}  days={d}",
                ns=settings.temporal.namespace, d=days,
            )
        except Exception as exc:
            logger.warning("temporal retention update failed  err={e}", e=exc)

    asyncio.run(_update())


# Global tables live in `public` whatever graph is in play (the registry,
# API keys, the Telegram bot's users/audit).  Everything else is per-graph:
# `migrate_graph_schema` (src/storage/pg_schema.py) runs GRAPH_DDL once per graph under a
# `search_path` pinned to that graph's schema (`public` for `default`, so
# the pre-multi-graph deployment's tables are exactly where they were).
# pg_trgm lives in `extensions`; GRAPH_DDL trigram indexes find
# `gin_trgm_ops` through the `extensions` entry of every graph's search_path.
GLOBAL_DDL: list[str] = [
    _PG_TRGM_DDL, _BOT_USER_DDL, _BOT_REQUEST_DDL, _BOT_INDEXES_DDL,
    # `_TENANTS_DDL` strictly before the two tables that reference it.
    _TENANTS_DDL, _GRAPHS_DDL, _API_KEYS_DDL,
]


def setup_postgres() -> None:
    pg = settings.postgres
    logger.info("postgres setup  host={h}:{p}  db={d}", h=pg.host, p=pg.port, d=pg.db)
    with psycopg.connect(
        pg.dsn, connect_timeout=pg.connect_timeout_s, autocommit=True,
    ) as conn, conn.cursor() as cur:
        for stmt in GLOBAL_DDL:
            cur.execute(stmt)
        _set_database_search_path(cur)
        _bootstrap_registry(cur)
        for graph in _ready_graphs(cur):
            migrate_graph_schema(cur, graph)
    logger.info("postgres setup  done")


def _ready_graphs(cur) -> list:
    from src.tenancy.context import DEFAULT_GRAPH_ID, default_graph_context
    from src.tenancy.registry import _context_from_row

    cur.execute(
        "SELECT id, owner, status, nebula_space, nebula_partition_num, chunks_collection, "
        "er_vec_collection, report_vec_collection, pg_schema, generation "
        "FROM public.graphs WHERE status = 'ready' ORDER BY id"
    )
    cols = [d.name for d in cur.description]
    graphs = [_context_from_row(dict(zip(cols, r, strict=True))) for r in cur.fetchall()]
    # The legacy public tables must always be migrated, even if the
    # `default` registry row is missing or not 'ready'.
    if not any(g.id == DEFAULT_GRAPH_ID for g in graphs):
        graphs.insert(0, default_graph_context())
    return graphs


# ── Milvus ───────────────────────────────────────────────────────────


def setup_milvus() -> None:
    """Verify Milvus reachable; collection lifecycle owned by
    ``MilvusVectorStore`` (Stage 3)."""
    from pymilvus import MilvusClient

    mv = settings.milvus
    logger.info("milvus connectivity  uri={u}", u=mv.uri)
    client = MilvusClient(uri=mv.uri, timeout=mv.timeout_s)
    try:
        collections = client.list_collections()
        logger.info(
            "milvus reachable  existing_collections={c}",
            c=collections,
        )
    finally:
        client.close()


# ── MinIO ────────────────────────────────────────────────────────────


def setup_minio() -> None:
    """Ensure the user-upload bucket exists.  Same MinIO instance the
    Milvus backend uses; this just adds an extra bucket alongside it.
    """
    from src.storage.minio import build_minio_storage

    mn = settings.minio
    logger.info("minio bucket  endpoint={e}  bucket={b}", e=mn.endpoint, b=mn.bucket)
    storage = build_minio_storage()
    storage.ensure_bucket()
    logger.info("minio bucket  done")


# ── entry point ──────────────────────────────────────────────────────


def main() -> None:
    configure_logging(level=settings.api.log_level, json_output=False)
    setup_postgres()
    setup_milvus()
    setup_minio()
    setup_temporal_search_attributes()
    setup_temporal_retention()
    logger.info("setup_db  all done")


if __name__ == "__main__":
    main()
