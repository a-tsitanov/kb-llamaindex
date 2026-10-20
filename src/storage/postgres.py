"""Async Postgres client for the ingestion pipeline's own writes.

Статус обработки документа (``doc_processing``) и аудит разрешённых
конфликтов фактов (``fact_supersede``).  Реестр приёма — таблица
``documents`` целиком, со всеми её выборками и агрегациями — живёт в
``src/intake/repository.py``.
Schema is the one initialised by ``scripts/setup_db.py`` (Stage 1).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import psycopg

from src.storage.pg_scope import graph_connection, search_path_sql
from src.tenancy.context import GraphContext


class AsyncPostgres:
    """Thin async wrapper around the pipeline's status / audit writes.

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

    async def update_status(
        self,
        doc_id: uuid.UUID,
        *,
        status: str,
        error: str = "",
        summary: str = "",
    ) -> None:
        # Именно UPDATE, а не UPSERT: отказ приёма (`IntakeRepository.reject`)
        # удаляет строку обработки, и запоздалая активность уже отменённого
        # воркфлоу не должна её воскресить.
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE doc_processing
                       SET status = %s,
                           error = %s,
                           summary = COALESCE(NULLIF(%s, ''), summary),
                           updated_at = NOW()
                     WHERE doc_id = %s
                    """,
                    (status, error, summary, str(doc_id)),
                )
            await conn.commit()

    async def record_fact_conflicts(self, rows: list[dict[str, Any]]) -> None:
        """Append resolved fact conflicts to the `fact_supersede` audit log.

        `rows` are `dataclasses.asdict(EdgeConflict)` shapes (see
        `src/graph/edge_conflicts.py`).  The graph stores only the winning
        belief, so this log is the record of what the losing source claimed.
        """
        if not rows:
            return
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(
                    """
                    INSERT INTO fact_supersede
                        (src, rel, tgt, stored_polarity, new_polarity,
                         stored_trust, new_trust, stored_doc_id, new_doc_id, winner)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (r.get("src", ""), r.get("rel", ""), r.get("tgt", ""),
                         r.get("stored_polarity", ""), r.get("new_polarity", ""),
                         float(r.get("stored_trust", 0.0)), float(r.get("new_trust", 0.0)),
                         r.get("stored_doc_id", ""), r.get("new_doc_id", ""),
                         r.get("winner", ""))
                        for r in rows
                    ],
                )
            await conn.commit()
