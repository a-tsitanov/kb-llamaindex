"""ASGI tests for GET /api/v1/documents/{doc_id}."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import settings


def _key() -> dict[str, str]:
    return {"X-API-Key": settings.api.keys_list[0]}


async def _get(path, *, headers=None):
    from src.api.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        return await ac.get(path, headers=headers)


_DOC_ID = str(uuid.uuid4())


def _row(path):
    return SimpleNamespace(path=path)


def _storage():
    s = MagicMock()
    s.stat_object.return_value = ("report.pdf", 5, "application/pdf")
    s.stream_object.return_value = iter([b"hello"])
    return s


@pytest.mark.asyncio
async def test_download_streams_original():
    with patch("src.storage.postgres.AsyncPostgres.get",
               new=AsyncMock(return_value=_row(f"s3://b/{_DOC_ID}/report.pdf"))), \
         patch("src.api.routes.documents.build_minio_storage",
               return_value=_storage()):
        resp = await _get(f"/api/v1/documents/{_DOC_ID}", headers=_key())
    assert resp.status_code == 200, resp.text
    assert resp.content == b"hello"
    assert 'filename="report.pdf"' in resp.headers["content-disposition"]
    assert resp.headers["content-type"].startswith("application/pdf")


@pytest.mark.asyncio
async def test_download_unknown_doc_404():
    with patch("src.storage.postgres.AsyncPostgres.get",
               new=AsyncMock(return_value=None)):
        resp = await _get(f"/api/v1/documents/{_DOC_ID}", headers=_key())
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_requires_api_key():
    resp = await _get(f"/api/v1/documents/{_DOC_ID}")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_download_sanitizes_filename_header():
    storage = MagicMock()
    # crafted filename with a quote and a space
    storage.stat_object.return_value = ('e"vil report.pdf', 5, "application/pdf")
    storage.stream_object.return_value = iter([b"hello"])
    with patch("src.storage.postgres.AsyncPostgres.get",
               new=AsyncMock(return_value=_row(f"s3://b/{_DOC_ID}/x.pdf"))), \
         patch("src.api.routes.documents.build_minio_storage",
               return_value=storage):
        resp = await _get(f"/api/v1/documents/{_DOC_ID}", headers=_key())
    assert resp.status_code == 200, resp.text
    cd = resp.headers["content-disposition"]
    # raw unescaped double-quote from the filename must NOT leak into the header
    assert 'e"vil' not in cd
    assert "filename*=UTF-8''" in cd


# ── variant=original|text (original binary stored next to the converted text) ──

def _row2(path, original_path=None):
    return SimpleNamespace(path=path, original_path=original_path)


def _storage_by_uri():
    """stat/stream keyed by URI so the test can see which object was served."""
    s = MagicMock()

    def stat(uri):
        name = uri.rsplit("/", 1)[-1]
        return name, 3, "application/octet-stream"

    s.stat_object.side_effect = stat
    s.stream_object.side_effect = lambda uri: iter([uri.encode()])
    return s


_TXT = f"s3://b/{_DOC_ID}/report.md"
_ORIG = f"s3://b/{_DOC_ID}/original/report.docx"


async def _get_variant(row, query=""):
    with patch("src.storage.postgres.AsyncPostgres.get",
               new=AsyncMock(return_value=row)), \
         patch("src.api.routes.documents.build_minio_storage",
               return_value=_storage_by_uri()):
        return await _get(f"/api/v1/documents/{_DOC_ID}{query}", headers=_key())


@pytest.mark.asyncio
async def test_download_defaults_to_original_when_present():
    resp = await _get_variant(_row2(_TXT, _ORIG))
    assert resp.status_code == 200, resp.text
    assert resp.content == _ORIG.encode()
    assert 'filename="report.docx"' in resp.headers["content-disposition"]
    assert resp.headers["content-disposition"].startswith("attachment;")
    # Content-Type guessed from the filename, not the stored octet-stream.
    assert resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml")


@pytest.mark.asyncio
async def test_download_variant_text_serves_converted():
    resp = await _get_variant(_row2(_TXT, _ORIG), "?variant=text")
    assert resp.status_code == 200, resp.text
    assert resp.content == _TXT.encode()
    assert 'filename="report.md"' in resp.headers["content-disposition"]
    assert resp.headers["content-type"].startswith("text/markdown")


@pytest.mark.asyncio
async def test_download_falls_back_to_text_without_original():
    resp = await _get_variant(_row2(_TXT, None))
    assert resp.status_code == 200, resp.text
    assert resp.content == _TXT.encode()


@pytest.mark.asyncio
async def test_download_explicit_original_missing_404():
    resp = await _get_variant(_row2(_TXT, None), "?variant=original")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_unknown_variant_422():
    resp = await _get_variant(_row2(_TXT, _ORIG), "?variant=pdf")
    assert resp.status_code == 422
