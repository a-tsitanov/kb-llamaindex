"""accept_document persists source_channel/source_group and pairs the row
with its doc_processing row. Integration — skipped when Postgres is
unreachable."""

from __future__ import annotations

import asyncio
import uuid

import psycopg
import pytest

from src.config import settings
from src.intake.repository import IntakeRepository
from src.tenancy.context import default_graph_context


def _pg_reachable() -> bool:
    try:
        with psycopg.connect(settings.postgres.dsn, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_reachable(), reason="local Postgres unreachable"
)


@pytest.fixture(autouse=True)
def _bounded_pg_sessions(monkeypatch):
    """Live-PG test: a running stack may hold locks on these tables. libpq
    applies PGOPTIONS to every connection it opens (direct and pooled), so
    each session gets ``SET lock_timeout='5s'; SET statement_timeout='30s'``
    and fails fast instead of blocking the suite."""
    monkeypatch.setenv("PGOPTIONS", "-c lock_timeout=5s -c statement_timeout=30s")


def test_accept_document_writes_source_columns() -> None:
    doc_id = uuid.uuid4()
    pg = IntakeRepository(settings.postgres.dsn, graph=default_graph_context())

    async def go():
        await pg.accept_document(
            doc_id, f"{doc_id}/tg_chan_1.txt",
            source_channel="chan", source_group="news",
        )

    try:
        asyncio.run(go())
        with psycopg.connect(settings.postgres.dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT source_channel, source_group FROM documents WHERE id = %s",
                (str(doc_id),),
            )
            assert cur.fetchone() == ("chan", "news")
            # Приём — один акт: строка обработки заводится вместе с документом.
            cur.execute(
                "SELECT status FROM doc_processing WHERE doc_id = %s",
                (str(doc_id),),
            )
            assert cur.fetchone() == ("pending",)
    finally:
        with psycopg.connect(settings.postgres.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                # doc_processing уезжает следом по ON DELETE CASCADE.
                cur.execute("DELETE FROM documents WHERE id = %s", (str(doc_id),))
