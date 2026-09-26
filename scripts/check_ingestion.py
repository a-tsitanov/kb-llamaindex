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

_SEP = "─" * 70


async def check_postgres() -> None:
    print(_SEP)
    print("Postgres — documents")
    print(_SEP)
    try:
        async with await psycopg.AsyncConnection.connect(
            settings.postgres.dsn, connect_timeout=5,
        ) as conn, conn.cursor() as cur:
            await cur.execute(
                "SELECT status, COUNT(*) FROM documents GROUP BY status"
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
