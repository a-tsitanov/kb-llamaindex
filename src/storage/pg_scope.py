"""Graph-scoped Postgres connections via ``search_path``.

Each graph's tables live in its own schema (``public`` for `default`);
pg_trgm lives in ``extensions``, the only other schema on the path.  The
SET is committed immediately so a later rollback inside the caller's block
cannot silently revert it; the pools' ``reset`` callbacks restore the
default path when a connection returns, so no schema leaks into the next
checkout (bot tables, another graph)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from psycopg import sql

from src.storage.pg_pool import get_pg_pool
from src.tenancy.context import GraphContext


def search_path_sql(graph: GraphContext) -> sql.Composed:
    # `extensions` (pg_trgm) instead of `public`: a graph schema missing a
    # table must fail loudly, not fall through to `default`'s public table
    # (R-P5).  Global tables are always addressed as `public.<t>`.
    return sql.SQL("SET search_path TO {}, extensions").format(sql.Identifier(graph.pg_schema))


async def reset_search_path(conn) -> None:
    await conn.execute("RESET search_path")
    await conn.commit()


def reset_search_path_sync(conn) -> None:
    conn.execute("RESET search_path")
    conn.commit()


@asynccontextmanager
async def graph_connection(
    graph: GraphContext, *, timeout: float | None = None,
) -> AsyncIterator:
    pool = await get_pg_pool()
    cm = pool.connection() if timeout is None else pool.connection(timeout=timeout)
    async with cm as conn:
        await conn.execute(search_path_sql(graph))
        await conn.commit()
        yield conn


@contextmanager
def graph_sync_connection(graph: GraphContext, *, timeout: float | None = None) -> Iterator:
    from src.storage.pg_sync_pool import get_pg_sync_pool

    with get_pg_sync_pool().connection(timeout=timeout) as conn:
        conn.execute(search_path_sql(graph))
        conn.commit()
        yield conn


__all__ = [
    "graph_connection",
    "graph_sync_connection",
    "reset_search_path",
    "reset_search_path_sync",
    "search_path_sql",
]
