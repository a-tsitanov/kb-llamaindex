"""Журнал выдач оригиналов и границы легаси-ветки (§7.3 и §7.4 карты контуров).

Предмет — не поток байт (он проверен в ``test_documents.py``), а два
свойства самой строгой точки контура приёма:

* выдача ЗАПИСАНА, и записан эффективный вариант, а не присланный;
* незаписанная выдача НЕ происходит — маршрут fail-closed.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from src.config import settings
from src.intake.api.documents import _legacy_local_file
from src.tenancy.context import default_graph_context, new_graph_context

_DOC_ID = str(uuid.uuid4())


def _key() -> dict[str, str]:
    return {"X-API-Key": settings.api.keys_list[0]}


def _row(path: str, original: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(path=path, original_path=original)


def _storage() -> MagicMock:
    s = MagicMock()
    s.stat_object.return_value = ("report.pdf", 5, "application/pdf")
    s.stream_object.return_value = iter([b"hello"])
    return s


async def _get(path: str, headers=None):
    from src.api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        return await ac.get(path, headers=headers)


# ── журнал ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_download_is_journalled_with_principal_and_path() -> None:
    row = _row(f"s3://b/{_DOC_ID}/a.txt", f"s3://b/{_DOC_ID}/original/a.pdf")
    with (
        patch("src.intake.repository.IntakeRepository.get",
              new=AsyncMock(return_value=row)),
        patch("src.intake.repository.IntakeRepository.record_download",
              new=AsyncMock()) as rec,
        patch("src.intake.api.documents.build_minio_storage",
              return_value=_storage()),
    ):
        resp = await _get(f"/api/v1/documents/{_DOC_ID}", _key())

    assert resp.status_code == 200, resp.text
    assert rec.await_count == 1
    args, kwargs = rec.await_args
    assert str(args[0]) == _DOC_ID
    # Эффективный вариант: ?variant= не передан, оригинал есть → ушёл он.
    assert args[1] == "original"
    assert args[2] == f"s3://b/{_DOC_ID}/original/a.pdf"
    # Принципал — owner ключа; у legacy-ключа из env он непустой.
    assert kwargs["principal"]


@pytest.mark.asyncio
async def test_journal_records_text_variant_when_text_is_served() -> None:
    row = _row(f"s3://b/{_DOC_ID}/a.txt", f"s3://b/{_DOC_ID}/original/a.pdf")
    with (
        patch("src.intake.repository.IntakeRepository.get",
              new=AsyncMock(return_value=row)),
        patch("src.intake.repository.IntakeRepository.record_download",
              new=AsyncMock()) as rec,
        patch("src.intake.api.documents.build_minio_storage",
              return_value=_storage()),
    ):
        resp = await _get(f"/api/v1/documents/{_DOC_ID}?variant=text", _key())

    assert resp.status_code == 200, resp.text
    assert rec.await_args.args[1] == "text"


@pytest.mark.asyncio
async def test_journal_records_text_when_no_original_exists() -> None:
    """Без оригинала по умолчанию уходит текст — журнал пишет 'text'.

    Это и есть причина не писать присланный параметр: он был None, а ушёл
    конкретный вариант.
    """
    with (
        patch("src.intake.repository.IntakeRepository.get",
              new=AsyncMock(return_value=_row(f"s3://b/{_DOC_ID}/a.txt"))),
        patch("src.intake.repository.IntakeRepository.record_download",
              new=AsyncMock()) as rec,
        patch("src.intake.api.documents.build_minio_storage",
              return_value=_storage()),
    ):
        resp = await _get(f"/api/v1/documents/{_DOC_ID}", _key())

    assert resp.status_code == 200, resp.text
    assert rec.await_args.args[1] == "text"


@pytest.mark.asyncio
async def test_unwritable_journal_refuses_the_download() -> None:
    """Fail-closed: не записали — не отдали, и байт в ответе нет."""
    storage = _storage()
    with (
        patch("src.intake.repository.IntakeRepository.get",
              new=AsyncMock(return_value=_row(f"s3://b/{_DOC_ID}/a.txt"))),
        patch("src.intake.repository.IntakeRepository.record_download",
              new=AsyncMock(side_effect=RuntimeError("pg down"))),
        patch("src.intake.api.documents.build_minio_storage",
              return_value=storage),
    ):
        resp = await _get(f"/api/v1/documents/{_DOC_ID}", _key())

    assert resp.status_code == 503, resp.text
    assert resp.json()["detail"] == "download journal unavailable"
    assert b"hello" not in resp.content
    storage.stream_object.assert_not_called()


@pytest.mark.asyncio
async def test_refused_download_writes_nothing() -> None:
    """404 — не выдача: журнал расследования не засоряется промахами."""
    with (
        patch("src.intake.repository.IntakeRepository.get",
              new=AsyncMock(return_value=None)),
        patch("src.intake.repository.IntakeRepository.record_download",
              new=AsyncMock()) as rec,
    ):
        resp = await _get(f"/api/v1/documents/{_DOC_ID}", _key())

    assert resp.status_code == 404
    rec.assert_not_awaited()


# ── легаси-ветка чтения с диска ──────────────────────────────────────


def test_legacy_path_outside_the_whitelist_is_refused(tmp_path, monkeypatch) -> None:
    """Путь из колонки БД читается только из ``API_UPLOAD_DIR``."""
    monkeypatch.setattr(settings.api, "upload_dir", str(tmp_path / "uploads"))
    (tmp_path / "uploads").mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("x")

    with pytest.raises(HTTPException) as exc:
        _legacy_local_file(str(outside), default_graph_context())
    assert exc.value.status_code == 404


def test_legacy_path_traversal_is_refused(tmp_path, monkeypatch) -> None:
    """``..`` не выводит из белого списка: путь разрешается до сравнения."""
    root = tmp_path / "uploads"
    root.mkdir()
    monkeypatch.setattr(settings.api, "upload_dir", str(root))
    outside = tmp_path / "secret.txt"
    outside.write_text("x")

    with pytest.raises(HTTPException) as exc:
        _legacy_local_file(str(root / ".." / "secret.txt"), default_graph_context())
    assert exc.value.status_code == 404


def test_legacy_branch_is_refused_outside_the_default_graph(tmp_path, monkeypatch) -> None:
    """Локальные пути существуют только в дорелизных строках, а они все в
    `default`; в новом графе такая строка — испорченный реестр."""
    root = tmp_path / "uploads"
    root.mkdir()
    monkeypatch.setattr(settings.api, "upload_dir", str(root))
    inside = root / "a.txt"
    inside.write_text("x")

    with pytest.raises(HTTPException) as exc:
        _legacy_local_file(str(inside), new_graph_context("acme"))
    assert exc.value.status_code == 404
    # Тот же путь в `default` проходит — отказ именно из-за графа.
    assert _legacy_local_file(str(inside), default_graph_context()) == inside.resolve()


@pytest.mark.asyncio
async def test_legacy_download_is_journalled_too(tmp_path, monkeypatch) -> None:
    root = tmp_path / "uploads"
    root.mkdir()
    monkeypatch.setattr(settings.api, "upload_dir", str(root))
    legacy = root / "old.txt"
    legacy.write_text("legacy")

    with (
        patch("src.intake.repository.IntakeRepository.get",
              new=AsyncMock(return_value=_row(str(legacy)))),
        patch("src.intake.repository.IntakeRepository.record_download",
              new=AsyncMock()) as rec,
    ):
        resp = await _get(f"/api/v1/documents/{_DOC_ID}", _key())

    assert resp.status_code == 200, resp.text
    assert resp.content == b"legacy"
    assert rec.await_args.args[1] == "text"
    assert rec.await_args.args[2] == str(legacy)
