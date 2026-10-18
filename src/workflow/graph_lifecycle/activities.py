"""Idempotent steps of graph provisioning / deletion.

Each step re-reads the registry row and refuses `default`.  Provision steps
require `provisioning`, teardown steps `deleting`: a stale workflow (e.g. one
whose start the API reported as failed) must never touch a graph that was
resumed or re-created under the same id since.
Sync storage clients run in a thread; the step raises (retryable) when its
strict post-check fails, so the workflow can mark the graph `failed`."""

from __future__ import annotations

import asyncio

import psycopg
from loguru import logger
from temporalio import activity
from temporalio.exceptions import ApplicationError

from src.config import settings
from src.tenancy import graph_repo
from src.tenancy.context import DEFAULT_GRAPH_ID, GraphContext, graph_scoped_id
from src.tenancy.registry import GraphNotFound, get_graph_registry
from src.workflow.client import get_temporal_client
from src.workflow.graph_lifecycle.contracts import GraphLifecycleIn, SetStatusIn


def _protect(graph_id: str) -> None:
    if graph_id == DEFAULT_GRAPH_ID:
        raise ApplicationError(
            "the default graph cannot be provisioned or dropped",
            type="DefaultGraphProtected", non_retryable=True,
        )


async def _load(graph_id: str, *, expect: str, missing_ok: bool = False) -> GraphContext | None:
    """Load the row, which must be in status ``expect``.  Teardown passes
    ``missing_ok``: a missing row then means "already gone" (None) instead
    of a non-retryable error."""
    _protect(graph_id)
    try:
        return await graph_repo.load_context_any_status(graph_id, expect=expect)
    except GraphNotFound as exc:
        if missing_ok:
            return None
        raise ApplicationError(str(exc), type="GraphUnavailable", non_retryable=True) from exc
    except graph_repo.GraphStateChanged as exc:
        raise ApplicationError(str(exc), type="GraphStateChanged", non_retryable=True) from exc


# ── sync bodies (patched in tests) ─────────────────────────────────────

def _nebula_session():
    from src.graph import nebula_store

    with nebula_store._lock:
        pool = nebula_store._shared_pool()
    cfg = settings.nebula
    return nebula_store._acquire_session(pool, cfg.user, cfg.password.get_secret_value())


def _nebula_provision_sync(graph: GraphContext) -> list[str]:
    from src.graph.nebula_schema import ensure_schema, verify_space_schema

    sess = _nebula_session()
    try:
        ensure_schema(sess, graph, use_attempts=60, use_delay_s=1.0)
        return verify_space_schema(sess, graph)
    finally:
        sess.release()


def _nebula_drop_sync(graph: GraphContext) -> None:
    from src.graph.nebula_schema import drop_space

    sess = _nebula_session()
    try:
        drop_space(sess, graph)
    finally:
        sess.release()


def _milvus_client():
    from pymilvus import MilvusClient

    return MilvusClient(uri=settings.milvus.uri, timeout=settings.milvus.timeout_s)


def _milvus_provision_sync(graph: GraphContext) -> list[str]:
    from src.graph.community_vector_store_milvus import MilvusCommunityReportVectorStore
    from src.graph.entity_vector_store_milvus import MilvusEntityVectorStore
    from src.retrieval.vector_index import build_vector_store

    build_vector_store(graph)  # MilvusVectorStore creates the chunks collection on open
    client = _milvus_client()
    try:
        MilvusEntityVectorStore(graph.er_vec_collection, client=client).ensure_collection()
        MilvusCommunityReportVectorStore(graph.report_vec_collection, client=client).ensure_collection()
        names = (graph.chunks_collection, graph.er_vec_collection, graph.report_vec_collection)
        return [n for n in names if not client.has_collection(n)]
    finally:
        client.close()


