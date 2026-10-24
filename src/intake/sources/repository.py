"""Реестр источников: весь SQL по таблицам ``source`` и ``source_slug``.

Личность канала — ``peer_id``; слаг лишь его текущее имя (почему — в
комментарии к ``_SOURCE_DDL`` в ``src/storage/pg_schema.py``).  Схему
инициализирует ``scripts/setup_db.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, NamedTuple

import psycopg
from psycopg.rows import dict_row

from src.intake.sources.channel_key import channel_key, normalize_slug
from src.storage.pg_scope import graph_connection, search_path_sql
from src.tenancy.context import GraphContext

_COLS = "peer_id, slug, title, group_name, trust, state, added_by, note"


class SourceRow(NamedTuple):
    peer_id: int
    slug: str
    title: str
    group_name: str
    # None = «как у группы»; это не то же самое, что 0.
    trust: float | None
    state: str
    added_by: str
    note: str

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> SourceRow:
        return cls(**{f: row[f] for f in cls._fields})


class SourceRepository:
    """Подключённые каналы графа.

    Соединение — как у ``IntakeRepository``: общий пул, а явный ``dsn``
    оставляет прямое подключение для одноразовых скриптов.
    """

    def __init__(self, dsn: str | None = None, *, graph: GraphContext) -> None:
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

    async def add(
        self, peer_id: int, slug: str, title: str, group_name: str,
        *, added_by: str,
    ) -> None:
        """Подключить канал (UPSERT по ``peer_id``).

        Канал, из которого раньше вышли, подключают снова: простой INSERT
        упал бы на первичном ключе, поэтому конфликт поднимает строку в
        ``active``, сбрасывает ``left_at`` и обновляет описание.  Доверие и
        заметка оператора при этом сохраняются — повторное подключение не
        должно молча стирать настроенное.

        Строка источника и строка слага пишутся одной транзакцией: канал
        без слага в истории не нашёл бы свои документы в отчёте.  В
        ``source.slug`` остаётся имя как его дал телеграм (``@Five``), а в
        ``source_slug`` пишется ключ (``channel_key``): так же называет канал
        фидер в ``documents.source_channel``.
        """
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO source "
                    "(peer_id, slug, title, group_name, added_by) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (peer_id) DO UPDATE SET "
                    "state = 'active', left_at = NULL, "
                    "group_name = EXCLUDED.group_name, "
                    "slug = EXCLUDED.slug, title = EXCLUDED.title, "
                    "added_by = EXCLUDED.added_by",
                    (peer_id, slug, title, group_name, added_by),
                )
                await cur.execute(
                    "INSERT INTO source_slug (peer_id, slug) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (peer_id, channel_key(slug, peer_id)),
                )
            await conn.commit()

    async def _one(
        self, where: str, param: Any, order: str = "",
    ) -> SourceRow | None:
        async with self._conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {_COLS} FROM source WHERE {where}{order}", (param,),
            )
            row = await cur.fetchone()
        return SourceRow.from_dict(row) if row else None

    async def get(self, peer_id: int) -> SourceRow | None:
        return await self._one("peer_id = %s", peer_id)

    async def list_active(self) -> list[SourceRow]:
        async with self._conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {_COLS} FROM source WHERE state = 'active' "
                "ORDER BY slug"
            )
            rows = await cur.fetchall()
        return [SourceRow.from_dict(r) for r in rows]

    async def _update(self, sql: str, params: tuple) -> bool:
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, params)
                changed = cur.rowcount > 0
            await conn.commit()
        return changed

    async def set_trust(self, peer_id: int, trust: float | None) -> bool:
        """``None`` сбрасывает доверие к групповому."""
        return await self._update(
            "UPDATE source SET trust = %s WHERE peer_id = %s", (trust, peer_id),
        )

    async def set_group(self, peer_id: int, group_name: str) -> bool:
        return await self._update(
            "UPDATE source SET group_name = %s WHERE peer_id = %s",
            (group_name, peer_id),
        )

    async def mark_left(self, peer_id: int) -> bool:
        """Выйти из канала, не удаляя строку: история и доверие остаются."""
        return await self._update(
            "UPDATE source SET state = 'left', left_at = now() "
            "WHERE peer_id = %s",
            (peer_id,),
        )

    async def trust_for_channel(self, slug: str) -> float | None:
        """Личное доверие к каналу по слагу документа.

        Идёт через ``source_slug``: документ записан под слагом на момент
        приёма, а канал мог уже сменить имя.  Покинутый канал и неизвестный
        слаг дают None — вызывающий откатывается к групповому доверию.
        ``slug`` — как в документе (без «@»); к ключу его приводит
        ``normalize_slug``, регистр и «@» значения не имеют.
        """
        key = normalize_slug(slug)
        if not key:
            return None
        async with self._conn() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT s.trust FROM source_slug ss "
                "JOIN source s ON s.peer_id = ss.peer_id "
                "WHERE ss.slug = %s AND s.state = 'active' "
                # `ltrim(lower(..), '@')` — SQL-копия правила `channel_key.normalize_slug`
                # (вторая — `_MINE` в report.py); правишь Python — правь обе.
                # Слаг освобождают и перехватывают: доверие берём у канала,
                # который несёт его сейчас, а не у первого попавшегося.
                "ORDER BY (COALESCE(NULLIF(ltrim(lower(s.slug), '@'), ''), "
                "s.peer_id::text) = ss.slug) DESC, ss.seen_at DESC, "
                "s.peer_id DESC LIMIT 1",
                (key,),
            )
            row = await cur.fetchone()
        return row[0] if row else None

    async def remember_slug(
        self, peer_id: int, slug: str, *, display: str | None = None,
    ) -> None:
        """Записать ключ слага в историю канала; повтор не ошибка.

        ``display`` — новое человеческое имя: если оно дано, ``source.slug``
        обновляется в той же транзакции (канал переименовали).
        """
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO source_slug (peer_id, slug) VALUES (%s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (peer_id, channel_key(slug, peer_id)),
                )
                if display is not None:
                    await cur.execute(
                        "UPDATE source SET slug = %s WHERE peer_id = %s",
                        (display, peer_id),
                    )
            await conn.commit()
