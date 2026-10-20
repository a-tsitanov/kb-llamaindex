"""ASGI tests for the /ingest `backfill` form field: forwarded into IngestParams
so a re-ingest can fill the entity-watch journals without raising watch events."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import settings
from tests.test_intake.test_dedup import no_duplicate


def _api_key_header() -> dict[str, str]:
    return {"X-API-Key": settings.api.keys_list[0]}



async def _post(data: dict[str, str]) -> AsyncMock:
    from src.api.main import app
    from src.intake.repository import IntakeRepository

    stub_storage = MagicMock()
    stub_storage.put_object.return_value = "s3://bucket/x/t.txt"
    submit = AsyncMock()
    with (
        patch("src.intake.api.ingest.build_minio_storage", return_value=stub_storage),
        no_duplicate(),
        patch.object(IntakeRepository, "accept_document", new=AsyncMock()),
        patch("src.intake.api.ingest.get_temporal_client", new=AsyncMock(return_value=MagicMock())),
        patch("src.intake.api.ingest.submit_document", new=submit),
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
