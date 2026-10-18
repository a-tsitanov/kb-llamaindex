"""Writes to the graph registry (``public.graphs``) and status-agnostic reads
for the lifecycle workflows.  Request-path reads go through the cached
:class:`~src.tenancy.registry.GraphRegistry` instead."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

from psycopg.rows import dict_row

from src.tenancy.context import DEFAULT_GRAPH_ID, GraphContext, new_graph_context
from src.tenancy.registry import _COLS, GraphNotFound, _context_from_row

ROW_COLS = _COLS + ", status_error, max_inflight, created_at, updated_at"

ConnFactory = Callable[[], AbstractAsyncContextManager[Any]]


@asynccontextmanager
async def _pool_conn():
    from src.storage.pg_pool import get_pg_pool

    pool = await get_pg_pool()
    async with pool.connection(timeout=5) as conn:
        yield conn


class GraphStateChanged(RuntimeError):
    """The row left the status a lifecycle step requires (e.g. a stale
    delete workflow finding its graph resumed / re-created)."""

    def __init__(self, graph_id: str, status: str, expected: str) -> None:
        super().__init__(f"graph {graph_id!r} is {status!r}, expected {expected!r}")
        self.graph_id, self.status, self.expected = graph_id, status, expected


@dataclass(frozen=True)
class CreateOutcome:
    kind: Literal["created", "resumed", "conflict"]
    status: str


async def create_or_resume(
    graph_id: str,
    owner: str,
    partition_num: int,
    *,
    conn_factory: ConnFactory | None = None,
) -> CreateOutcome:
    """Insert a `provisioning` row; a `failed` row is reset to
    `provisioning` (resume); any other existing row is a conflict."""
    g = new_graph_context(
        graph_id, nebula_partition_num=partition_num
    )  # validates, rejects default
    async with (conn_factory or _pool_conn)() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "INSERT INTO public.graphs (id, owner, status, nebula_space, nebula_partition_num, "
                "chunks_collection, er_vec_collection, report_vec_collection, pg_schema, generation) "
                "VALUES (%s, %s, 'provisioning', %s, %s, %s, %s, %s, %s, "
                "(extract(epoch from clock_timestamp()) * 1000000)::bigint) "
                "ON CONFLICT (id) DO NOTHING RETURNING id",
                (
                    g.id,
                    owner,
                    g.nebula_space,
                    g.nebula_partition_num,
                    g.chunks_collection,
                    g.er_vec_collection,
                    g.report_vec_collection,
                    g.pg_schema,
                ),
            )
            if await cur.fetchone() is not None:
                outcome = CreateOutcome("created", "provisioning")
            else:
                # New generation: a failed delete may already have dropped
                # storage that long-lived processes still cache under the
                # old `id#generation` key.
                await cur.execute(
                    "UPDATE public.graphs SET status = 'provisioning', status_error = '', "
                    "generation = (extract(epoch from clock_timestamp()) * 1000000)::bigint, "
                    "updated_at = now() WHERE id = %s AND status = 'failed' RETURNING id",
                    (g.id,),
                )
                if await cur.fetchone() is not None:
                    outcome = CreateOutcome("resumed", "provisioning")
                else:
                    await cur.execute("SELECT status FROM public.graphs WHERE id = %s", (g.id,))
                    row = await cur.fetchone()
                    outcome = CreateOutcome("conflict", row["status"] if row else "unknown")
        await conn.commit()
    return outcome


async def get_row(graph_id: str, *, conn_factory: ConnFactory | None = None) -> dict | None:
    async with (conn_factory or _pool_conn)() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"SELECT {ROW_COLS} FROM public.graphs WHERE id = %s", (graph_id,))
        return await cur.fetchone()


async def list_rows(*, conn_factory: ConnFactory | None = None) -> list[dict]:
    async with (conn_factory or _pool_conn)() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"SELECT {ROW_COLS} FROM public.graphs ORDER BY id")
        return await cur.fetchall()


async def patch_row(
    graph_id: str,
    *,
    owner: str | None,
    max_inflight: int | None,
    conn_factory: ConnFactory | None = None,
) -> dict | None:
    async with (conn_factory or _pool_conn)() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "UPDATE public.graphs SET owner = COALESCE(%s, owner), "
                "max_inflight = COALESCE(%s, max_inflight), updated_at = now() "
                f"WHERE id = %s RETURNING {ROW_COLS}",
                (owner, max_inflight, graph_id),
            )
            row = await cur.fetchone()
        await conn.commit()
    return row


async def set_status(
    graph_id: str,
    status: str,
    error: str = "",
    *,
    expect: str | None = None,
    conn_factory: ConnFactory | None = None,
) -> bool:
    """Set ``status``; with ``expect`` only when the row is currently in that
    status (a concurrent transition wins).  Returns whether a row changed."""
    q = "UPDATE public.graphs SET status = %s, status_error = %s, updated_at = now() WHERE id = %s"
    params: tuple = (status, error[:2000], graph_id)
    if expect is not None:
        q += " AND status = %s"
        params += (expect,)
    async with (conn_factory or _pool_conn)() as conn:
        async with conn.cursor() as cur:
            await cur.execute(q + " RETURNING id", params)
            changed = await cur.fetchone() is not None
        await conn.commit()
    return changed


async def mark_deleting(graph_id: str, *, conn_factory: ConnFactory | None = None) -> str | None:
    """Set `deleting` unless the row is `provisioning`; return the previous
    status (None = no such graph; `provisioning` = row left unchanged).
    One locked statement, so a concurrent resume cannot slip in between
    the check and the write."""
    if graph_id == DEFAULT_GRAPH_ID:
        raise ValueError("the default graph is not deletable")
    async with (conn_factory or _pool_conn)() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "WITH old AS (SELECT id, status AS prev FROM public.graphs WHERE id = %s FOR UPDATE), "
                "upd AS (UPDATE public.graphs g SET status = 'deleting', updated_at = now() "
                "FROM old WHERE g.id = old.id AND old.prev <> 'provisioning' RETURNING g.id) "
                "SELECT prev FROM old",
                (graph_id,),
            )
            row = await cur.fetchone()
        await conn.commit()
    return row["prev"] if row else None


async def delete_row(
    graph_id: str,
    *,
    expect: str | None = None,
    conn_factory: ConnFactory | None = None,
) -> bool:
    """Delete the row; with ``expect`` only when it is currently in that
    status.  Returns whether a row was deleted."""
    q = "DELETE FROM public.graphs WHERE id = %s"
    params: tuple = (graph_id,)
    if expect is not None:
        q += " AND status = %s"
        params += (expect,)
    async with (conn_factory or _pool_conn)() as conn:
        async with conn.cursor() as cur:
            await cur.execute(q + " RETURNING id", params)
            deleted = await cur.fetchone() is not None
        await conn.commit()
    return deleted


async def load_context_any_status(
    graph_id: str,
    *,
    expect: str | None = None,
    conn_factory: ConnFactory | None = None,
) -> GraphContext:
    """Load the row regardless of the registry's `ready` gate; with
    ``expect`` raise :class:`GraphStateChanged` unless it is in that status."""
    row = await get_row(graph_id, conn_factory=conn_factory)
    if row is None:
        raise GraphNotFound(graph_id)
    if expect is not None and row["status"] != expect:
        raise GraphStateChanged(graph_id, row["status"], expect)
    return _context_from_row(row)


async def list_ready_contexts(*, conn_factory: ConnFactory | None = None) -> list[GraphContext]:
    async with (conn_factory or _pool_conn)() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            f"SELECT {ROW_COLS} FROM public.graphs WHERE status = 'ready' ORDER BY id",
        )
        return [_context_from_row(r) for r in await cur.fetchall()]
