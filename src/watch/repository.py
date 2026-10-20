"""Postgres access for entity watch: journals, subscriptions, events, feed.

Schema: ``scripts/setup_db.py`` (``_WATCH_DDL``). Design:
``docs/superpowers/specs/2026-10-15-entity-watch-design.md``.

Ingest appends to the journals (``entity_mention``, ``edge_new``); the
monitor sweep reads them past a per-journal cursor and writes
``watch_event`` rows for subscribed entities; the MCP tools read the feed.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from src.storage.pg_scope import graph_connection, search_path_sql
from src.tenancy.context import GraphContext

# Journal table -> its insert-time column. Doubles as the whitelist for the
# table name spliced into read_journal's SQL.
JOURNALS: dict[str, str] = {
    "entity_mention": "ingested_at",
    "edge_new": "created_at",
    "fact_supersede": "decided_at",
}

# A row becomes visible to the sweep only once it is this old. Ids come
# from a sequence at INSERT time but commit in any order; without the lag a
# row with a lower id committing after a higher one is already read would
# fall behind the cursor and never be seen.
_SETTLE = "interval '60 seconds'"

_INSERT_MENTION = """
INSERT INTO entity_mention
    (entity_vid, doc_id, entity_name, label, doc_date, mention_count, backfill)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (entity_vid, doc_id) DO NOTHING
"""

_INSERT_EDGE = """
INSERT INTO edge_new
    (src_vid, src_name, src_label, tgt_vid, tgt_name, tgt_label, rel,
     doc_id, doc_date, backfill)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (src_vid, tgt_vid) DO NOTHING
"""

_INSERT_EVENT = """
INSERT INTO watch_event
    (entity_vid, entity_name, kind, doc_id, doc_date, detail, why,
     source_table, source_id, dedup_key)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (dedup_key) DO NOTHING
"""

_UPSERT_CURSOR = """
INSERT INTO monitor_cursor (name, last_id, updated_at) VALUES (%s, %s, now())
ON CONFLICT (name) DO UPDATE SET last_id = EXCLUDED.last_id, updated_at = now()
"""

# ER merge: move every row of the loser vid onto the canonical one. A loser
# row whose canonical twin already exists (same owner / same doc / same
# pair) is dropped first, so the UPDATE never hits a unique violation.
_REWRITE_SQL: tuple[str, ...] = (
    "DELETE FROM watch w WHERE w.entity_vid = %(l)s AND EXISTS "
    "(SELECT 1 FROM watch c WHERE c.owner = w.owner AND c.entity_vid = %(c)s)",
    "UPDATE watch SET entity_vid = %(c)s, entity_name = %(n)s WHERE entity_vid = %(l)s",
    "DELETE FROM entity_mention m WHERE m.entity_vid = %(l)s AND EXISTS "
    "(SELECT 1 FROM entity_mention c WHERE c.doc_id = m.doc_id AND c.entity_vid = %(c)s)",
    "UPDATE entity_mention SET entity_vid = %(c)s, entity_name = %(n)s "
    "WHERE entity_vid = %(l)s",
    "DELETE FROM edge_new x WHERE x.src_vid = %(l)s AND EXISTS "
    "(SELECT 1 FROM edge_new c WHERE c.src_vid = %(c)s AND c.tgt_vid = x.tgt_vid)",
    "UPDATE edge_new SET src_vid = %(c)s, src_name = %(n)s WHERE src_vid = %(l)s",
    "DELETE FROM edge_new x WHERE x.tgt_vid = %(l)s AND EXISTS "
    "(SELECT 1 FROM edge_new c WHERE c.tgt_vid = %(c)s AND c.src_vid = x.src_vid)",
    "UPDATE edge_new SET tgt_vid = %(c)s, tgt_name = %(n)s WHERE tgt_vid = %(l)s",
    # loser -> canon became canon -> canon
    "DELETE FROM edge_new WHERE src_vid = tgt_vid AND src_vid = %(c)s",
    "UPDATE watch_event SET entity_vid = %(c)s, entity_name = %(n)s "
    "WHERE entity_vid = %(l)s",
)

# Events visible to one owner: on a subscribed entity, detected after the
# subscription, of a subscribed kind, not muted.
_VISIBLE = """
FROM watch_event e
JOIN watch w ON w.entity_vid = e.entity_vid AND w.owner = %s
LEFT JOIN watch_seen s ON s.event_id = e.id AND s.owner = w.owner
LEFT JOIN documents d ON d.id = e.doc_id
WHERE e.detected_at >= w.created_at
  AND (cardinality(w.kinds) = 0 OR e.kind = ANY(w.kinds))
  AND (w.muted_until IS NULL OR w.muted_until < now())
