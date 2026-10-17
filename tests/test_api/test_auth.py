"""Stage-8 auth dependency tests.

Uses ``require_api_key`` directly — a unit test (no full ASGI) is
sufficient since the dependency is tiny and pure.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.auth import require_api_key
from src.config import settings
from src.tenancy.api_keys import ApiKeyRecord


@pytest.mark.asyncio
async def test_missing_header_returns_401() -> None:
    with pytest.raises(HTTPException) as exc:
        await require_api_key(x_api_key=None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_invalid_key_returns_403() -> None:
    with pytest.raises(HTTPException) as exc:
        await require_api_key(x_api_key="not-a-valid-key-12345")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_valid_key_returns_key() -> None:
    # Env API_KEYS resolve via the legacy fallback (R-A3); the record only
    # authenticates (no graph binding / admin flag — amendment 2026-10-17).
    valid = settings.api.keys_list[0]
    out = await require_api_key(x_api_key=valid)
    assert out == ApiKeyRecord(owner="legacy-env")