def _milvus_drop_sync(graph: GraphContext) -> None:
    client = _milvus_client()
    try:
        for name in (graph.chunks_collection, graph.er_vec_collection, graph.report_vec_collection):
            # Belt and braces on top of _protect: only ever drop g_<id>_* names.
            if not name.startswith(f"g_{graph.id}_"):
                raise ValueError(f"refusing to drop collection {name!r}")
            if client.has_collection(name):
                client.drop_collection(name)
    finally:
        client.close()


def _pg_connect():
    pg = settings.postgres
    return psycopg.connect(pg.dsn, connect_timeout=pg.connect_timeout_s, autocommit=True)


def _pg_provision_sync(graph: GraphContext) -> list[str]:
    from src.storage.pg_schema import migrate_graph_schema, missing_graph_tables

    with _pg_connect() as conn, conn.cursor() as cur:
        migrate_graph_schema(cur, graph)
        return missing_graph_tables(cur, graph)


def _pg_drop_sync(graph: GraphContext) -> None:
    from src.storage.pg_schema import drop_graph_schema

    with _pg_connect() as conn, conn.cursor() as cur:
        drop_graph_schema(cur, graph)


# Objects removed per thread hop; purge_minio heartbeats between batches.
_MINIO_PURGE_BATCH = 1000


def _minio_purge_sync(graph: GraphContext) -> int:
    from src.storage.minio import build_minio_storage

    return build_minio_storage().delete_prefix(graph.minio_prefix, limit=_MINIO_PURGE_BATCH)


# Long per-graph workflows (not document-scoped) whose activities write to
# the graph's storage; ids are graph_scoped_id(<prefix>, graph, <uuid hex>).
_GRAPH_WIDE_WORKFLOW_PREFIXES = ("community-build", "analytics-materialize")


async def _inflight_doc_ids(graph: GraphContext) -> list[str]:
    from src.storage.pg_scope import graph_connection

    async with graph_connection(graph, timeout=5) as conn, conn.cursor() as cur:
        # The schema is absent when provisioning failed before provision_pg
        # or a previous delete already ran drop_pg; with no `public` on the
        # search_path the SELECT would raise UndefinedTable on every retry.
        await cur.execute("SELECT to_regclass('documents')")
        row = await cur.fetchone()
        if row is None or row[0] is None:
            return []
        await cur.execute(
            "SELECT id::text FROM documents WHERE status IN ('pending', 'processing')",
        )
        return [r[0] for r in await cur.fetchall()]


async def _running_graph_wide_ids(client, graph: GraphContext) -> list[str]:
    from temporalio.service import RPCError, RPCStatusCode

    ids: list[str] = []
    for prefix in _GRAPH_WIDE_WORKFLOW_PREFIXES:
        # Slugs are [a-z0-9_], so `<prefix>-<id>-` never matches another graph.
        start = graph_scoped_id(prefix, graph.id, "")
        query = f"WorkflowId STARTS_WITH '{start}' AND ExecutionStatus = 'Running'"
        try:
            async for wf in client.list_workflows(query):
                ids.append(wf.id)
        except RPCError as exc:
            if exc.status != RPCStatusCode.INVALID_ARGUMENT:
                raise
            logger.warning(
                "graph delete: visibility rejected {q!r} ({e}); {p} workflows not terminated",
                q=query, e=exc, p=prefix,
            )
    return ids


def _check(step: str, graph: GraphContext, missing: list[str]) -> None:
    if missing:
        raise ApplicationError(f"{step}: graph {graph.id!r} missing {missing}", type="ProvisionIncomplete")


# ── provisioning ──────────────────────────────────────────────────────

@activity.defn
async def provision_nebula(inp: GraphLifecycleIn) -> None:
    graph = await _load(inp.graph_id, expect="provisioning")
    _check("nebula", graph, await asyncio.to_thread(_nebula_provision_sync, graph))


@activity.defn
async def provision_milvus(inp: GraphLifecycleIn) -> None:
    graph = await _load(inp.graph_id, expect="provisioning")
    _check("milvus", graph, await asyncio.to_thread(_milvus_provision_sync, graph))


