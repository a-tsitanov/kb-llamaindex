"""PG-backed graph registry (``public.graphs``), TTL-cached per process."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from loguru import logger

from src.tenancy.context import (
    DEFAULT_GRAPH_ID,
    GraphContext,
    InvalidGraphId,
    default_graph_context,
    validate_graph_id,
)

_COLS = (
    "id, owner, status, nebula_space, nebula_partition_num, chunks_collection, "
    "er_vec_collection, report_vec_collection, pg_schema"
)


class GraphNotFound(LookupError):
    def __init__(self, graph_id: str) -> None:
        super().__init__(f"graph not found: {graph_id!r}")
        self.graph_id = graph_id


class GraphNotReady(RuntimeError):
    def __init__(self, graph_id: str, status: str) -> None:
        super().__init__(f"graph {graph_id!r} is {status}")
        self.graph_id, self.status = graph_id, status


async def _load_row_from_pg(graph_id: str) -> dict | None:
    from psycopg.rows import dict_row

    from src.storage.pg_pool import get_pg_pool

    pool = await get_pg_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"SELECT {_COLS} FROM public.graphs WHERE id = %s", (graph_id,))
        return await cur.fetchone()


def _context_from_row(row: dict) -> GraphContext:
    gid = row["id"]
    return GraphContext(
        id=gid,
        nebula_space=row["nebula_space"],
        nebula_partition_num=int(row["nebula_partition_num"]),
        chunks_collection=row["chunks_collection"],
        er_vec_collection=row["er_vec_collection"],
        report_vec_collection=row["report_vec_collection"],
        pg_schema=row["pg_schema"],
        minio_prefix="" if gid == DEFAULT_GRAPH_ID else f"{gid}/",
    )


class GraphRegistry:
    def __init__(
        self,
        loader: Callable[[str], Awaitable[dict | None]] | None = None,
        ttl_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._loader = loader or _load_row_from_pg
        self._ttl = ttl_s
        self._clock = clock
        self._cache: dict[str, tuple[float, dict | None]] = {}
        self._warned_default = False

    def invalidate(self, graph_id: str | None = None) -> None:
        if graph_id is None:
            self._cache.clear()
        else:
            self._cache.pop(graph_id, None)

    async def get_row(self, graph_id: str) -> dict | None:
        now = self._clock()
        hit = self._cache.get(graph_id)
        if hit is not None and now - hit[0] < self._ttl:
            return hit[1]
        row = await self._loader(graph_id)
        self._cache[graph_id] = (now, row)
        return row

    async def get(self, graph_id: str) -> GraphContext:
        try:
            validate_graph_id(graph_id)
        except InvalidGraphId:
            raise GraphNotFound(graph_id) from None
        try:
            row = await self.get_row(graph_id)
        except Exception:
            if graph_id != DEFAULT_GRAPH_ID:
                raise
            row = None
        if row is None:
            if graph_id == DEFAULT_GRAPH_ID:
                if not self._warned_default:
                    logger.warning("graph registry: no 'default' row; using built-in default context")
                    self._warned_default = True
                return default_graph_context()
            raise GraphNotFound(graph_id)
        if row["status"] != "ready":
            raise GraphNotReady(graph_id, row["status"])
        return _context_from_row(row)


_registry: GraphRegistry | None = None


def get_graph_registry() -> GraphRegistry:
    global _registry
    if _registry is None:
        _registry = GraphRegistry()
    return _registry


def reset_graph_registry_for_tests() -> None:
    global _registry
    _registry = None
