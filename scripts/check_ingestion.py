"""Diagnostic — show what landed in each backend after ingestion.

Pings every storage backend in turn:
  * Postgres — count + status breakdown of `documents` rows.
  * Milvus   — collection stats.

Usage::

    python -m scripts.check_ingestion
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio

import psycopg

from src.config import settings
from src.intake.repository import EFFECTIVE_STATUS

_SEP = "─" * 70


async def check_postgres() -> None:
    print(_SEP)
    print("Postgres — documents")
    print(_SEP)
    try:
        async with await psycopg.AsyncConnection.connect(
            settings.postgres.dsn, connect_timeout=5,
        ) as conn, conn.cursor() as cur:
            # Запись расщеплена: статус обработки живёт в `doc_processing`,
            # а в `documents.status` остаётся дорасщеплённое значение (I8),
            # поэтому голый `GROUP BY status` показывал бы одни 'pending'.
            # Выражение берём из реестра приёма, чтобы диагностика и
            # отчётность не разъехались.  GROUP BY повторяет ВЫРАЖЕНИЕ, а не
            # псевдоним: имя `status` есть в обеих таблицах, и Postgres
            # разрешил бы его в пользу входной колонки.
            #
            # Предиката `duplicate_of IS NULL` здесь НЕТ намеренно: это
            # построчная диагностика «что лежит в Postgres», а не отчёт
            # «сколько документов принято», поэтому версии того же тела
            # (политика on_duplicate=version) считаются как отдельные строки —
            # у каждой свой комплект чанков.
            await cur.execute(
                f"SELECT {EFFECTIVE_STATUS} AS status, COUNT(*) "
                f"FROM documents d "
                f"LEFT JOIN doc_processing p ON p.doc_id = d.id "
                f"GROUP BY {EFFECTIVE_STATUS}"
            )
            rows = await cur.fetchall()
        if not rows:
            print("  (no rows yet)\n")
            return
        for status, n in rows:
            print(f"  {status:12s} {n}")
    except Exception as exc:
        print(f"  unreachable: {exc}\n")


def check_milvus() -> None:
    from pymilvus import MilvusClient

    print(_SEP)
    print("Milvus")
    print(_SEP)
    cfg = settings.milvus
    try:
        client = MilvusClient(uri=cfg.uri, timeout=cfg.timeout_s)
        try:
            collections = client.list_collections()
            print(f"  collections: {collections}")
            if cfg.collection in collections:
                info = client.get_collection_stats(cfg.collection)
                print(f"  {cfg.collection}: {info}")
        finally:
            client.close()
    except Exception as exc:
        print(f"  unreachable: {exc}")


async def main() -> None:
    await check_postgres()
    check_milvus()


if __name__ == "__main__":
    asyncio.run(main())