@activity.defn
async def provision_pg(inp: GraphLifecycleIn) -> None:
    graph = await _load(inp.graph_id, expect="provisioning")
    _check("postgres", graph, await asyncio.to_thread(_pg_provision_sync, graph))


@activity.defn
async def set_graph_status(inp: SetStatusIn) -> None:
    _protect(inp.graph_id)
    await graph_repo.set_status(inp.graph_id, inp.status, inp.error, expect=inp.expect)
    get_graph_registry().invalidate(inp.graph_id)  # this process; others within the TTL


# ── deletion ──────────────────────────────────────────────────────────

@activity.defn
async def terminate_graph_ingests(inp: GraphLifecycleIn) -> int:
    """Terminate the ingest + graph-build workflows of the graph's
    pending/processing documents, and its running community-build /
    analytics-materialize workflows (their activities would otherwise
    re-create dropped Milvus collections).  Queued-but-unstarted documents
    fail on their own: their first activity cannot resolve a `deleting`
    graph."""
    from temporalio.service import RPCError, RPCStatusCode

    graph = await _load(inp.graph_id, expect="deleting", missing_ok=True)
    if graph is None:
        return 0
    client = await get_temporal_client()
    reason = f"graph {graph.id} deleted"
    n = 0

    async def _terminate(wid: str) -> None:
        nonlocal n
        try:
            await client.get_workflow_handle(wid).terminate(reason=reason)
            n += 1
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise

    for doc_id in await _inflight_doc_ids(graph):
        for prefix in ("ingest", "graph"):
            await _terminate(graph_scoped_id(prefix, graph.id, doc_id))
        activity.heartbeat(n)
    for wid in await _running_graph_wide_ids(client, graph):
        await _terminate(wid)
        activity.heartbeat(n)
    logger.info("graph delete: terminated {n} workflow(s)  graph={g}", n=n, g=graph.id)
    return n


@activity.defn
async def drop_nebula(inp: GraphLifecycleIn) -> None:
    graph = await _load(inp.graph_id, expect="deleting", missing_ok=True)
    if graph is not None:
        await asyncio.to_thread(_nebula_drop_sync, graph)


@activity.defn
async def drop_milvus(inp: GraphLifecycleIn) -> None:
    graph = await _load(inp.graph_id, expect="deleting", missing_ok=True)
    if graph is not None:
        await asyncio.to_thread(_milvus_drop_sync, graph)


@activity.defn
async def drop_pg(inp: GraphLifecycleIn) -> None:
    graph = await _load(inp.graph_id, expect="deleting", missing_ok=True)
    if graph is not None:
        await asyncio.to_thread(_pg_drop_sync, graph)


@activity.defn
async def purge_minio(inp: GraphLifecycleIn) -> int:
    """Purge the graph's MinIO prefix in bounded batches, heartbeating
    between them so a large prefix is not killed by the heartbeat timeout."""
    graph = await _load(inp.graph_id, expect="deleting", missing_ok=True)
    if graph is None:
        return 0
    total = 0
    while removed := await asyncio.to_thread(_minio_purge_sync, graph):
        total += removed
        activity.heartbeat(total)
    return total


@activity.defn
async def delete_graph_row(inp: GraphLifecycleIn) -> None:
    # Raises GraphStateChanged for a row no longer `deleting`; the DELETE is
    # conditional too, so a resume racing this step keeps its row.
    if await _load(inp.graph_id, expect="deleting", missing_ok=True) is not None:
        await graph_repo.delete_row(inp.graph_id, expect="deleting")
    get_graph_registry().invalidate(inp.graph_id)


LIFECYCLE_ACTIVITIES = [
    provision_nebula, provision_milvus, provision_pg, set_graph_status,
    terminate_graph_ingests, drop_nebula, drop_milvus, drop_pg, purge_minio, delete_graph_row,
]
