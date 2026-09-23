"""Lens auth: own API keys (``LENS_API_KEYS``) + short-lived signed SSE tokens.

``EventSource`` can't send headers, and a long-lived key in a URL ends up in proxy
access logs.  So the stream takes ``?token=`` minted by an authenticated POST: it is
bound to one workspace and expires after ``ttl_s``.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import HTTPException, Request, status

from src.lens.config import lens_settings

STREAM_TOKEN_TTL_S = 300


def _sig(secret: str, workspace_id: str, exp: int) -> str:
    msg = f"{workspace_id}.{exp}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()[:32]


def make_stream_token(
    workspace_id: str, secret: str, *, ttl_s: int = STREAM_TOKEN_TTL_S, now: float | None = None,
) -> str:
    exp = int(now if now is not None else time.time()) + ttl_s
    return f"{exp}.{_sig(secret, workspace_id, exp)}"


def check_stream_token(
    token: str, workspace_id: str, secret: str, *, now: float | None = None,
) -> bool:
    try:
        exp_s, sig = token.split(".", 1)
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < (now if now is not None else time.time()):
        return False
    return hmac.compare_digest(sig, _sig(secret, workspace_id, exp))


async def require_key(request: Request) -> None:
    key = request.headers.get("X-API-Key")
    if not key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-API-Key")
    if key not in lens_settings.keys_list():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid X-API-Key")


async def require_stream_token(request: Request, workspace_id: str) -> None:
    token = request.query_params.get("token", "")
    if not check_stream_token(token, workspace_id, lens_settings.stream_secret_value()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired stream token")
