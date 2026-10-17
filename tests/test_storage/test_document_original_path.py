"""documents.original_path: row model, insert_pending, setup_db DDL. DB-free."""

from __future__ import annotations

import datetime as dt
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.storage.postgres import AsyncPostgres, DocumentRow
from src.tenancy.context import default_graph_context


def _row(**extra):
    now = dt.datetime.now()
    return {
        "id": uuid.uuid4(), "path": "s3://b/x/a.md", "department": "",
        "doc_type": "md", "status": "pending", "error": "", "summary": "",
        "created_at": now, "updated_at": now, **extra,
    }


def test_from_dict_carries_original_path():
    row = DocumentRow.from_dict(_row(original_path="s3://b/x/original/a.docx"))
    assert row.original_path == "s3://b/x/original/a.docx"


def test_from_dict_without_column_is_none():
    # Pre-setup_db deployments: SELECT * has no original_path column yet.
    assert DocumentRow.from_dict(_row()).original_path is None


def _fake_pg():
    cur = MagicMock()
    cur.execute = AsyncMock()
    cur.__aenter__ = AsyncMock(return_value=cur)
    cur.__aexit__ = AsyncMock(return_value=False)
    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.commit = AsyncMock()

    pg = AsyncPostgres(graph=default_graph_context())

    @asynccontextmanager
    async def _conn():
        yield conn

    pg._conn = _conn  # type: ignore[method-assign]
    return pg, cur


@pytest.mark.asyncio
async def test_insert_pending_writes_original_path():
    pg, cur = _fake_pg()
    await pg.insert_pending(uuid.uuid4(), "s3://b/x/a.md",
                            original_path="s3://b/x/original/a.docx")
    sql, params = cur.execute.call_args.args
    assert "original_path" in sql
    assert "s3://b/x/original/a.docx" in params


@pytest.mark.asyncio
async def test_insert_pending_omits_column_when_no_original():
    # Keeps the INSERT valid on a DB where setup_db hasn't added the column.
    pg, cur = _fake_pg()
    await pg.insert_pending(uuid.uuid4(), "s3://b/x/a.md")
    sql, _ = cur.execute.call_args.args
    assert "original_path" not in sql


def test_setup_db_adds_original_path_idempotently():
    from scripts.setup_db import _DOCUMENTS_DDL

    assert "ADD COLUMN IF NOT EXISTS original_path TEXT" in _DOCUMENTS_DDL
