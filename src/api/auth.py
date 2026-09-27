"""X-API-Key auth dependency.

Keys are looked up in ``public.api_keys`` (sha256-hashed) via
:class:`~src.tenancy.api_keys.ApiKeyStore`, with the legacy ``API_KEYS``
env list as fallback (R-A3).  Each key maps to the graphs it may use.
Health endpoint stays public; everything else requires the header.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from src.tenancy.api_keys import ApiKeyRecord, get_api_key_store


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> ApiKeyRecord:
    if x_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )
    rec = await get_api_key_store().lookup(x_api_key)
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid X-API-Key",
        )
    return rec


async def require_admin(key: ApiKeyRecord = Depends(require_api_key)) -> ApiKeyRecord:
    if not key.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin key required")
    return key
