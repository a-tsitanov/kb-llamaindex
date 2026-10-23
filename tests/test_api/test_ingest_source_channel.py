"""POST /ingest forwards the channel + group form fields into accept_document
as source_channel / source_group. Stubs MinIO + Temporal so no infra runs."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import psycopg.errors
import pytest
from httpx import ASGITransport, AsyncClient

from src.config import settings
from tests.test_intake.test_dedup import no_duplicate


def _api_key_header() -> dict[str, str]:
    return {"X-API-Key": settings.api.keys_list[0]}


@pytest.mark.asyncio
async def test_ingest_forwards_channel_and_group() -> None:
    from src.api.main import app
    from src.intake.repository import IntakeRepository
    from src.intake.sources.repository import SourceRepository

    stub_storage = MagicMock()
    stub_storage.put_object.return_value = "s3://bucket/key"

    with (
        patch.object(SourceRepository, "trust_for_channel", new=AsyncMock(return_value=None)),
        patch(
            "src.intake.api.ingest.build_minio_storage",
            return_value=stub_storage,
        ),
        patch("src.intake.api.ingest.get_temporal_client", new=AsyncMock()),
        patch("src.intake.api.ingest.submit_document", new=AsyncMock()),
        no_duplicate(),
        patch.object(IntakeRepository, "accept_document", new=AsyncMock()) as ins,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/ingest",
                headers=_api_key_header(),
                files={"file": ("tg_acme_9.txt", b"hi", "text/plain")},
                data={"group": "news", "channel": "acme"},
            )

    assert resp.status_code == 202, resp.text
    _, kwargs = ins.call_args
    assert kwargs["source_channel"] == "acme"
    assert kwargs["source_group"] == "news"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("channel", "registry_trust", "expected"),
    [("acme", 0.9, 0.9), ("acme", None, None), ("", 0.9, None)],
)
async def test_ingest_resolves_channel_trust_into_params(
    channel: str, registry_trust: float | None, expected: float | None,
) -> None:
    """Доверие на канал снимается при приёме и едет в IngestParams; пустой
    канал реестр не опрашивает, неизвестный канал даёт None."""
    from src.api.main import app
    from src.intake.repository import IntakeRepository
    from src.intake.sources.repository import SourceRepository

    stub_storage = MagicMock()
    stub_storage.put_object.return_value = "s3://bucket/key"
    submit = AsyncMock()
    lookup = AsyncMock(return_value=registry_trust)

    with (
        patch(
            "src.intake.api.ingest.build_minio_storage",
            return_value=stub_storage,
        ),
        patch("src.intake.api.ingest.get_temporal_client", new=AsyncMock()),
        patch("src.intake.api.ingest.submit_document", new=submit),
        no_duplicate(),
        patch.object(IntakeRepository, "accept_document", new=AsyncMock()),
        patch.object(SourceRepository, "trust_for_channel", new=lookup),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/ingest",
                headers=_api_key_header(),
                files={"file": ("tg_acme_9.txt", b"hi", "text/plain")},
                data={"group": "news", "channel": channel},
            )

    assert resp.status_code == 202, resp.text
    params = submit.call_args.args[1]
    assert params.channel == channel
    assert params.channel_trust == expected
    if channel:
        lookup.assert_awaited_once_with(channel)
    else:
        lookup.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [RuntimeError("pg hiccup"), psycopg.errors.UndefinedTable("relation \"source\" does not exist")],
)
async def test_ingest_survives_failing_channel_trust_lookup(error: Exception) -> None:
    """Доверие на канал — необязательное уточнение: сбой реестра (миграция не
    накатана, сеть) не ломает приём, канал остаётся, доверие = None, документ
    ставится в очередь."""
    from src.api.main import app
    from src.intake.repository import IntakeRepository
    from src.intake.sources.repository import SourceRepository

    stub_storage = MagicMock()
    stub_storage.put_object.return_value = "s3://bucket/key"
    submit = AsyncMock()

    with (
        patch(
            "src.intake.api.ingest.build_minio_storage",
            return_value=stub_storage,
        ),
        patch("src.intake.api.ingest.get_temporal_client", new=AsyncMock()),
        patch("src.intake.api.ingest.submit_document", new=submit),
        no_duplicate(),
        patch.object(IntakeRepository, "accept_document", new=AsyncMock()),
        patch.object(SourceRepository, "trust_for_channel", new=AsyncMock(side_effect=error)),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/ingest",
                headers=_api_key_header(),
                files={"file": ("tg_acme_9.txt", b"hi", "text/plain")},
                data={"group": "news", "channel": "acme"},
            )

    assert resp.status_code == 202, resp.text
    submit.assert_awaited_once()
    params = submit.call_args.args[1]
    assert params.channel == "acme"
    assert params.channel_trust is None
