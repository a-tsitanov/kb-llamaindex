"""API key lookup (``public.api_keys``, sha256-hashed) with legacy env fallback (R-A3).

A key carries its rights, not just its identity: the tenant it belongs to,
the actions it may perform and an optional narrowing to specific graphs
(``graph_ids is None`` = every graph of its tenant).  The decision itself
is taken in :mod:`src.tenancy.authz`; this module only loads the record.

Two fallbacks here and in the graph registry are deliberately ASYMMETRIC:

* a key row WITHOUT a ``scopes`` key means ``public.api_keys`` has not been
  migrated yet -> fail-OPEN (full rights, i.e. exactly today's behaviour),
  because the code really can start before ``scripts.setup_db`` runs and
  fail-closed would be a service outage for every key;
* a graph row without ``tenant_id`` is fail-CLOSED (reason ``unknown`` ->
  404).

Do not "align" the two.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from loguru import logger

from src.config import settings
from src.tenancy.authz import ALL_ACTIONS
from src.tenancy.context import DEFAULT_TENANT_ID


@dataclass(frozen=True)
class ApiKeyRecord:
    owner: str
    tenant_id: str
    scopes: frozenset[str]
    graph_ids: tuple[str, ...] | None  # None = every graph of the tenant

    @classmethod
    def full(cls, owner: str, tenant_id: str = DEFAULT_TENANT_ID) -> ApiKeyRecord:
        """Every action on every graph of ``tenant_id`` — the pre-tenancy key."""
        return cls(owner=owner, tenant_id=tenant_id, scopes=ALL_ACTIONS, graph_ids=None)


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _load_key_row(key_hash: str) -> dict | None:
    """Read the key row as jsonb, naming no column but ``key_hash``.

    Naming ``tenant_id``/``scopes``/``graph_ids`` would raise UndefinedColumn
    on a table ``scripts.setup_db`` has not migrated yet; the ``except`` in
    :meth:`ApiKeyStore.lookup` swallows it and would drop EVERY db key into
    the env fallback (403 per key, cached for the TTL).  mcp-search/-tools/
    -stats and the offline cluster can start before the migration.
    """
    from psycopg.rows import dict_row

    from src.storage.pg_pool import get_pg_pool

    pool = await get_pg_pool()
    # R-P8: fail fast (1 s) on a saturated/unreachable pool instead of
    # blocking the request for the pool's default wait.
    async with pool.connection(timeout=1) as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT to_jsonb(k) - 'key_hash' AS j FROM public.api_keys k WHERE key_hash = %s",
            (key_hash,),
        )
        row = await cur.fetchone()
        return row["j"] if row else None


_warned_no_scopes = False


def _record_from_row(j: dict) -> ApiKeyRecord:
    """Map a raw ``public.api_keys`` row to a record (pure)."""
    global _warned_no_scopes
    if "scopes" in j:
        # Present-but-empty is a real, rightless key; absent is pre-migration.
        scopes = frozenset(j["scopes"] or ())
    else:
        scopes = ALL_ACTIONS
        if not _warned_no_scopes:
            _warned_no_scopes = True
            logger.warning(
                "authz: public.api_keys has no scopes column — "
                "pre-migration fallback, run scripts.setup_db"
            )
    return ApiKeyRecord(
        owner=j["owner"],
        tenant_id=j.get("tenant_id") or DEFAULT_TENANT_ID,
        scopes=scopes,
        graph_ids=tuple(j["graph_ids"]) if j.get("graph_ids") is not None else None,
    )


async def records_for_owner(owner: str) -> list[ApiKeyRecord]:
    """Живые ключи этого владельца — для проверки права ПЕРЕД доставкой.

    Доставка наблюдения (``src/watch/delivery.py``) идёт не в ответ на
    запрос, а сама, поэтому ключа в руках у неё нет: есть только `owner`
    подписки.  Отсюда чтение по владельцу — обратное обычному чтению по
    хешу.

    Отозвали все ключи владельца — список пуст, и доставка молчит.  Это и
    есть «отзыв прав останавливает доставку»: физическая изоляция таблиц
    от утечки через webhook не спасает, потому что утечка идёт наружу.

    НЕ кешируется, в отличие от ``ApiKeyStore.lookup``: отзыв должен
    действовать сразу, а доставка — редкая операция (раз в проход свипа),
    так что экономить на ней нечего.  Легаси-ключи из ``API_KEYS`` под
    владельцем ``legacy-env`` здесь не видны — у них нет строки в
    таблице, и подписка на такое имя доставки не получит (подписки
    создаются ключом, у которого строка есть).
    """
    if not owner:
        return []
    from psycopg.rows import dict_row

    from src.storage.pg_pool import get_pg_pool

    pool = await get_pg_pool()
    async with pool.connection(timeout=1) as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT to_jsonb(k) - 'key_hash' AS j FROM public.api_keys k WHERE owner = %s",
            (owner,),
        )
        rows = await cur.fetchall()
    return [_record_from_row(r["j"]) for r in rows]


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
            rec: ApiKeyRecord | None = _record_from_row(row)
        elif raw_key in settings.api.keys_list:
            rec = ApiKeyRecord.full("legacy-env")
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
