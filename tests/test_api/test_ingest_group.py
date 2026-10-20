"""ASGI test for the `/ingest` `group` form-field validation (Task 3,
channel-groups). Mirrors `test_ingest_unknown_queue_422` in
`test_ingest.py`: an unknown `group` must 422 before any
upload/Postgres/Temporal work — no MinIO/Temporal infra needed since
validation runs first, so only that stub-free 422 path is exercised
here.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.config import settings
from tests.test_intake.test_dedup import no_duplicate


def _api_key_header() -> dict[str, str]:
    return {"X-API-Key": settings.api.keys_list[0]}



@pytest.mark.asyncio
async def test_ingest_unknown_group_422() -> None:
    from src.api.main import app
    from src.intake.repository import IntakeRepository

    stub_storage = MagicMock()

    with (
        patch(
            "src.intake.api.ingest.build_minio_storage",
            return_value=stub_storage,
        ),
        no_duplicate(),
        patch.object(IntakeRepository, "accept_document", new=AsyncMock()) as ins,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                "/api/v1/ingest",
                headers=_api_key_header(),
                files={"file": ("t.txt", b"hi", "text/plain")},
                data={"group": "sport"},
            )

    assert resp.status_code == 422, resp.text
    assert "unknown group" in resp.text
    # Rejected before any side effects.
    stub_storage.put_object.assert_not_called()
    ins.assert_not_awaited()