"""


class WatchRepository:
    """Async wrapper over the entity-watch tables of one graph (its schema)."""

    def __init__(self, dsn: str | None = None, *, graph: GraphContext) -> None:
        # None → shared pool; explicit dsn → legacy direct connect.
        self._dsn = dsn
        self._graph = graph

    @property
    def graph(self) -> GraphContext:
        return self._graph

    @asynccontextmanager
    async def _conn(self) -> AsyncIterator[psycopg.AsyncConnection]:
        if self._dsn is None:
            # Short acquisition budget: journal writes sit on the ingest path
            # and are fail-open, so a Postgres outage must cost seconds, not
            # the pool's full timeout.
            async with graph_connection(self._graph, timeout=5) as conn:
                yield conn
        else:
            async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
                await conn.execute(search_path_sql(self._graph))
                await conn.commit()
                yield conn

    # ── journals (ingest) ───────────────────────────────────────────

    async def record_mentions(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(_INSERT_MENTION, [
                    (r["entity_vid"], r["doc_id"], r["entity_name"], r.get("label", ""),
                     r.get("doc_date"), int(r.get("mention_count") or 0),
                     bool(r.get("backfill", False)))
                    for r in rows
                ])
            await conn.commit()

    async def record_new_edges(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(_INSERT_EDGE, [
                    (r["src_vid"], r["src_name"], r.get("src_label", ""),
                     r["tgt_vid"], r["tgt_name"], r.get("tgt_label", ""),
                     r.get("rel", ""), r["doc_id"], r.get("doc_date"),
                     bool(r.get("backfill", False)))
                    for r in rows
                ])
            await conn.commit()

    # ── ER merge ────────────────────────────────────────────────────

    async def rewrite_vid(self, loser_vid: str, canon_vid: str, canon_name: str) -> None:
        if loser_vid == canon_vid:
            return
        params = {"l": loser_vid, "c": canon_vid, "n": canon_name}
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                for sql in _REWRITE_SQL:
                    await cur.execute(sql, params)
            await conn.commit()

    # ── sweep ───────────────────────────────────────────────────────

    async def cursor(self, name: str) -> int:
        async with self._conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT last_id FROM monitor_cursor WHERE name = %s", (name,))
            row = await cur.fetchone()
        return int(row["last_id"]) if row else 0

    async def read_journal(self, name: str, *, after_id: int, limit: int) -> list[dict[str, Any]]:
        ts = JOURNALS.get(name)
        if ts is None:
            raise ValueError(f"unknown journal {name!r}, expected one of {sorted(JOURNALS)}")
        sql = (
            f"SELECT * FROM {name} WHERE id > %s AND {ts} < now() - {_SETTLE} "
            "ORDER BY id LIMIT %s"
        )
        async with self._conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, (int(after_id), int(limit)))
            return list(await cur.fetchall())

    async def watched(self) -> dict[str, str]:
        """vid -> name of every entity anyone watches."""
        async with self._conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT DISTINCT entity_vid, entity_name FROM watch")
            return {r["entity_vid"]: r["entity_name"] for r in await cur.fetchall()}

    @staticmethod
    def _event_params(events: list[dict[str, Any]]) -> list[tuple]:
        return [
            (e["entity_vid"], e["entity_name"], e["kind"], e.get("doc_id"),
             e.get("doc_date"), json.dumps(e.get("detail") or {}, ensure_ascii=False),
             e.get("why", ""), e.get("source_table", ""), e.get("source_id"),
             e["dedup_key"])
            for e in events
        ]

    async def save_events(self, journal: str, events: list[dict[str, Any]], *, last_id: int) -> None:
        """Insert events (dedup on key) and advance the journal cursor, atomically."""
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                if events:
                    await cur.executemany(_INSERT_EVENT, self._event_params(events))
                await cur.execute(_UPSERT_CURSOR, (journal, int(last_id)))
            await conn.commit()

    async def insert_events(self, events: list[dict[str, Any]]) -> None:
        """Записать события БЕЗ курсора — для детекторов без журнала.

        Единственный такой детектор — рост риска: прежнее значение лежит
        на узле графа, продвигать по нему нечего.  Отдельный метод, а не
        ``save_events`` с фиктивным курсором: запись фиктивной строки в
        ``monitor_cursor`` создала бы вид журнала, которого нет.
        """
        if not events:
            return
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(_INSERT_EVENT, self._event_params(events))
            await conn.commit()

    # ── subscriptions ───────────────────────────────────────────────

    async def add_watch(
        self, owner: str, vid: str, name: str, *, kinds: list[str] | None = None,
        note: str = "", webhook_url: str = "",
    ) -> None:
        """Создать или обновить подписку.

        ``webhook_url`` пусто = доставки нет, только лента.  Повторная
        подписка адресат ПЕРЕЗАПИСЫВАЕТ, в том числе пустым: это
        единственный способ отключить доставку, оставив подписку, и
        «подписаться заново без адресата» должно значить именно то, что
        написано.
        """
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO watch "
                    "(owner, entity_vid, entity_name, kinds, note, webhook_url) "
                    "VALUES (%s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (owner, entity_vid) DO UPDATE SET "
                    "kinds = EXCLUDED.kinds, note = EXCLUDED.note, "
                    "webhook_url = EXCLUDED.webhook_url, muted_until = NULL",
                    (owner, vid, name, list(kinds or []), note, webhook_url),
                )
            await conn.commit()

    async def remove_watch(self, owner: str, vid: str) -> bool:
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM watch WHERE owner = %s AND entity_vid = %s", (owner, vid),
                )
                removed = cur.rowcount
            await conn.commit()
        return bool(removed)

    async def list_watch(self, owner: str) -> list[dict[str, Any]]:
        async with self._conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT entity_vid, entity_name, kinds, muted_until, note, "
                "webhook_url, daily_push_limit, created_at "
                "FROM watch WHERE owner = %s ORDER BY created_at",
                (owner,),
            )
            return list(await cur.fetchall())

    # ── feed ────────────────────────────────────────────────────────

    async def feed(self, owner: str, *, include_acked: bool, limit: int) -> list[dict[str, Any]]:
        sql = (
            "SELECT e.id, e.entity_vid, e.entity_name, e.kind, e.doc_id, e.doc_date, "
            "e.detail, e.why, e.detected_at, s.seen_at, s.acked_at, d.path AS doc_path "
            + _VISIBLE
            + ("" if include_acked else "  AND s.acked_at IS NULL\n")
            + "ORDER BY e.detected_at DESC, e.id DESC LIMIT %s"
        )
        async with self._conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, (owner, int(limit)))
            return list(await cur.fetchall())

    async def mark_seen(self, owner: str, event_ids: list[int]) -> None:
        if not event_ids:
            return
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.executemany(
                    "INSERT INTO watch_seen (owner, event_id, seen_at) VALUES (%s, %s, now()) "
                    "ON CONFLICT (owner, event_id) DO UPDATE SET "
                    "seen_at = COALESCE(watch_seen.seen_at, now())",
                    [(owner, int(i)) for i in event_ids],
                )
            await conn.commit()

    async def ack(
        self, owner: str, *, event_ids: list[int] | None = None, all_events: bool = False,
    ) -> int:
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                if all_events:
                    await cur.execute(
                        "INSERT INTO watch_seen (owner, event_id, seen_at, acked_at) "
                        "SELECT w.owner, e.id, now(), now() "
                        "FROM watch_event e JOIN watch w ON w.entity_vid = e.entity_vid "
                        "AND w.owner = %s WHERE e.detected_at >= w.created_at "
                        "ON CONFLICT (owner, event_id) DO UPDATE SET acked_at = now()",
                        (owner,),
                    )
                    n = cur.rowcount
                else:
                    ids = [int(i) for i in (event_ids or [])]
                    if not ids:
                        return 0
                    await cur.executemany(
                        "INSERT INTO watch_seen (owner, event_id, seen_at, acked_at) "
                        "VALUES (%s, %s, now(), now()) "
                        "ON CONFLICT (owner, event_id) DO UPDATE SET acked_at = now()",
                        [(owner, i) for i in ids],
                    )
                    n = len(ids)
            await conn.commit()
        return int(n or 0)



    # ── доставка ────────────────────────────────────────────────────

    async def due_deliveries(
        self, *, limit: int = 100, max_attempts: int = 3,
    ) -> list[dict[str, Any]]:
        """События, которые пора отправить, вместе с адресатом подписки.

        Критерии — те же, что у ленты (`_VISIBLE`): подписанная сущность,
        подписанный вид, событие ПОСЛЕ создания подписки, подписка не в
        мюте.  Плюс два своих: у подписки есть адресат и это событие ей
        ещё не отправляли.

        Повтор ограничен счётчиком попыток: 'failed' с неисчерпанными
        попытками возвращается снова, исчерпавший — нет.  Отдельной
        очереди ретраев нет намеренно: следующий проход свипа и есть
        расписание повтора.

        `suppressed` (не влезло в суточный потолок) НЕ возвращается: это
        не отложенная отправка, а решение «показали сводкой», и повторять
        его значило бы доставлять задним числом то, что подписчик уже
        видел сжатым.
        """
        sql = (
            "SELECT e.id, e.entity_vid, e.entity_name, e.kind, e.doc_id, e.doc_date, "
            "e.detail, e.why, e.detected_at, "
            "w.owner, w.webhook_url, w.daily_push_limit, "
            "COALESCE(dl.attempts, 0) AS attempts "
            "FROM watch_event e "
            "JOIN watch w ON w.entity_vid = e.entity_vid "
            "LEFT JOIN watch_delivery dl ON dl.owner = w.owner AND dl.event_id = e.id "
            "WHERE w.webhook_url <> '' "
            "  AND e.detected_at >= w.created_at "
            "  AND (cardinality(w.kinds) = 0 OR e.kind = ANY(w.kinds)) "
            "  AND (w.muted_until IS NULL OR w.muted_until < now()) "
            "  AND (dl.state IS NULL "
            "       OR (dl.state = 'failed' AND dl.attempts < %s)) "
            "ORDER BY w.owner, e.id LIMIT %s"
        )
        async with self._conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, (int(max_attempts), int(limit)))
            return list(await cur.fetchall())

    async def pushes_today(self, owner: str) -> int:
        """Сколько событий отправлено этому подписчику с начала суток UTC.

        Сводки не считаются: сводка — одно сообщение ВМЕСТО потока, и
        включив её в счёт, потолок в единицу съедала бы сама сводка.
        """
        async with self._conn() as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT COUNT(*) FROM watch_delivery "
                "WHERE owner = %s AND state = 'delivered' "
                "AND updated_at >= date_trunc('day', now())",
                (owner,),
            )
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def mark_delivery(
        self, owner: str, event_id: int, state: str, *,
        error: str = "", digest_of: int | None = None,
    ) -> None:
        """Записать исход отправки одного события одному подписчику.

        Счётчик попыток растёт только у неудач: успех и подавление —
        окончательные исходы, и считать их попытками значило бы исчерпать
        лимит повторов на успешных отправках.
        """
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO watch_delivery "
                    "(owner, event_id, state, attempts, last_error, digest_of, updated_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, now()) "
                    "ON CONFLICT (owner, event_id) DO UPDATE SET "
                    "state = EXCLUDED.state, "
                    "attempts = watch_delivery.attempts + EXCLUDED.attempts, "
                    "last_error = EXCLUDED.last_error, "
                    "digest_of = COALESCE(EXCLUDED.digest_of, watch_delivery.digest_of), "
                    "updated_at = now()",
                    (owner, int(event_id), state, 1 if state == "failed" else 0,
                     error[:500], digest_of),
                )
            await conn.commit()

    async def open_digest(self, owner: str, events: int) -> int:
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO watch_digest (owner, events) VALUES (%s, %s) RETURNING id",
                    (owner, int(events)),
                )
                row = await cur.fetchone()
            await conn.commit()
        return int(row[0])

    async def close_digest(self, digest_id: int, state: str, error: str = "") -> None:
        async with self._conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE watch_digest SET state = %s, last_error = %s WHERE id = %s",
                    (state, error[:500], int(digest_id)),
                )
            await conn.commit()


__all__ = ["JOURNALS", "WatchRepository"]
