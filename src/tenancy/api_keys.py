"""API key lookup (``public.api_keys``, sha256-hashed) with legacy env fallback (R-A3)."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from loguru import logger

from src.config import settings
from src.tenancy.context import DEFAULT_GRAPH_ID


@dataclass(frozen=True)
class ApiKeyRecord:
    owner: str
    graph_ids: tuple[str, ...]
    is_admin: bool


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _load_key_row(key_hash: str) -> dict | None:
    from psycopg.rows import dict_row

    from src.storage.pg_pool import get_pg_pool

    pool = await get_pg_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT owner, graph_ids, is_admin FROM public.api_keys WHERE key_hash = %s",
            (key_hash,),
        )
        return await cur.fetchone()


class ApiKeyStore:
    def __init__(
        self,
        loader: Callable[[str], Awaitable[dict | None]] | None = None,
        ttl_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._loader = loader or _load_key_row
        self._ttl, self._clock = ttl_s, clock
        self._cache: dict[str, tuple[float, ApiKeyRecord | None]] = {}

    async def lookup(self, raw_key: str) -> ApiKeyRecord | None:
        if not raw_key:
            return None
        h = hash_api_key(raw_key)
        now = self._clock()
        hit = self._cache.get(h)
        if hit is not None and now - hit[0] < self._ttl:
            return hit[1]
        try:
            row = await self._loader(h)
        except Exception as exc:  # e.g. table missing before setup_db ran
            logger.warning("api key lookup failed; falling back to env API_KEYS: {e}", e=exc)
            row = None
        if row is not None:
            rec: ApiKeyRecord | None = ApiKeyRecord(
                owner=row["owner"], graph_ids=tuple(row["graph_ids"] or ()), is_admin=bool(row["is_admin"])
            )
        elif raw_key in settings.api.keys_list:
            rec = ApiKeyRecord(owner="legacy-env", graph_ids=(DEFAULT_GRAPH_ID,), is_admin=True)
        else:
            rec = None
        self._cache[h] = (now, rec)
        return rec


_store: ApiKeyStore | None = None


def get_api_key_store() -> ApiKeyStore:
    global _store
    if _store is None:
        _store = ApiKeyStore()
    return _store


def reset_api_key_store_for_tests() -> None:
    global _store
    _store = None
