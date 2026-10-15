"""ASGI tests for the optional `original` multipart field on POST /ingest.

The converted text (`file`) still drives the pipeline; the original binary
(e.g. .docx) is only stored next to it at `<doc_id>/original/<name>` and its
URI saved as `documents.original_path` for download.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import settings


def _api_key_header() -> dict[str, str]:
    return {"X-API-Key": settings.api.keys_list[0]}


def _stub_storage() -> MagicMock:
    storage = MagicMock()
    storage.put_object.side_effect = lambda key, *_a, **_k: f"s3://kb-uploads/{key}"
    return storage


def _stub_temporal_client() -> MagicMock:
    fake_client = MagicMock()
    fake_client.start_workflow = AsyncMock(return_value=MagicMock())
    return fake_client


async def _post(files: dict, storage: MagicMock, ins: AsyncMock):
    from src.api.main import app
    from src.storage.postgres import AsyncPostgres

    fake_client = _stub_temporal_client()
    with (
        patch("src.api.routes.ingest.build_minio_storage", return_value=storage),
        patch.object(AsyncPostgres, "insert_pending", new=ins),
        patch(
            "src.api.routes.ingest.get_temporal_client",
            new=AsyncMock(return_value=fake_client),
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/ingest", headers=_api_key_header(), files=files,
            )
    return resp, fake_client


@pytest.mark.asyncio
async def test_ingest_with_original_stores_both_objects() -> None:
    storage, ins = _stub_storage(), AsyncMock()
    docx = b"PK\x03\x04 fake docx"
    resp, fake_client = await _post(
        {
            "file": ("report.md", b"# hi", "text/markdown"),
            "original": (
                "report.docx", docx,
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document",
            ),
        },
        storage, ins,
    )
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]

    assert storage.put_object.call_count == 2
    keys = [c.args[0] for c in storage.put_object.call_args_list]
    assert keys[0] == f"{job_id}/report.md"
    assert keys[1] == f"{job_id}/original/report.docx"
    orig_call = storage.put_object.call_args_list[1]
    assert orig_call.args[2] == len(docx)

    ins.assert_awaited_once()
    assert ins.call_args.args[1] == f"s3://kb-uploads/{job_id}/report.md"
    assert ins.call_args.kwargs["original_path"] == (
        f"s3://kb-uploads/{job_id}/original/report.docx")
    # Pipeline still gets the converted text only.
    params = fake_client.start_workflow.call_args.kwargs["start_signal_args"][0]
    assert params.path == f"s3://kb-uploads/{job_id}/report.md"


@pytest.mark.asyncio
async def test_ingest_without_original_saves_no_original_path() -> None:
    storage, ins = _stub_storage(), AsyncMock()
    resp, _ = await _post(
        {"file": ("note.md", b"# hi", "text/markdown")}, storage, ins,
    )
    assert resp.status_code == 202, resp.text
    storage.put_object.assert_called_once()
    assert ins.call_args.kwargs.get("original_path") is None


@pytest.mark.asyncio
async def test_ingest_original_filename_is_sanitised() -> None:
    storage, ins = _stub_storage(), AsyncMock()
    resp, _ = await _post(
        {
            "file": ("x.md", b"# hi", "text/markdown"),
            "original": ("..\\..\\evil\r\nname.pdf", b"%PDF", "application/pdf"),
        },
        storage, ins,
    )
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["job_id"]
    key = storage.put_object.call_args_list[1].args[0]
    assert key.startswith(f"{job_id}/original/")
    name = key.removeprefix(f"{job_id}/original/")
    assert "/" not in name and "\\" not in name
    assert "\r" not in name and "\n" not in name
    assert name.endswith(".pdf") and not name.startswith(".")
