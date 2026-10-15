"""Postgres access for the entity search mirror.

Pure query builders (asserted exactly, no live DB) + a thin async
repository over the process pool. The graph is canonical; this table is
a trigram-indexed copy so name lookup runs here instead of scanning
Nebula.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from src.storage.pg_pool import get_pg_pool

_COLUMNS = "vid, name, label, description, mention_count"
_MODES = ("exact", "prefix", "substring")


def build_entity_search_query(
    query: str, *, mode: str, label: str | None, limit: int,
) -> tuple[str, list[Any]]:
    """One name-search query. `mode`: exact / prefix / substring."""
    if mode not in _MODES:
        raise ValueError(f"unknown mode {mode!r}, expected one of {list(_MODES)}")
    params: list[Any] = []
    order = "mention_count DESC"
    if mode == "exact":
        where = "name = %s"
        params.append(query)
    elif mode == "prefix":
        where = "name ILIKE %s"
        params.append(f"{query}%")
    else:  # substring — trigram; `%%` is the escaped `%` operator
        where = "name %% %s"
        params.append(query)
        order = "similarity(name, %s) DESC, mention_count DESC"
    if label is not None:
        where += " AND label = %s"
        params.append(label)
    # similarity() in ORDER BY needs its own bound param, appended last so
    # it lands after the WHERE params.
    if mode == "substring":
        params.append(query)
    params.append(int(limit))
    sql = (
        f"SELECT {_COLUMNS} FROM entity WHERE {where} "
        f"ORDER BY {order} LIMIT %s"
    )
    return sql, params


def build_persons_by_surname_query(
    stems: list[str], *, limit: int,
) -> tuple[str, list[Any]]:
    """Person rows whose name contains one of the surname stems, any word
    order ("Поляков С.Н.", "С.Н. Поляков"). ILIKE with a leading `%` is
    served by the trigram GIN index.

    Stems come with `ё` folded to `е`; ILIKE does not fold it, so each `е`
    also gets a `ё` variant ("королев" finds "Королёв")."""
    patterns: list[str] = []
    for stem in stems:
        variants = [stem] + [
            stem[:i] + "ё" + stem[i + 1:] for i, ch in enumerate(stem) if ch == "е"
        ]
        patterns.extend(f"%{v}%" for v in variants if f"%{v}%" not in patterns)
    sql = (
        f"SELECT {_COLUMNS} FROM entity "
        "WHERE label = 'Person' AND name ILIKE ANY(%s) "
        "ORDER BY mention_count DESC LIMIT %s"
    )
    return sql, [patterns, int(limit)]


class EntitySearchRepository:
    """Async wrapper over the `entity` table."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn

    @asynccontextmanager
    async def _conn(self) -> AsyncIterator[psycopg.AsyncConnection]:
        if self._dsn is None:
            pool = await get_pg_pool()
            # timeout=1 bounds connection acquisition during a Postgres
            # outage so `_entity_table_names`'s fail-soft catch fires in
            # ~1s instead of stalling behind the pool's full pool_timeout_s
            # (~30s) — mirrors entity_table.mirror_entities' timeout=1.
            async with pool.connection(timeout=1) as conn:
                yield conn
        else:
            async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
                yield conn

    async def search(
        self, query: str, *, mode: str = "substring",
        label: str | None = None, limit: int = 10,
    ) -> list[dict[str, Any]]:
        if not (query or "").strip():
            return []
        sql, params = build_entity_search_query(
            query, mode=mode, label=label, limit=limit,
        )
        async with self._conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())


    async def persons_by_surname(
        self, stems: list[str], *, limit: int = 200,
    ) -> list[dict[str, Any]]:
        stems = [s for s in stems if s]
        if not stems:
            return []
        sql, params = build_persons_by_surname_query(stems, limit=limit)
        async with self._conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return list(await cur.fetchall())


__all__ = [
    "EntitySearchRepository", "build_entity_search_query", "build_persons_by_surname_query",
]
