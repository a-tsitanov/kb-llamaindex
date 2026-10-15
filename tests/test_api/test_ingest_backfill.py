"""ASGI tests for the /ingest `backfill` form field: forwarded into IngestParams
so a re-ingest can fill the entity-watch journals without raising watch events."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import settings


def _api_key_header() -> dict[str, str]:
    return {"X-API-Key": settings.api.keys_list[0]}


async def _post(data: dict[str, str]) -> AsyncMock:
    from src.api.main import app
    from src.storage.postgres import AsyncPostgres

    stub_storage = MagicMock()
    stub_storage.put_object.return_value = "s3://bucket/x/t.txt"
    submit = AsyncMock()
    with (
        patch("src.api.routes.ingest.build_minio_storage", return_value=stub_storage),
        patch.object(AsyncPostgres, "insert_pending", new=AsyncMock()),
        patch("src.api.routes.ingest.get_temporal_client", new=AsyncMock(return_value=MagicMock())),
        patch("src.api.routes.ingest.submit_document", new=submit),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/ingest",
                headers=_api_key_header(),
                files={"file": ("t.txt", b"hi", "text/plain")},
                data=data,
            )
    assert resp.status_code == 202, resp.text
    return submit


@pytest.mark.asyncio
async def test_ingest_forwards_backfill() -> None:
    submit = await _post({"backfill": "true"})
    assert submit.await_args.args[1].backfill is True


@pytest.mark.asyncio
async def test_ingest_backfill_defaults_to_false() -> None:
    submit = await _post({})
    assert submit.await_args.args[1].backfill is False
