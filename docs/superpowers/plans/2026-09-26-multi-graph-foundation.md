# Multi-Graph Foundation (Plan A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every storage access graph-scoped through an explicit `GraphContext`, and carry `graph_id` from HTTP/MCP/RabbitMQ through Temporal into activities — with only the `default` graph registered, so behaviour is unchanged.

**Architecture:** A small `src/tenancy/` package owns graph identity: `GraphContext` (id + physical names), `GraphRegistry` (PG-backed, TTL-cached, built-in `default`), `ApiKeyStore`, and workflow-id helpers. Storage layers (Postgres via `search_path`, Nebula per-space sessions, Milvus per-graph collections, MinIO prefixes) take a `GraphContext` argument. Temporal contracts get `graph_id` (transitional default `"default"`); activities resolve the context; API/MCP bind the graph to the connection. Plan B (separate) adds graph lifecycle (provision/delete), key management endpoints, per-graph background jobs and the live isolation test.

**Tech Stack:** Python 3.12, FastAPI, fastmcp 3.3.1, Temporal Python SDK, psycopg 3 + psycopg_pool 3.3.1, nebula3-python, pymilvus / llama-index MilvusVectorStore, MinIO, aio-pika, pytest (`uv run --extra dev pytest`).

**Spec:** `docs/superpowers/specs/2026-09-24-multi-graph-design.md` (sections 1, 2 and the MinIO/migration parts of 3–4; lifecycle/delete, key admin endpoints, refresh-all and isolation test are Plan B).

## Global Constraints

- Graph id slug: `^[a-z][a-z0-9_]{1,30}$`; `default` is reserved. Validation is the DDL-injection defence — every entry point validates.
- `default` graph physical names: Nebula space `kb`, partition_num `100`, chunks collection `settings.milvus.collection` (`kb_llamaindex`), `entity_er_vec`, `community_report_vec`, PG schema `public`, MinIO prefix `""`.
- New-graph physical names: space `g_<id>`, collections `g_<id>_chunks`, `g_<id>_er_vec`, `g_<id>_report_vec`, PG schema `g_<id>`, MinIO prefix `<id>/`, partition_num default `10`.
- Global PG tables live in `public` and are addressed as `public.<table>`: `graphs`, `api_keys`, `bot_user`, `bot_request`. Graph-scoped tables (in each graph schema): `documents`, `entity`, `er_verdict`, `fact_supersede`, `ingest_metrics`, `stat_indicator`, `stat_observation`.
- Storage-touching functions take `GraphContext` (or resources built from it) as an explicit argument — no contextvars.
- Temporal: physical names are never put into workflow inputs; only `graph_id`. `graph_id: str = "default"` is a transitional default in Plan A (removed in Plan B after drain).
- No behaviour change while only `default` exists: workflow ids for `default` stay exactly as today (e.g. `ingest-{doc_id}`); non-default graphs get the graph segment.
- Neo4j does not exist in this codebase (guard `tests/test_no_neo4j.py` stays green).
- SUITE = `uv run --extra dev pytest -q -p no:cacheprovider --ignore=tests/eval -m "not integration"` (~20 s). Gate for every task: failures ⊆ {`tests/test_scripts/test_make_env.py::test_every_env_var_has_russian_description`} (pre-existing); the 2 strict xfails in `tests/test_workflow/test_monitor_activities.py` stay XFAIL.
- Git: local commits only, never push; trailer `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. After the last task: `graphify update .` and commit `graphify-out`.

## Controller rulings baked into this plan

- **R-A1 built-in default:** `GraphRegistry.get("default")` returns the built-in default context when the `public.graphs` row is missing or PG is unreachable (logs once). Keeps dev/tests/DB-less paths working; `setup_db` still inserts the row.
- **R-A2 workflow ids:** `graph_scoped_id(prefix, graph_id, suffix)` returns `f"{prefix}-{suffix}"` for `default` and `f"{prefix}-{graph_id}-{suffix}"` otherwise — preserves Temporal dedupe for in-flight `default` runs across the deploy.
- **R-A3 legacy keys:** a key present in `settings.api.keys_list` (env `API_KEYS`) and absent from `public.api_keys` authenticates as `is_admin=True, graph_ids=("default",)`. Plan B adds key management and may retire this.
- **R-A4 MCP rejection point:** fastmcp verifies bearer tokens without request headers, so the graph binding is validated on each tool call (`current_graph()` raises `ToolError`) instead of at handshake. Same rules as HTTP.
- **R-A5 transitional marker:** while call sites are being migrated they pass `transitional_default_graph()`; Task 12's guard requires zero remaining references in `src/`.

## Review Focus

1. A pooled Postgres connection used for graph A must not carry `search_path` into the next checkout (bot tables, graph B). Pinned in Task 3 by `test_reset_callback_resets_search_path_and_commits` and `test_graph_connection_commits_set_before_yield` (a rollback inside the block must not revert the SET).
2. Nebula session re-acquired after an idle expiry must `USE` the same space it was built for, not `kb`. Pinned in Task 4 by `test_reconnect_reuses_the_graph_space`.
3. A Temporal payload serialized before deploy (no `graph_id` key) must still load and run as `default`. Pinned in Task 7 by `test_legacy_payload_without_graph_id_defaults`.
4. A valid key used against a graph outside its list, or a multi-graph key without `X-Graph`, must be refused (403 / 400), never silently served `default`. Pinned in Task 9 by the `resolve_graph` table tests.
5. MCP over stdio (no HTTP request) must still work for local desktop use and bind to the configured graph. Pinned in Task 10 by `test_current_graph_stdio_uses_configured_graph`.
6. Code deployed before `setup_db` created `public.api_keys` must keep authenticating env `API_KEYS` instead of returning 500. Pinned in Task 2 by `test_loader_error_falls_back_to_env_keys`.

## Existing data (no migration)

Plan A moves or rewrites no data: the current deployment becomes graph `default` under its existing names (space `kb`, collections `kb_llamaindex`/`entity_er_vec`/`community_report_vec`, PG schema `public`, unprefixed MinIO keys, unchanged `default` workflow ids and queue message ids). `setup_db` only adds `public.graphs` (+ `default` row) and `public.api_keys` (+ sha256 of env `API_KEYS`). Pre-deploy check: `SELECT nspname FROM pg_namespace WHERE nspname = current_user;` must be empty (connections now use `search_path = public` instead of PG's default `"$user", public`). Rollback = code revert; the two new tables are inert.

---

### Task 1: `GraphContext`, slug validation, physical names, workflow-id helper

**Files:**
- Create: `src/tenancy/__init__.py`, `src/tenancy/context.py`
- Test: `tests/test_tenancy/__init__.py`, `tests/test_tenancy/test_context.py`

**Interfaces:**
- Produces:
  - `DEFAULT_GRAPH_ID: str = "default"`
  - `class InvalidGraphId(ValueError)`
  - `validate_graph_id(graph_id: str) -> str` (returns it or raises `InvalidGraphId`)
  - `@dataclass(frozen=True) class GraphContext: id: str; nebula_space: str; nebula_partition_num: int; chunks_collection: str; er_vec_collection: str; report_vec_collection: str; pg_schema: str; minio_prefix: str` with `is_default -> bool` property
  - `default_graph_context() -> GraphContext`
  - `new_graph_context(graph_id: str, *, nebula_partition_num: int = 10) -> GraphContext`
  - `transitional_default_graph() -> GraphContext` (same value as `default_graph_context()`, distinct name for the guard)
  - `graph_scoped_id(prefix: str, graph_id: str, suffix: str) -> str`

- [ ] **Step 1: Write the failing test** — `tests/test_tenancy/test_context.py`:

```python
import pytest

from src.config import settings
from src.tenancy.context import (
    DEFAULT_GRAPH_ID,
    GraphContext,
    InvalidGraphId,
    default_graph_context,
    graph_scoped_id,
    new_graph_context,
    transitional_default_graph,
    validate_graph_id,
)


@pytest.mark.parametrize("gid", ["ab", "acme", "client_1", "a" + "b" * 30])
def test_valid_ids(gid):
    assert validate_graph_id(gid) == gid


@pytest.mark.parametrize(
    "gid",
    ["", "a", "1abc", "Acme", "acme-x", "acme x", "a" + "b" * 31, "kb`; DROP SPACE kb; --", "g_x;", "é"],
)
def test_invalid_ids(gid):
    with pytest.raises(InvalidGraphId):
        validate_graph_id(gid)


def test_default_context_uses_legacy_names():
    ctx = default_graph_context()
    assert ctx == GraphContext(
        id=DEFAULT_GRAPH_ID,
        nebula_space="kb",
        nebula_partition_num=100,
        chunks_collection=settings.milvus.collection,
        er_vec_collection="entity_er_vec",
        report_vec_collection="community_report_vec",
        pg_schema="public",
        minio_prefix="",
    )
    assert ctx.is_default
    assert transitional_default_graph() == ctx


def test_new_graph_context_names():
    ctx = new_graph_context("acme")
    assert ctx.nebula_space == "g_acme"
    assert ctx.nebula_partition_num == 10
    assert ctx.chunks_collection == "g_acme_chunks"
    assert ctx.er_vec_collection == "g_acme_er_vec"
    assert ctx.report_vec_collection == "g_acme_report_vec"
    assert ctx.pg_schema == "g_acme"
    assert ctx.minio_prefix == "acme/"
    assert not ctx.is_default


def test_new_graph_context_rejects_reserved_and_invalid():
    with pytest.raises(InvalidGraphId):
        new_graph_context(DEFAULT_GRAPH_ID)
    with pytest.raises(InvalidGraphId):
        new_graph_context("Bad-Id")


def test_graph_scoped_id_keeps_default_ids_unchanged():
    assert graph_scoped_id("ingest", DEFAULT_GRAPH_ID, "doc1") == "ingest-doc1"
    assert graph_scoped_id("ingest", "acme", "doc1") == "ingest-acme-doc1"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_tenancy/test_context.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.tenancy'`.

- [ ] **Step 3: Implement** — `src/tenancy/__init__.py`: empty docstring module `"""Graph identity and scoping (multi-graph isolation)."""`. `src/tenancy/context.py`:

```python
"""Graph identity: the id, its physical storage names, and id validation.

A ``GraphContext`` is the only thing storage code needs to know which graph
it is touching.  Physical names live here (and in the registry row), never in
Temporal payloads."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.config import settings

DEFAULT_GRAPH_ID = "default"
_SLUG = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


class InvalidGraphId(ValueError):
    """Graph id is not a valid slug (it is interpolated into DDL)."""


def validate_graph_id(graph_id: str) -> str:
    if not isinstance(graph_id, str) or not _SLUG.fullmatch(graph_id):
        raise InvalidGraphId(f"invalid graph id: {graph_id!r}")
    return graph_id


@dataclass(frozen=True)
class GraphContext:
    id: str
    nebula_space: str
    nebula_partition_num: int
    chunks_collection: str
    er_vec_collection: str
    report_vec_collection: str
    pg_schema: str
    minio_prefix: str

    @property
    def is_default(self) -> bool:
        return self.id == DEFAULT_GRAPH_ID


def default_graph_context() -> GraphContext:
    """The pre-multi-graph deployment, under its existing physical names."""
    return GraphContext(
        id=DEFAULT_GRAPH_ID,
        nebula_space="kb",
        nebula_partition_num=100,
        chunks_collection=settings.milvus.collection,
        er_vec_collection="entity_er_vec",
        report_vec_collection="community_report_vec",
        pg_schema="public",
        minio_prefix="",
    )


def transitional_default_graph() -> GraphContext:
    """Call sites not yet wired to a real graph use this; Task 12's guard
    requires zero references in src/ at the end of Plan A."""
    return default_graph_context()


def new_graph_context(graph_id: str, *, nebula_partition_num: int = 10) -> GraphContext:
    validate_graph_id(graph_id)
    if graph_id == DEFAULT_GRAPH_ID:
        raise InvalidGraphId("'default' is reserved")
    return GraphContext(
        id=graph_id,
        nebula_space=f"g_{graph_id}",
        nebula_partition_num=nebula_partition_num,
        chunks_collection=f"g_{graph_id}_chunks",
        er_vec_collection=f"g_{graph_id}_er_vec",
        report_vec_collection=f"g_{graph_id}_report_vec",
        pg_schema=f"g_{graph_id}",
        minio_prefix=f"{graph_id}/",
    )


def graph_scoped_id(prefix: str, graph_id: str, suffix: str) -> str:
    """Temporal workflow id; `default` keeps its pre-multi-graph id (R-A2)."""
    if graph_id == DEFAULT_GRAPH_ID:
        return f"{prefix}-{suffix}"
    return f"{prefix}-{graph_id}-{suffix}"
```

Note: `default` does not match `_SLUG`'s reserved check in `validate_graph_id` (it is a valid slug); only `new_graph_context` rejects it.

- [ ] **Step 4: Run to verify it passes** — same command → PASS. Then SUITE (gate).
- [ ] **Step 5: Commit**

```bash
git add src/tenancy tests/test_tenancy
git commit -m "feat(tenancy): GraphContext, graph id validation and workflow-id helper"
```

### Task 2: Graph registry, API key store, global PG DDL + bootstrap

**Files:**
- Create: `src/tenancy/registry.py`, `src/tenancy/api_keys.py`
- Modify: `scripts/setup_db.py` (add `_GRAPHS_DDL`, `_API_KEYS_DDL`, `_bootstrap_registry(cur)`)
- Test: `tests/test_tenancy/test_registry.py`, `tests/test_tenancy/test_api_keys.py`, `tests/test_scripts/test_setup_db_registry.py`

**Interfaces:**
- Consumes: Task 1 `GraphContext`, `default_graph_context`, `validate_graph_id`, `DEFAULT_GRAPH_ID`.
- Produces:
  - `class GraphNotFound(LookupError)`, `class GraphNotReady(RuntimeError)` (attrs `graph_id`, `status`)
  - `class GraphRegistry(loader: Callable[[str], Awaitable[dict | None]] | None = None, ttl_s: float = 30.0, clock: Callable[[], float] = time.monotonic)` with `async get(graph_id: str) -> GraphContext`, `async get_row(graph_id) -> dict | None`, `invalidate(graph_id: str | None = None) -> None`
  - `get_graph_registry() -> GraphRegistry` (process singleton), `reset_graph_registry_for_tests() -> None`
  - `@dataclass(frozen=True) class ApiKeyRecord: owner: str; graph_ids: tuple[str, ...]; is_admin: bool`
  - `hash_api_key(raw: str) -> str` (sha256 hex)
  - `class ApiKeyStore(loader: Callable[[str], Awaitable[dict | None]] | None = None, ttl_s: float = 30.0, clock=time.monotonic)` with `async lookup(raw_key: str) -> ApiKeyRecord | None`
  - `get_api_key_store() -> ApiKeyStore`, `reset_api_key_store_for_tests() -> None`

- [ ] **Step 1: Write the failing tests** — `tests/test_tenancy/test_registry.py`:

```python
import pytest

from src.tenancy.context import default_graph_context, new_graph_context
from src.tenancy.registry import GraphNotFound, GraphNotReady, GraphRegistry


def _row(gid, status="ready"):
    c = new_graph_context(gid)
    return {
        "id": gid, "owner": "o", "status": status,
        "nebula_space": c.nebula_space, "nebula_partition_num": c.nebula_partition_num,
        "chunks_collection": c.chunks_collection, "er_vec_collection": c.er_vec_collection,
        "report_vec_collection": c.report_vec_collection, "pg_schema": c.pg_schema,
    }


class _Loader:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    async def __call__(self, gid):
        self.calls.append(gid)
        return self.rows.get(gid)


async def test_get_ready_graph_builds_context():
    reg = GraphRegistry(loader=_Loader({"acme": _row("acme")}))
    assert await reg.get("acme") == new_graph_context("acme")


async def test_get_caches_within_ttl_and_reloads_after():
    t = [0.0]
    loader = _Loader({"acme": _row("acme")})
    reg = GraphRegistry(loader=loader, ttl_s=30, clock=lambda: t[0])
    await reg.get("acme"); await reg.get("acme")
    assert loader.calls == ["acme"]
    t[0] = 31
    await reg.get("acme")
    assert loader.calls == ["acme", "acme"]


async def test_invalidate_forces_reload():
    loader = _Loader({"acme": _row("acme")})
    reg = GraphRegistry(loader=loader)
    await reg.get("acme"); reg.invalidate("acme"); await reg.get("acme")
    assert loader.calls == ["acme", "acme"]


async def test_unknown_graph_raises_not_found():
    reg = GraphRegistry(loader=_Loader({}))
    with pytest.raises(GraphNotFound):
        await reg.get("nope")


@pytest.mark.parametrize("status", ["provisioning", "deleting", "failed"])
async def test_non_ready_graph_raises_not_ready(status):
    reg = GraphRegistry(loader=_Loader({"acme": _row("acme", status)}))
    with pytest.raises(GraphNotReady) as ei:
        await reg.get("acme")
    assert ei.value.status == status


async def test_invalid_id_never_reaches_loader():
    loader = _Loader({})
    reg = GraphRegistry(loader=loader)
    with pytest.raises(GraphNotFound):
        await reg.get("Bad;Id")
    assert loader.calls == []


async def test_default_falls_back_to_builtin_when_row_missing():
    reg = GraphRegistry(loader=_Loader({}))
    assert await reg.get("default") == default_graph_context()


async def test_default_falls_back_to_builtin_when_loader_errors():
    async def boom(gid):
        raise OSError("pg down")
    reg = GraphRegistry(loader=boom)
    assert await reg.get("default") == default_graph_context()


async def test_non_default_loader_error_propagates():
    async def boom(gid):
        raise OSError("pg down")
    reg = GraphRegistry(loader=boom)
    with pytest.raises(OSError):
        await reg.get("acme")
```

`tests/test_tenancy/test_api_keys.py`:

```python
import hashlib

from src.tenancy.api_keys import ApiKeyRecord, ApiKeyStore, hash_api_key


def test_hash_is_sha256_hex():
    assert hash_api_key("k") == hashlib.sha256(b"k").hexdigest()


async def test_lookup_db_row():
    async def loader(h):
        assert h == hash_api_key("secret")
        return {"owner": "acme", "graph_ids": ["acme", "acme_hr"], "is_admin": False}
    rec = await ApiKeyStore(loader=loader).lookup("secret")
    assert rec == ApiKeyRecord(owner="acme", graph_ids=("acme", "acme_hr"), is_admin=False)


async def test_legacy_env_key_is_default_admin(monkeypatch):
    from src.config import settings
    monkeypatch.setattr(type(settings.api), "keys_list", property(lambda self: ["legacy"]))
    async def loader(h):
        return None
    rec = await ApiKeyStore(loader=loader).lookup("legacy")
    assert rec == ApiKeyRecord(owner="legacy-env", graph_ids=("default",), is_admin=True)


async def test_unknown_key_is_none(monkeypatch):
    from src.config import settings
    monkeypatch.setattr(type(settings.api), "keys_list", property(lambda self: []))
    async def loader(h):
        return None
    assert await ApiKeyStore(loader=loader).lookup("nope") is None


async def test_loader_error_falls_back_to_env_keys(monkeypatch):
    # public.api_keys missing (code deployed before setup_db) must not 500 every request
    from src.config import settings
    monkeypatch.setattr(type(settings.api), "keys_list", property(lambda self: ["legacy"]))
    async def boom(h):
        raise RuntimeError('relation "public.api_keys" does not exist')
    store = ApiKeyStore(loader=boom)
    assert await store.lookup("legacy") == ApiKeyRecord(owner="legacy-env", graph_ids=("default",), is_admin=True)
    assert await store.lookup("other") is None


async def test_empty_key_is_none():
    async def loader(h):
        raise AssertionError("must not query")
    assert await ApiKeyStore(loader=loader).lookup("") is None
```

If `keys_list` is a `cached_property` rather than a property, monkeypatch the instance attribute instead (`monkeypatch.setattr(settings.api, "keys_list", ["legacy"], raising=False)` after checking `src/config.py:66-72`); keep the assertions.

`tests/test_scripts/test_setup_db_registry.py`:

```python
from scripts import setup_db


class _Cur:
    def __init__(self):
        self.sql = []

    def execute(self, q, params=None):
        self.sql.append((str(q), params))


def test_global_ddl_creates_registry_tables_in_public():
    assert "CREATE TABLE IF NOT EXISTS public.graphs" in setup_db._GRAPHS_DDL
    assert "CREATE TABLE IF NOT EXISTS public.api_keys" in setup_db._API_KEYS_DDL


def test_bootstrap_inserts_default_row_idempotently(monkeypatch):
    cur = _Cur()
    monkeypatch.setattr(setup_db.settings.api, "keys", "k1,k2", raising=False)
    setup_db._bootstrap_registry(cur)
    stmts = [s for s, _ in cur.sql]
    assert any("INSERT INTO public.graphs" in s and "ON CONFLICT (id) DO NOTHING" in s for s in stmts)
    key_inserts = [p for s, p in cur.sql if "INSERT INTO public.api_keys" in s]
    assert len(key_inserts) == 2
    assert all("ON CONFLICT (key_hash) DO NOTHING" in s for s, _ in cur.sql if "public.api_keys" in s and "INSERT" in s)
```

- [ ] **Step 2: Run to verify failure** — `uv run --extra dev pytest -q -p no:cacheprovider tests/test_tenancy tests/test_scripts/test_setup_db_registry.py` → FAIL (modules/attrs missing).

- [ ] **Step 3: Implement** — `src/tenancy/registry.py`:

```python
"""PG-backed graph registry (``public.graphs``), TTL-cached per process."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from loguru import logger

from src.tenancy.context import (
    DEFAULT_GRAPH_ID,
    GraphContext,
    InvalidGraphId,
    default_graph_context,
    validate_graph_id,
)

_COLS = (
    "id, owner, status, nebula_space, nebula_partition_num, chunks_collection, "
    "er_vec_collection, report_vec_collection, pg_schema"
)


class GraphNotFound(LookupError):
    def __init__(self, graph_id: str) -> None:
        super().__init__(f"graph not found: {graph_id!r}")
        self.graph_id = graph_id


class GraphNotReady(RuntimeError):
    def __init__(self, graph_id: str, status: str) -> None:
        super().__init__(f"graph {graph_id!r} is {status}")
        self.graph_id, self.status = graph_id, status


async def _load_row_from_pg(graph_id: str) -> dict | None:
    from psycopg.rows import dict_row

    from src.storage.pg_pool import get_pg_pool

    pool = await get_pg_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"SELECT {_COLS} FROM public.graphs WHERE id = %s", (graph_id,))
        return await cur.fetchone()


def _context_from_row(row: dict) -> GraphContext:
    gid = row["id"]
    return GraphContext(
        id=gid,
        nebula_space=row["nebula_space"],
        nebula_partition_num=int(row["nebula_partition_num"]),
        chunks_collection=row["chunks_collection"],
        er_vec_collection=row["er_vec_collection"],
        report_vec_collection=row["report_vec_collection"],
        pg_schema=row["pg_schema"],
        minio_prefix="" if gid == DEFAULT_GRAPH_ID else f"{gid}/",
    )


class GraphRegistry:
    def __init__(
        self,
        loader: Callable[[str], Awaitable[dict | None]] | None = None,
        ttl_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._loader = loader or _load_row_from_pg
        self._ttl = ttl_s
        self._clock = clock
        self._cache: dict[str, tuple[float, dict | None]] = {}
        self._warned_default = False

    def invalidate(self, graph_id: str | None = None) -> None:
        if graph_id is None:
            self._cache.clear()
        else:
            self._cache.pop(graph_id, None)

    async def get_row(self, graph_id: str) -> dict | None:
        now = self._clock()
        hit = self._cache.get(graph_id)
        if hit is not None and now - hit[0] < self._ttl:
            return hit[1]
        row = await self._loader(graph_id)
        self._cache[graph_id] = (now, row)
        return row

    async def get(self, graph_id: str) -> GraphContext:
        try:
            validate_graph_id(graph_id)
        except InvalidGraphId:
            raise GraphNotFound(graph_id) from None
        try:
            row = await self.get_row(graph_id)
        except Exception:
            if graph_id != DEFAULT_GRAPH_ID:
                raise
            row = None
        if row is None:
            if graph_id == DEFAULT_GRAPH_ID:
                if not self._warned_default:
                    logger.warning("graph registry: no 'default' row; using built-in default context")
                    self._warned_default = True
                return default_graph_context()
            raise GraphNotFound(graph_id)
        if row["status"] != "ready":
            raise GraphNotReady(graph_id, row["status"])
        return _context_from_row(row)


_registry: GraphRegistry | None = None


def get_graph_registry() -> GraphRegistry:
    global _registry
    if _registry is None:
        _registry = GraphRegistry()
    return _registry


def reset_graph_registry_for_tests() -> None:
    global _registry
    _registry = None
```

`src/tenancy/api_keys.py`:

```python
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
```

`scripts/setup_db.py` — add near the other DDL constants:

```python
_GRAPHS_DDL = """
CREATE TABLE IF NOT EXISTS public.graphs (
    id                     TEXT PRIMARY KEY,
    owner                  TEXT NOT NULL,
    status                 TEXT NOT NULL,
    status_error           TEXT NOT NULL DEFAULT '',
    nebula_space           TEXT NOT NULL,
    nebula_partition_num   INTEGER NOT NULL DEFAULT 10,
    chunks_collection      TEXT NOT NULL,
    er_vec_collection      TEXT NOT NULL,
    report_vec_collection  TEXT NOT NULL,
    pg_schema              TEXT NOT NULL,
    max_inflight           INTEGER,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_API_KEYS_DDL = """
CREATE TABLE IF NOT EXISTS public.api_keys (
    key_hash    TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    graph_ids   TEXT[] NOT NULL DEFAULT '{}',
    is_admin    BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _bootstrap_registry(cur) -> None:
    """Idempotent: register `default` under its legacy names and the env
    API_KEYS as admin keys for `default`."""
    from src.tenancy.api_keys import hash_api_key
    from src.tenancy.context import default_graph_context

    d = default_graph_context()
    cur.execute(
        "INSERT INTO public.graphs (id, owner, status, nebula_space, nebula_partition_num, "
        "chunks_collection, er_vec_collection, report_vec_collection, pg_schema) "
        "VALUES (%s, %s, 'ready', %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
        (d.id, "system", d.nebula_space, d.nebula_partition_num, d.chunks_collection,
         d.er_vec_collection, d.report_vec_collection, d.pg_schema),
    )
    for raw in [k.strip() for k in settings.api.keys.split(",") if k.strip()]:
        cur.execute(
            "INSERT INTO public.api_keys (key_hash, owner, graph_ids, is_admin) "
            "VALUES (%s, 'legacy-env', ARRAY['default'], true) ON CONFLICT (key_hash) DO NOTHING",
            (hash_api_key(raw),),
        )
```

In `setup_postgres()`, after `cur.execute(_BOT_INDEXES_DDL)` add `cur.execute(_GRAPHS_DDL)`, `cur.execute(_API_KEYS_DDL)`, `_bootstrap_registry(cur)` (Task 3 reorganizes the function; keep these three calls in the global section there).

- [ ] **Step 4: Run** the three test files → PASS; then SUITE.
- [ ] **Step 5: Commit**

```bash
git add src/tenancy tests/test_tenancy scripts/setup_db.py tests/test_scripts/test_setup_db_registry.py
git commit -m "feat(tenancy): PG-backed graph registry and API key store; registry DDL + bootstrap"
```

### Task 3: Postgres graph scoping (`search_path`), per-graph schema migration, PG storage classes take a graph

**Files:**
- Create: `src/storage/pg_scope.py`
- Modify: `src/storage/pg_pool.py`, `src/storage/pg_sync_pool.py` (add `reset=` callbacks), `src/storage/postgres.py` (`AsyncPostgres`), `src/storage/ingest_metrics.py`, `src/storage/stats.py` (`StatsRepository`), `src/storage/entity_search.py`, `src/graph/entity_table.py` (`mirror_entities`), `src/graph/er_graph_ops.py` (`PostgresERVerdictCache`), `src/di/providers.py` (drop the app-scoped `AsyncPostgres` provider), `scripts/setup_db.py` (split DDL into global vs graph; `migrate_graph_schema(cur, ctx)`), every constructor call site of those classes (grep below).
- Test: `tests/test_storage/test_pg_scope.py`, `tests/test_scripts/test_setup_db_graph_schema.py`, adjust existing storage tests to pass a graph.

**Interfaces:**
- Consumes: Task 1 `GraphContext`, `transitional_default_graph`.
- Produces:
  - `graph_connection(graph: GraphContext) -> AsyncContextManager[psycopg.AsyncConnection]` (pooled; `SET search_path` committed before yield)
  - `graph_sync_connection(graph: GraphContext, *, timeout: float | None = None) -> ContextManager[psycopg.Connection]`
  - `search_path_sql(graph: GraphContext) -> psycopg.sql.Composed`
  - `async reset_search_path(conn)` / `reset_search_path_sync(conn)` (pool `reset=` callbacks)
  - `AsyncPostgres(dsn: str | None = None, *, graph: GraphContext)`; same `*, graph: GraphContext` keyword on `IngestMetricsStore`-equivalent class in `ingest_metrics.py`, `StatsRepository`, the entity-search class in `entity_search.py`, `PostgresERVerdictCache`; `mirror_entities(graph: GraphContext, rows)` (graph first param) — check each class/func's current name and keep it.
  - `scripts.setup_db.GRAPH_DDL: list[str]`, `GLOBAL_DDL: list[str]`, `migrate_graph_schema(cur, graph: GraphContext) -> None`

- [ ] **Step 1: Write the failing tests** — `tests/test_storage/test_pg_scope.py`:

```python
from contextlib import asynccontextmanager, contextmanager

import pytest

from src.storage import pg_scope
from src.tenancy.context import default_graph_context, new_graph_context


class _AConn:
    def __init__(self):
        self.log = []

    async def execute(self, q, params=None):
        self.log.append(("execute", q.as_string(None) if hasattr(q, "as_string") else str(q)))

    async def commit(self):
        self.log.append(("commit",))

    async def rollback(self):
        self.log.append(("rollback",))


class _APool:
    def __init__(self):
        self.conn = _AConn()

    @asynccontextmanager
    async def connection(self, timeout=None):
        yield self.conn


def test_search_path_sql_quotes_identifier():
    s = pg_scope.search_path_sql(new_graph_context("acme")).as_string(None)
    assert s == 'SET search_path TO "g_acme", public'
    assert pg_scope.search_path_sql(default_graph_context()).as_string(None) == 'SET search_path TO "public", public'


async def test_graph_connection_commits_set_before_yield(monkeypatch):
    pool = _APool()

    async def fake_get_pool():
        return pool
    monkeypatch.setattr(pg_scope, "get_pg_pool", fake_get_pool)
    async with pg_scope.graph_connection(new_graph_context("acme")) as conn:
        assert conn.log == [("execute", 'SET search_path TO "g_acme", public'), ("commit",)]
        await conn.rollback()  # a later rollback cannot revert a committed SET


async def test_reset_callback_resets_search_path_and_commits():
    conn = _AConn()
    await pg_scope.reset_search_path(conn)
    assert conn.log == [("execute", "RESET search_path"), ("commit",)]


def test_sync_reset_callback():
    log = []

    class C:
        def execute(self, q, params=None):
            log.append(("execute", str(q)))

        def commit(self):
            log.append(("commit",))
    pg_scope.reset_search_path_sync(C())
    assert log == [("execute", "RESET search_path"), ("commit",)]


def test_pools_install_reset_callbacks(monkeypatch):
    import src.storage.pg_pool as ap
    import src.storage.pg_sync_pool as sp
    seen = {}

    class FakeAsyncPool:
        def __init__(self, **kw):
            seen["async"] = kw.get("reset")

        async def open(self):
            pass

    class FakeSyncPool:
        def __init__(self, **kw):
            seen["sync"] = kw.get("reset")

        def open(self, *a, **k):
            pass
    monkeypatch.setattr(ap, "AsyncConnectionPool", FakeAsyncPool)
    monkeypatch.setattr(sp, "ConnectionPool", FakeSyncPool)
    ap.reset_for_tests()
    monkeypatch.setattr(sp, "_pool", None)
    import asyncio
    asyncio.run(ap.get_pg_pool())
    sp.get_pg_sync_pool()
    assert seen["async"] is pg_scope.reset_search_path
    assert seen["sync"] is pg_scope.reset_search_path_sync
    ap.reset_for_tests()
    monkeypatch.setattr(sp, "_pool", None)
```

If `pg_sync_pool.get_pg_sync_pool()` calls `pool.open(wait=...)` or passes `open=` differently, adapt `FakeSyncPool` to accept it; keep the `reset` assertion.

`tests/test_scripts/test_setup_db_graph_schema.py`:

```python
from scripts import setup_db
from src.tenancy.context import default_graph_context, new_graph_context


class _Cur:
    def __init__(self):
        self.sql = []

    def execute(self, q, params=None):
        self.sql.append(q.as_string(None) if hasattr(q, "as_string") else str(q))


def test_graph_ddl_contains_every_graph_table_and_no_global_one():
    joined = "\n".join(setup_db.GRAPH_DDL)
    for t in ("documents", "ingest_metrics", "fact_supersede", "stat_indicator", "stat_observation", "er_verdict", "entity"):
        assert f"CREATE TABLE IF NOT EXISTS {t}" in joined, t
    for t in ("bot_user", "bot_request", "graphs", "api_keys"):
        assert t not in joined


def test_migrate_new_graph_creates_schema_and_scopes_ddl():
    cur = _Cur()
    setup_db.migrate_graph_schema(cur, new_graph_context("acme"))
    assert cur.sql[0] == 'CREATE SCHEMA IF NOT EXISTS "g_acme"'
    assert cur.sql[1] == 'SET search_path TO "g_acme", public'
    assert cur.sql[2 : 2 + len(setup_db.GRAPH_DDL)] == setup_db.GRAPH_DDL
    assert cur.sql[-1] == "RESET search_path"


def test_migrate_default_graph_does_not_create_public():
    cur = _Cur()
    setup_db.migrate_graph_schema(cur, default_graph_context())
    assert not any(s.startswith("CREATE SCHEMA") for s in cur.sql)
    assert cur.sql[0] == 'SET search_path TO "public", public'
```

- [ ] **Step 2: Run to verify failure** — `uv run --extra dev pytest -q -p no:cacheprovider tests/test_storage/test_pg_scope.py tests/test_scripts/test_setup_db_graph_schema.py` → FAIL.

- [ ] **Step 3: Implement `src/storage/pg_scope.py`:**

```python
"""Graph-scoped Postgres connections via ``search_path``.

Each graph's tables live in its own schema (``public`` for `default`).  The
SET is committed immediately so a later rollback inside the caller's block
cannot silently revert it; the pools' ``reset`` callbacks restore the
default path when a connection returns, so no schema leaks into the next
checkout (bot tables, another graph)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from psycopg import sql

from src.storage.pg_pool import get_pg_pool
from src.tenancy.context import GraphContext


def search_path_sql(graph: GraphContext) -> sql.Composed:
    return sql.SQL("SET search_path TO {}, public").format(sql.Identifier(graph.pg_schema))


async def reset_search_path(conn) -> None:
    await conn.execute("RESET search_path")
    await conn.commit()


def reset_search_path_sync(conn) -> None:
    conn.execute("RESET search_path")
    conn.commit()


@asynccontextmanager
async def graph_connection(graph: GraphContext) -> AsyncIterator:
    pool = await get_pg_pool()
    async with pool.connection() as conn:
        await conn.execute(search_path_sql(graph))
        await conn.commit()
        yield conn


@contextmanager
def graph_sync_connection(graph: GraphContext, *, timeout: float | None = None) -> Iterator:
    from src.storage.pg_sync_pool import get_pg_sync_pool

    with get_pg_sync_pool().connection(timeout=timeout) as conn:
        conn.execute(search_path_sql(graph))
        conn.commit()
        yield conn
```

Pools: in `src/storage/pg_pool.py` add `reset=reset_search_path` to the `AsyncConnectionPool(...)` call (import inside the function: `from src.storage.pg_scope import reset_search_path` to avoid an import cycle, since `pg_scope` imports `pg_pool`); same in `pg_sync_pool.py` with `reset=reset_search_path_sync`.

- [ ] **Step 4: Refactor PG storage classes.** Rule for each class that currently does `pool = await get_pg_pool(); async with pool.connection() as conn:` (see `src/storage/{postgres,ingest_metrics,stats,entity_search}.py`): add a required keyword-only `graph: GraphContext` to `__init__`, store it, and replace the pooled branch with `async with graph_connection(self._graph) as conn:`. For the legacy `dsn` branch (`psycopg.AsyncConnection.connect(self._dsn)`), execute `search_path_sql(self._graph)` then `commit()` right after connecting. Example for `AsyncPostgres._conn`:

```python
    def __init__(self, dsn: str | None = None, *, graph: GraphContext) -> None:
        self._dsn = dsn
        self._graph = graph

    @asynccontextmanager
    async def _conn(self) -> AsyncIterator[psycopg.AsyncConnection]:
        if self._dsn is None:
            async with graph_connection(self._graph) as conn:
                yield conn
        else:
            async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
                await conn.execute(search_path_sql(self._graph))
                await conn.commit()
                yield conn
```

Sync users: `src/graph/entity_table.py` `mirror_entities` → take `graph: GraphContext` as first parameter and use `graph_sync_connection(graph, timeout=1)` in place of `get_pg_sync_pool().connection(timeout=1)`; `src/graph/er_graph_ops.py` `PostgresERVerdictCache` → `__init__(self, *, graph: GraphContext)` and draw connections via `graph_sync_connection(self._graph)` wherever it used `get_pg_sync_pool()` (~L189). `src/storage/bot.py` stays unscoped (global tables) — change its SQL to `public.bot_user` / `public.bot_request` explicitly.

Call sites: find with
`grep -rn "AsyncPostgres(\|StatsRepository(\|PostgresERVerdictCache(\|mirror_entities(\|IngestMetrics\|EntitySearch" src scripts tests | grep -v "def \|class "`
and pass `graph=transitional_default_graph()` (import from `src.tenancy.context`) in `src/`; in `scripts/` pass `graph=default_graph_context()`; in tests pass `graph=default_graph_context()`. `src/di/providers.py`: delete the `postgres()` provider and make every former `FromDishka[AsyncPostgres]` route parameter construct `AsyncPostgres(graph=transitional_default_graph())` in the handler body (Task 9 replaces it with the request graph). `NebulaGraphStore.upsert_nodes` calls `mirror_entities(rows)` — pass `transitional_default_graph()` here for now; Task 4 switches it to the store's own graph.

- [ ] **Step 5: `scripts/setup_db.py` split.** Define:

```python
GLOBAL_DDL: list[str] = [_PG_TRGM_DDL, _BOT_USER_DDL, _BOT_REQUEST_DDL, _BOT_INDEXES_DDL, _GRAPHS_DDL, _API_KEYS_DDL]
GRAPH_DDL: list[str] = [
    _DOCUMENTS_DDL, _INGEST_METRICS_DDL, _BACKFILL_SOURCE_CHANNEL_SQL, _FACT_SUPERSEDE_DDL,
    _STAT_INDICATOR_DDL, _STAT_INDICATOR_CONSTRAINTS_DDL, _STAT_OBSERVATION_DDL, _STAT_INDEXES_DDL,
    _ER_VERDICT_DDL, _ENTITY_DDL, _ENTITY_INDEXES_DDL,
]


def migrate_graph_schema(cur, graph) -> None:
    from psycopg import sql

    from src.storage.pg_scope import search_path_sql

    if graph.pg_schema != "public":
        cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(graph.pg_schema)))
    cur.execute(search_path_sql(graph))
    for stmt in GRAPH_DDL:
        cur.execute(stmt)
    cur.execute("RESET search_path")
```

Change the bot DDL constants to create `public.bot_user` / `public.bot_request` (and their indexes on `public.` tables). Rewrite `setup_postgres()`:

```python
def setup_postgres() -> None:
    pg = settings.postgres
    logger.info("postgres setup  host={h}:{p}  db={d}", h=pg.host, p=pg.port, d=pg.db)
    with psycopg.connect(pg.dsn, connect_timeout=pg.connect_timeout_s, autocommit=True) as conn, conn.cursor() as cur:
        for stmt in GLOBAL_DDL:
            cur.execute(stmt)
        _bootstrap_registry(cur)
        for graph in _ready_graphs(cur):
            migrate_graph_schema(cur, graph)
    logger.info("postgres setup  done")


def _ready_graphs(cur) -> list:
    from src.tenancy.registry import _context_from_row

    cur.execute(
        "SELECT id, owner, status, nebula_space, nebula_partition_num, chunks_collection, "
        "er_vec_collection, report_vec_collection, pg_schema FROM public.graphs WHERE status = 'ready' ORDER BY id"
    )
    cols = [d.name for d in cur.description]
    return [_context_from_row(dict(zip(cols, r, strict=True))) for r in cur.fetchall()]
```

Keep the test helper `_Cur` compatible: `_ready_graphs` is not called by the new tests.

- [ ] **Step 6: Run** the two new test files, the storage/graph test dirs (`tests/test_storage tests/test_graph tests/test_api`), then SUITE. Fix call sites until green.
- [ ] **Step 7: Commit**

```bash
git add src scripts tests
git commit -m "feat(pg): graph-scoped search_path connections, per-graph schema migration; PG stores take a GraphContext"
```

### Task 4: Nebula — one session per space, store knows its graph

**Files:**
- Modify: `src/graph/nebula_schema.py` (drop `SPACE_NAME`/module `SPACE_DDL`; `space_ddl(graph)`; `ensure_schema(session, graph, *, use_attempts=30, use_delay_s=1.0)`), `src/graph/nebula_store.py` (`NebulaGraphStore(session, reconnect=None, *, graph)`, per-space cache, `build_nebula_graph_store(graph)`), `src/graph/store.py` (`build_graph_store(graph)`), `src/config.py` (delete dead `NebulaSettings.space` field and its comment), `scripts/wipe_db.py` (log line that read `settings.nebula.space`), every call site of `build_graph_store()` (18 in `src/`, 5 in `scripts/` — list: `src/graph/merge_and_resolve.py:268`, `src/mcp/tools_server.py:102`, `src/workflow/monitor/activities.py:32`, `src/workflow/wiki/wiki_sweep.py:38,56`, `src/workflow/_search_deps.py:69`, `src/workflow/search/activities/documents.py:64`, `src/workflow/search/activities/global_search.py:71`, `src/workflow/search/activities/community.py:145`, `src/workflow/activities/mark_dirty.py:26`, `src/workflow/activities/push_wikibase.py:51`, `src/workflow/analytics/activities.py:53`, `src/workflow/activities/merge_and_resolve.py:273`, `src/api/routes/admin.py:24,58`, `src/api/routes/graph_admin.py:31`, `src/api/routes/entities.py:39`, `src/workflow/analytics/materialize_activities.py:27`, `scripts/{migrate_er_verdicts,setup_wikibase,backfill_entity_table,smoke_wikibase_push}.py`).
- Test: `tests/test_graph/test_nebula_schema.py`, `tests/test_graph/test_nebula_pool_recovery.py` (adjust), new `tests/test_graph/test_nebula_per_space.py`.

**Interfaces:**
- Consumes: `GraphContext`, `transitional_default_graph`, `default_graph_context`.
- Produces: `space_ddl(graph) -> str`; `ensure_schema(session, graph, *, use_attempts=30, use_delay_s=1.0) -> None`; `build_nebula_graph_store(graph: GraphContext) -> NebulaGraphStore` (cached per `graph.nebula_space`, one shared `ConnectionPool`); `build_graph_store(graph: GraphContext) -> NebulaGraphStore`; `NebulaGraphStore.graph: GraphContext`; `reset_nebula_stores_for_tests() -> None`.

- [ ] **Step 1: Write the failing tests** — `tests/test_graph/test_nebula_per_space.py`:

```python
import src.graph.nebula_store as ns
from src.graph import nebula_schema
from src.tenancy.context import default_graph_context, new_graph_context


class _Sess:
    def __init__(self, log):
        self.log = log

    def execute(self, stmt):
        self.log.append(stmt)
        return type("R", (), {"is_succeeded": lambda s: True, "error_msg": lambda s: "", "error_code": lambda s: 0})()


def test_space_ddl_uses_graph_names():
    assert nebula_schema.space_ddl(default_graph_context()) == (
        "CREATE SPACE IF NOT EXISTS `kb` (partition_num=100, replica_factor=1, vid_type=FIXED_STRING(32));"
    )
    assert nebula_schema.space_ddl(new_graph_context("acme")) == (
        "CREATE SPACE IF NOT EXISTS `g_acme` (partition_num=10, replica_factor=1, vid_type=FIXED_STRING(32));"
    )


def test_ensure_schema_uses_the_graph_space():
    log = []
    nebula_schema.ensure_schema(_Sess(log), new_graph_context("acme"), use_attempts=1, use_delay_s=0)
    assert log[0].startswith("CREATE SPACE IF NOT EXISTS `g_acme`")
    assert log[1] == "USE `g_acme`;"
    assert not any("`kb`" in s for s in log)


def test_stores_are_cached_per_space_and_share_one_pool(monkeypatch):
    ns.reset_nebula_stores_for_tests()
    pools = []

    class FakePool:
        def __init__(self):
            pools.append(self)

        def init(self, *a, **k):
            return True

    used = []
    monkeypatch.setattr("nebula3.gclient.net.ConnectionPool", FakePool)
    monkeypatch.setattr(ns, "_acquire_session", lambda pool, u, p: object())
    monkeypatch.setattr(ns, "ensure_schema", lambda sess, graph: used.append(graph.nebula_space))
    a1 = ns.build_nebula_graph_store(new_graph_context("acme"))
    a2 = ns.build_nebula_graph_store(new_graph_context("acme"))
    d = ns.build_nebula_graph_store(default_graph_context())
    assert a1 is a2 and a1 is not d
    assert a1.graph.nebula_space == "g_acme" and d.graph.nebula_space == "kb"
    assert len(pools) == 1
    assert used == ["g_acme", "kb"]
    ns.reset_nebula_stores_for_tests()


def test_reconnect_reuses_the_graph_space(monkeypatch):
    ns.reset_nebula_stores_for_tests()
    monkeypatch.setattr("nebula3.gclient.net.ConnectionPool", lambda: type("P", (), {"init": lambda s, *a, **k: True})())
    monkeypatch.setattr(ns, "_acquire_session", lambda pool, u, p: object())
    used = []
    monkeypatch.setattr(ns, "ensure_schema", lambda sess, graph: used.append(graph.nebula_space))
    store = ns.build_nebula_graph_store(new_graph_context("acme"))
    store._reconnect()
    assert used == ["g_acme", "g_acme"]
    ns.reset_nebula_stores_for_tests()
```

Adapt `_Sess.execute`'s result stub to whatever `_execute_with_retry` in `nebula_schema.py` inspects (read it first); keep the assertions on statement text.

- [ ] **Step 2: Run to verify failure** → FAIL (`space_ddl`/`reset_nebula_stores_for_tests` missing, signature mismatch).

- [ ] **Step 3: Implement.** `nebula_schema.py`: delete `SPACE_NAME` and the module-level `SPACE_DDL`; add

```python
def space_ddl(graph) -> str:
    return (
        f"CREATE SPACE IF NOT EXISTS `{graph.nebula_space}` "
        f"(partition_num={graph.nebula_partition_num}, replica_factor=1, vid_type=FIXED_STRING(32));"
    )
```

and change `ensure_schema(session, graph, *, use_attempts=30, use_delay_s=1.0)`: step 1 executes `space_ddl(graph)`, step 2 `USE \`{graph.nebula_space}\`;`, the warning logs `graph.nebula_space`. Replace every other `SPACE_NAME` use in the file (docstrings/logs) with the graph's space. `graph.nebula_space` is safe to interpolate: it comes from a validated slug (`g_<slug>`) or the literal `kb`.

`nebula_store.py`: replace `_store` with `_stores: dict[str, NebulaGraphStore] = {}`; keep `_pool` (shared) and `_lock`. `NebulaGraphStore.__init__(self, session, reconnect=None, *, graph)` stores `self.graph = graph`; `upsert_nodes` calls `mirror_entities(self.graph, rows)`. New builder:

```python
def _shared_pool() -> Any:
    global _pool
    if _pool is None:
        from nebula3.Config import Config
        from nebula3.gclient.net import ConnectionPool

        cfg = settings.nebula
        pool_config = Config()
        pool_config.interval_check = cfg.pool_health_check_s
        pool = ConnectionPool()
        pool.init([(cfg.host, cfg.port)], pool_config)
        _pool = pool
    return _pool


def build_nebula_graph_store(graph: GraphContext) -> NebulaGraphStore:
    """One store (session) per graph space; one ConnectionPool per process.

    <keep the existing docstring paragraphs about reconnect/ensure_schema>"""
    key = graph.nebula_space
    store = _stores.get(key)
    if store is not None:
        return store
    with _lock:
        store = _stores.get(key)
        if store is None:
            pool = _shared_pool()
            cfg = settings.nebula
            user, password = cfg.user, cfg.password.get_secret_value()

            def _new_session() -> Any:
                sess = _acquire_session(pool, user, password)
                ensure_schema(sess, graph)
                return sess

            store = NebulaGraphStore(_new_session(), reconnect=_new_session, graph=graph)
            _stores[key] = store
    return store


def reset_nebula_stores_for_tests() -> None:
    global _pool
    _stores.clear()
    _pool = None
```

`store.py`: `def build_graph_store(graph: GraphContext) -> NebulaGraphStore: return nebula_store.build_nebula_graph_store(graph)`.
Call sites: `src/` → `build_graph_store(transitional_default_graph())`; `scripts/` → `build_graph_store(default_graph_context())`. Existing tests that monkeypatch `build_graph_store` / `build_nebula_graph_store` with zero-arg lambdas: change the lambdas to accept `graph` (or `*a, **k`). Existing `NebulaGraphStore(...)` constructions in tests: add `graph=default_graph_context()`.

- [ ] **Step 4: Run** new + existing nebula tests (`tests/test_graph`), then SUITE.
- [ ] **Step 5: Commit**

```bash
git add src scripts tests
git commit -m "feat(nebula): per-graph space sessions over one pool; store carries its GraphContext"
```

### Task 5: Milvus collections and MinIO keys per graph

**Files:**
- Modify: `src/retrieval/vector_index.py` (`build_vector_store(graph, *, overwrite=False)`), `src/storage/chunk_repository.py` (`ChunkRepository(*, graph, milvus_client=None, collection=None, pg=None, minio=None)`), `src/graph/entity_vector_store_milvus.py` / `community_vector_store_milvus.py` (drop `_COLLECTION`; require `collection`), `src/graph/entity_vector_store.py` / `community_vector_store.py` (`build_*_vector_store(graph: GraphContext)`), `src/storage/minio.py` (`graph_object_key(graph, key) -> str`), `src/api/routes/ingest.py:125` (object key), call sites: `build_vector_store` (`src/ingestion/run.py:76`, `src/mcp/tools_server.py:91`, `src/workflow/_search_deps.py:52`, `src/workflow/activities/index_vector.py:170`, `scripts/backfill_doc_id.py:97`), `ChunkRepository(` (`src/mcp/tools_server.py:123`, `src/workflow/_search_deps.py:88`), `build_entity_vector_store(` (`src/graph/retriever.py:213`, `src/graph/merge_and_resolve.py:272`, `src/workflow/activities/merge_and_resolve.py:277`), `build_community_report_vector_store(` (`src/workflow/search/activities/community.py:471`, `src/workflow/search/activities/global_search.py:109,155`).
- Test: `tests/test_tenancy/test_storage_names.py` (new), adjust existing vector-store tests.

**Interfaces:**
- Produces: `build_vector_store(graph: GraphContext, *, overwrite: bool = False)`; `ChunkRepository(*, graph: GraphContext, ...)` (its `AsyncPostgres` default becomes `AsyncPostgres(graph=graph)`); `MilvusEntityVectorStore(collection: str, client=None)`; `MilvusCommunityReportVectorStore(collection: str, client=None)`; `build_entity_vector_store(graph: GraphContext)`; `build_community_report_vector_store(graph: GraphContext)`; `graph_object_key(graph: GraphContext, key: str) -> str`.

- [ ] **Step 1: Write the failing test** — `tests/test_tenancy/test_storage_names.py`:

```python
from src.tenancy.context import default_graph_context, new_graph_context


def test_vector_store_uses_graph_chunks_collection(monkeypatch):
    import src.retrieval.vector_index as vi
    seen = {}

    class FakeMVS:
        def __init__(self, **kw):
            seen.update(kw)
    monkeypatch.setattr(vi, "MilvusVectorStore", FakeMVS)
    vi.build_vector_store(new_graph_context("acme"))
    assert seen["collection_name"] == "g_acme_chunks"
    vi.build_vector_store(default_graph_context())
    assert seen["collection_name"] == default_graph_context().chunks_collection


def test_er_and_report_factories_use_graph_collections(monkeypatch):
    from src.graph import community_vector_store_milvus as cm
    from src.graph import entity_vector_store_milvus as em
    from src.graph.community_vector_store import build_community_report_vector_store
    from src.graph.entity_vector_store import build_entity_vector_store

    monkeypatch.setattr(em, "MilvusClient", lambda **kw: object(), raising=False)
    monkeypatch.setattr(cm, "MilvusClient", lambda **kw: object(), raising=False)
    g = new_graph_context("acme")
    assert build_entity_vector_store(g)._collection == "g_acme_er_vec"
    assert build_community_report_vector_store(g)._collection == "g_acme_report_vec"
    d = default_graph_context()
    assert build_entity_vector_store(d)._collection == "entity_er_vec"
    assert build_community_report_vector_store(d)._collection == "community_report_vec"


def test_chunk_repository_uses_graph_collection():
    from src.storage.chunk_repository import ChunkRepository
    repo = ChunkRepository(graph=new_graph_context("acme"), milvus_client=object(), pg=object())
    assert repo._collection == "g_acme_chunks"


def test_minio_keys_are_prefixed_only_for_non_default():
    from src.storage.minio import graph_object_key
    assert graph_object_key(default_graph_context(), "d1/f.pdf") == "d1/f.pdf"
    assert graph_object_key(new_graph_context("acme"), "d1/f.pdf") == "acme/d1/f.pdf"
```

Check how the two Milvus stores import/construct `MilvusClient` and what the collection attribute is named (`_collection` assumed); patch the name they actually use and adjust the attribute name in the assertions if different — keep the values.

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the signatures above. `graph_object_key`:

```python
def graph_object_key(graph, key: str) -> str:
    """MinIO object key inside the graph's prefix (`default` keeps legacy unprefixed keys)."""
    return f"{graph.minio_prefix}{key}"
```

`src/api/routes/ingest.py`: `object_key = graph_object_key(transitional_default_graph(), f"{doc_id}/{file.filename}")` (Task 9 swaps in the request graph). Call sites in `src/` pass `transitional_default_graph()`; scripts pass `default_graph_context()`; `retriever.py`/`merge_and_resolve.py` pass the graph they already hold (`graph_store.graph`) — `GraphRetriever.for_store(store, ...)` has the store, use `store.graph`.
- [ ] **Step 4: Run** new test, `tests/test_graph tests/test_storage tests/test_retrieval tests/test_api`, then SUITE.
- [ ] **Step 5: Commit**

```bash
git add src scripts tests
git commit -m "feat(storage): per-graph Milvus collections and MinIO key prefixes"
```

### Task 6: Per-graph process caches (search deps, MCP tools deps, API cached helpers)

**Files:**
- Modify: `src/workflow/_search_deps.py`, `src/mcp/tools_server.py` (`_deps`, `_init`, `_r/_g/_c/_gs`), `src/api/routes/graph_admin.py` (`_store`), `src/api/routes/entities.py` (`_retriever`)
- Test: `tests/test_workflow/test_search_deps_per_graph.py` (new), adjust existing `_search_deps`/tools_server tests.

**Interfaces:**
- Consumes: Tasks 3–5 builders taking `graph`.
- Produces (graph-aware accessors; graph-agnostic ones unchanged):
  - `_search_deps`: `get_retriever(graph)`, `get_vector_retriever(graph)`, `get_graph_retriever(graph)`, `get_chunk_repository(graph)` — cached per `graph.id`; `get_search_llm()`, `get_synthesizer()`, `get_synthesis_llm()`, `get_synthesis_synthesizer()`, `get_reranker()` stay process-global (same signatures). `reset_for_tests()` clears both.
  - `tools_server`: `_init(graph)`, `_r(graph)`, `_g(graph)`, `_c(graph)`, `_gs(graph)` keyed per graph.
  - `graph_admin._store(graph_id: str)` / `entities._retriever(graph_id: str)` keep `@functools.cache` but keyed by graph id and build via `await`-free registry-resolved context passed in by the caller: signature `_store(graph: GraphContext)` with an internal `dict[str, store]` instead of `functools.cache` (a dataclass is hashable, but keying by `graph.id` is explicit).

- [ ] **Step 1: Write the failing test** — `tests/test_workflow/test_search_deps_per_graph.py`:

```python
import src.workflow._search_deps as sd
from src.tenancy.context import default_graph_context, new_graph_context


async def test_chunk_repository_is_cached_per_graph(monkeypatch):
    sd.reset_for_tests()
    built = []

    class FakeRepo:
        def __init__(self, *, graph, **kw):
            built.append(graph.id)
            self.graph = graph
    monkeypatch.setattr(sd, "ChunkRepository", FakeRepo)
    a1 = await sd.get_chunk_repository(new_graph_context("acme"))
    a2 = await sd.get_chunk_repository(new_graph_context("acme"))
    d = await sd.get_chunk_repository(default_graph_context())
    assert a1 is a2 and a1 is not d
    assert built == ["acme", "default"]
    sd.reset_for_tests()


async def test_llm_stays_process_global(monkeypatch):
    sd.reset_for_tests()
    calls = []

    class Pool:
        def get(self, role):
            calls.append(role)
            return object()
    monkeypatch.setattr(sd, "get_llm_pool", lambda: Pool(), raising=False)
    assert await sd.get_search_llm() is await sd.get_search_llm()
    sd.reset_for_tests()
```

Read `_search_deps.py` first: if `ChunkRepository` / the LLM pool are imported inside functions, patch the source module (`src.storage.chunk_repository.ChunkRepository`, `src.retrieval.llm_pool.get_llm_pool`) instead; keep assertions.

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** In `_search_deps.py` split `_state` into `_global: dict[str, Any]` (llm, synthesizer, synthesis_*, reranker, embed model) and `_per_graph: dict[str, dict[str, Any]]` keyed by `graph.id` (retriever, vector index, graph_retriever, chunk_repository). Builders take `graph` and call `build_vector_store(graph)`, `build_graph_store(graph)`, `ChunkRepository(graph=graph)`. Callers of the graph-aware getters (search activities, `src/workflow/search/**`) pass `transitional_default_graph()` for now. Same pattern in `tools_server.py` (`_deps_by_graph: dict[str, dict]`), tool bodies pass `transitional_default_graph()` for now. `graph_admin._store` / `entities._retriever`: replace `@functools.cache` with a module dict keyed by `graph.id`; routes pass `transitional_default_graph()` for now.
- [ ] **Step 4: Run** new test + `tests/test_workflow tests/test_mcp tests/test_api`, then SUITE.
- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "feat: per-graph caches for search deps, MCP tool deps and API helpers"
```

### Task 7: Temporal contracts carry `graph_id`; workflows propagate it; graph-scoped workflow ids

**Files:**
- Modify: `src/workflow/contracts.py`, `src/analytics/contracts.py`, every workflow module (`src/workflow/document_ingest.py`, `ingest_scheduler.py`, `graph_build.py`, `monitor/workflow.py`, `wiki/wiki_sweep.py`, `search/global_wf.py`, `search/router_wf.py`, `search/community_wf.py`, `search/orchestrator.py`, `search/subquery_wf.py`, `analytics/workflow.py`, `analytics/materialize_workflow.py`), every `start_workflow`/`execute_workflow`/child-workflow id listed in the inventory below.
- Test: `tests/test_workflow/test_graph_id_contracts.py` (new)

Workflow ids to convert with `graph_scoped_id(prefix, graph_id, suffix)`: `ingest-{doc_id}` (`src/ingest_queue/consumer.py:67-82`, `src/workflow/ingest_scheduler.py:129-136`), `graph-{doc_id}` (`src/workflow/document_ingest.py:259-265`), `mcp-{kind}-{uuid}` (`src/mcp/search_server.py:287,334,391,447,471`), `search-{kind}-{request_id}` (`src/api/routes/search_v2.py:154,188,222,256`), `community-build-{request_id}` (`search_v2.py:293`), `analytics-materialize-{request_id}` (`src/api/routes/graph_admin.py:116`), `analyze-{request_id}` (`src/api/routes/analyze.py:36`). Child ids derived from `workflow.info().workflow_id` already inherit the parent's graph segment — leave them. Fixed ids `ingest-scheduler`, `wiki-sweep-*`, `monitor-sweep-*` stay (system-wide / default-only in Plan A).

**Interfaces:**
- Consumes: `DEFAULT_GRAPH_ID`, `graph_scoped_id`.
- Produces: `graph_id: str = DEFAULT_GRAPH_ID` on: `IngestParams`, `Ctx`, and every model that is (a) the parameter of a `@workflow.run` method or (b) the parameter of an `@activity.defn` that touches storage (graph, Milvus, Postgres, MinIO). Workflows copy `params.graph_id` into every child-workflow input and every such activity input they build.

- [ ] **Step 1: Write the failing test** — `tests/test_workflow/test_graph_id_contracts.py`:

```python
import inspect
import typing

import pytest

from src.tenancy.context import DEFAULT_GRAPH_ID
from src.workflow import worker as w


def _workflow_classes():
    out = set()
    for group in w.WORKER_GROUPS:
        try:
            spec = w.workflows_for_group(group)
        except AttributeError:
            pytest.skip("expose workflows_for_group(group) from worker.py (see Step 3)")
        out.update(spec)
    return out


def _run_input_type(cls):
    run = cls.run
    hints = typing.get_type_hints(run)
    params = [p for p in inspect.signature(run).parameters if p != "self"]
    return hints[params[0]] if params else None


def test_every_workflow_input_carries_graph_id():
    missing = []
    for cls in _workflow_classes():
        t = _run_input_type(cls)
        if t is None:
            continue
        fields = getattr(t, "model_fields", {})
        if "graph_id" not in fields:
            missing.append(f"{cls.__name__}({t.__name__})")
    assert missing == []


def test_legacy_payload_without_graph_id_defaults():
    from src.workflow.contracts import Ctx, IngestParams
    p = IngestParams.model_validate({"doc_id": "d1", "path": "s3://b/k"})
    assert p.graph_id == DEFAULT_GRAPH_ID
    c = Ctx.model_validate({"doc_id": "d1", "local_path": "/x", "cleanup_dir": None, "workflow_run_id": "r"})
    assert c.graph_id == DEFAULT_GRAPH_ID


def test_every_storage_activity_input_carries_graph_id():
    from src.workflow.activity_inputs import STORAGE_ACTIVITY_INPUTS
    missing = [t.__name__ for t in STORAGE_ACTIVITY_INPUTS if "graph_id" not in t.model_fields]
    assert missing == []
```

(Adjust the `IngestParams`/`Ctx` required fields in the legacy test to exactly the fields that have no default in `contracts.py`.)

- [ ] **Step 2: Run** → FAIL/skip (no `workflows_for_group`, no `graph_id`, no `activity_inputs`).

- [ ] **Step 3: Implement.**
  1. `src/workflow/worker.py`: extract the per-group `workflows=[...]` lists from `_build_worker` into `def workflows_for_group(group: str) -> list[type]` and use it inside `_build_worker` (pure refactor).
  2. Add `graph_id: str = DEFAULT_GRAPH_ID` (import from `src.tenancy.context`) to `IngestParams`, `Ctx`, and to each workflow-input model found by the test, plus each storage-touching activity input model. Find activity inputs with `grep -n "@activity.defn" -A3 -r src/workflow src/analytics` and read each body; a model qualifies if the activity (directly or via a helper) calls any of: `build_graph_store`, `build_*_vector_store`, `build_vector_store`, `ChunkRepository`, `AsyncPostgres`, `StatsRepository`, `IngestMetrics*`, `mirror_entities`, `PostgresERVerdictCache`, `build_minio_storage`, `get_retriever/get_graph_retriever/get_chunk_repository/get_vector_retriever`. Record the list in a new module `src/workflow/activity_inputs.py`: `STORAGE_ACTIVITY_INPUTS: tuple[type, ...] = (...)`.
  3. Every workflow copies `graph_id=params.graph_id` into child-workflow params and activity inputs it constructs (including `Ctx` built in `document_ingest.py`, the `IngestParams` kept in the scheduler `pending` list, and the orchestrator sub-query params).
  4. Convert the workflow ids listed above to `graph_scoped_id(...)` using the params' `graph_id` (callers still pass `DEFAULT_GRAPH_ID` until Tasks 9–11, so ids are byte-identical today).
- [ ] **Step 4: Run** the new test (no skips), `tests/test_workflow tests/test_ingest_queue tests/test_mcp tests/test_api`, then SUITE.
- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "feat(temporal): graph_id on workflow and storage-activity inputs; propagate to children; graph-scoped ids"
```

### Task 8: Activities resolve their graph from inputs

**Files:**
- Create: `src/tenancy/activity.py`
- Modify: every activity/helper under `src/workflow/**` and `src/graph/merge_and_resolve.py`, `src/workflow/_search_deps.py` callers — replace `transitional_default_graph()` with the resolved context.
- Test: `tests/test_tenancy/test_activity_resolve.py`

**Interfaces:**
- Consumes: `get_graph_registry()`, `GraphNotFound`, `GraphNotReady`, Task 7 `graph_id` fields.
- Produces: `async resolve_graph_for_activity(graph_id: str) -> GraphContext` — raises `temporalio.exceptions.ApplicationError(non_retryable=True, type="GraphUnavailable")` on `GraphNotFound`/`GraphNotReady`.

- [ ] **Step 1: Write the failing test:**

```python
import pytest
from temporalio.exceptions import ApplicationError

import src.tenancy.activity as ta
from src.tenancy.context import new_graph_context
from src.tenancy.registry import GraphNotFound, GraphNotReady


class _Reg:
    def __init__(self, result):
        self.result = result

    async def get(self, gid):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def test_resolves_ready_graph(monkeypatch):
    monkeypatch.setattr(ta, "get_graph_registry", lambda: _Reg(new_graph_context("acme")))
    assert (await ta.resolve_graph_for_activity("acme")).id == "acme"


@pytest.mark.parametrize("exc", [GraphNotFound("x"), GraphNotReady("x", "deleting")])
async def test_unavailable_graph_is_non_retryable(monkeypatch, exc):
    monkeypatch.setattr(ta, "get_graph_registry", lambda: _Reg(exc))
    with pytest.raises(ApplicationError) as ei:
        await ta.resolve_graph_for_activity("x")
    assert ei.value.non_retryable is True
    assert ei.value.type == "GraphUnavailable"
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement:**

```python
"""Resolve an activity's graph; unknown/non-ready graphs fail the activity for good."""

from __future__ import annotations

from temporalio.exceptions import ApplicationError

from src.tenancy.context import GraphContext
from src.tenancy.registry import GraphNotFound, GraphNotReady, get_graph_registry


async def resolve_graph_for_activity(graph_id: str) -> GraphContext:
    try:
        return await get_graph_registry().get(graph_id)
    except (GraphNotFound, GraphNotReady) as exc:
        raise ApplicationError(str(exc), type="GraphUnavailable", non_retryable=True) from exc
```

Then in every activity that received `graph_id` in Task 7: `graph = await resolve_graph_for_activity(inp.graph_id)` at the top and pass `graph` down to every storage builder/class that currently gets `transitional_default_graph()`. Sync helpers (`_get_store()` style) take `graph` as a parameter. After this step `grep -rn transitional_default_graph src/workflow src/graph src/analytics` must be empty.
- [ ] **Step 4: Run** new test, `tests/test_workflow tests/test_graph tests/test_analytics`, SUITE. Existing activity tests that monkeypatch `_get_store` etc.: make the fakes accept the new `graph` arg; tests that call activities directly get `graph_id` defaulting to `"default"` and the registry falls back to the built-in default (R-A1) — if a test must not touch PG, monkeypatch `src.tenancy.activity.get_graph_registry` to a stub returning `default_graph_context()` via a shared fixture in `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _offline_graph_registry(monkeypatch):
    from src.tenancy import registry as reg
    from src.tenancy.context import default_graph_context, new_graph_context

    class _Stub:
        async def get(self, gid):
            return default_graph_context() if gid == "default" else new_graph_context(gid)

        def invalidate(self, gid=None):
            pass
    monkeypatch.setattr(reg, "get_graph_registry", lambda: _Stub())
    import src.tenancy.activity as ta
    monkeypatch.setattr(ta, "get_graph_registry", lambda: _Stub())
```

(`tests/conftest.py` currently has only a beartype pre-import; add `import pytest` and this fixture below it.)
- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "feat(tenancy): activities resolve their GraphContext from graph_id (non-retryable when unavailable)"
```

### Task 9: HTTP API — key → graphs auth, `resolve_graph` dependency, routes use the request graph

**Files:**
- Create: `src/api/graph_dep.py`
- Modify: `src/api/auth.py` (`require_api_key` returns an `ApiKeyRecord` via `ApiKeyStore`), `src/api/routes/{ingest,documents,entities,stats,stats_data,search_v2,analyze,admin,graph_admin}.py` (take `graph: GraphContext = Depends(resolve_graph)`, pass it/`graph.id` down; remove `transitional_default_graph()`), `src/ingest_queue/*` callers from `ingest.py` (pass `graph_id` into `IngestParams`)
- Test: `tests/test_api/test_resolve_graph.py` (new), adjust `tests/test_api/*` (send headers / patch the key store).

**Interfaces:**
- Consumes: `get_api_key_store()`, `ApiKeyRecord`, `get_graph_registry()`, `GraphNotFound`, `GraphNotReady`, `DEFAULT_GRAPH_ID`.
- Produces: `async require_api_key(x_api_key: str | None = Header(None, alias="X-API-Key")) -> ApiKeyRecord`; `async resolve_graph(key: ApiKeyRecord = Depends(require_api_key), x_graph: str | None = Header(None, alias="X-Graph")) -> GraphContext`; `choose_graph_id(key: ApiKeyRecord, x_graph: str | None) -> str` (pure, raises `HTTPException`).

- [ ] **Step 1: Write the failing test** — `tests/test_api/test_resolve_graph.py`:

```python
import pytest
from fastapi import HTTPException

from src.api import graph_dep
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.context import new_graph_context
from src.tenancy.registry import GraphNotFound, GraphNotReady

ONE = ApiKeyRecord(owner="a", graph_ids=("acme",), is_admin=False)
TWO = ApiKeyRecord(owner="a", graph_ids=("acme", "acme_hr"), is_admin=False)
ADMIN = ApiKeyRecord(owner="ops", graph_ids=("default",), is_admin=True)


@pytest.mark.parametrize(
    ("key", "hdr", "expected"),
    [(ONE, None, "acme"), (ONE, "acme", "acme"), (TWO, "acme_hr", "acme_hr"), (ADMIN, None, "default"), (ADMIN, "acme", "acme")],
)
def test_choose_graph_ok(key, hdr, expected):
    assert graph_dep.choose_graph_id(key, hdr) == expected


@pytest.mark.parametrize(("key", "hdr", "code"), [(TWO, None, 400), (ONE, "other", 403), (ONE, "Bad;Id", 403)])
def test_choose_graph_errors(key, hdr, code):
    with pytest.raises(HTTPException) as ei:
        graph_dep.choose_graph_id(key, hdr)
    assert ei.value.status_code == code


class _Reg:
    def __init__(self, result):
        self.result = result

    async def get(self, gid):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def test_resolve_graph_maps_registry_errors(monkeypatch):
    monkeypatch.setattr(graph_dep, "get_graph_registry", lambda: _Reg(GraphNotFound("acme")))
    with pytest.raises(HTTPException) as ei:
        await graph_dep.resolve_graph(ONE, None)
    assert ei.value.status_code == 404
    monkeypatch.setattr(graph_dep, "get_graph_registry", lambda: _Reg(GraphNotReady("acme", "deleting")))
    with pytest.raises(HTTPException) as ei:
        await graph_dep.resolve_graph(ONE, None)
    assert ei.value.status_code == 409
    monkeypatch.setattr(graph_dep, "get_graph_registry", lambda: _Reg(new_graph_context("acme")))
    assert (await graph_dep.resolve_graph(ONE, None)).id == "acme"


async def test_require_api_key_statuses(monkeypatch):
    from src.api import auth

    class _Store:
        async def lookup(self, k):
            return ONE if k == "good" else None
    monkeypatch.setattr(auth, "get_api_key_store", lambda: _Store())
    with pytest.raises(HTTPException) as ei:
        await auth.require_api_key(None)
    assert ei.value.status_code == 401
    with pytest.raises(HTTPException) as ei:
        await auth.require_api_key("bad")
    assert ei.value.status_code == 403
    assert await auth.require_api_key("good") == ONE
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** `src/api/auth.py`:

```python
async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> ApiKeyRecord:
    if x_api_key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-API-Key header")
    rec = await get_api_key_store().lookup(x_api_key)
    if rec is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid X-API-Key")
    return rec


async def require_admin(key: ApiKeyRecord = Depends(require_api_key)) -> ApiKeyRecord:
    if not key.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin key required")
    return key
```

`src/api/graph_dep.py`:

```python
"""Bind each HTTP request to exactly one graph (spec §2)."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from src.api.auth import require_api_key
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.context import GraphContext, InvalidGraphId, validate_graph_id
from src.tenancy.registry import GraphNotFound, GraphNotReady, get_graph_registry


def choose_graph_id(key: ApiKeyRecord, x_graph: str | None) -> str:
    if x_graph is None:
        if len(key.graph_ids) == 1:
            return key.graph_ids[0]
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Graph header required for this key")
    try:
        validate_graph_id(x_graph)
    except InvalidGraphId:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "graph not allowed for this key") from None
    if key.is_admin or x_graph in key.graph_ids:
        return x_graph
    raise HTTPException(status.HTTP_403_FORBIDDEN, "graph not allowed for this key")


async def resolve_graph(
    key: ApiKeyRecord = Depends(require_api_key),
    x_graph: str | None = Header(default=None, alias="X-Graph"),
) -> GraphContext:
    gid = choose_graph_id(key, x_graph)
    try:
        return await get_graph_registry().get(gid)
    except GraphNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"graph {gid!r} not found") from None
    except GraphNotReady as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"graph {gid!r} is {exc.status}") from None
```

Routes: add `graph: GraphContext = Depends(resolve_graph)` to every handler under `/api/v1` and the graph-level admin handlers (`/admin/graph/*`, `/admin/monitor/*`, `/admin/wiki/*`, `/api/v1/admin/communities/rebuild`); admin handlers additionally depend on `require_admin`. Replace each `transitional_default_graph()` with `graph`; set `graph_id=graph.id` on every `IngestParams`/workflow params built in routes; ingest object key via `graph_object_key(graph, ...)`. Wiki admin endpoints: if `not graph.is_default` return HTTP 409 `"wiki is available only for the default graph"` (D6).
Existing API tests: they previously relied on `settings.api.keys_list`; the legacy fallback (R-A3) keeps them valid when `public.api_keys` lookups are stubbed. Add to `tests/test_api/conftest.py` (create if absent) an autouse fixture that monkeypatches `src.tenancy.api_keys._load_key_row` to `async def _none(h): return None` and resets the store (`reset_api_key_store_for_tests()`), so tests stay DB-free.
- [ ] **Step 4: Run** new test + `tests/test_api`, SUITE.
- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "feat(api): API keys map to graphs; every request is bound to one graph via X-Graph"
```

### Task 10: MCP — registry-backed token verifier and connection-bound graph

**Files:**
- Modify: `src/mcp/_shared.py` (`build_sse_auth` → `RegistryTokenVerifier`; add `current_graph()`), `src/mcp/tools_server.py`, `src/mcp/search_server.py`, `src/mcp/stats_server.py` (every tool resolves `graph = await current_graph()` and passes it / `graph.id`), `src/config.py` (new `mcp_graph: str = "default"` on the MCP-related settings class, env `KB_MCP_GRAPH` — find where `KB_MCP_REQUIRE_AUTH` is read and mirror it)
- Test: `tests/test_mcp/test_current_graph.py` (new), adjust `tests/test_mcp/test_auth.py`.

**Interfaces:**
- Consumes: `ApiKeyStore`, `ApiKeyRecord`, `choose_graph_id` (reuse from `src/api/graph_dep.py` — it raises `HTTPException`; wrap), registry.
- Produces: `class RegistryTokenVerifier(TokenVerifier)` with `async verify_token(token) -> AccessToken | None` (claims `{"owner", "graph_ids", "is_admin"}`); `async current_graph() -> GraphContext` (raises `fastmcp.exceptions.ToolError` on refusal).

- [ ] **Step 1: Write the failing test** — `tests/test_mcp/test_current_graph.py`:

```python
import pytest
from fastmcp.exceptions import ToolError

import src.mcp._shared as sh
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.context import default_graph_context, new_graph_context


class _Tok:
    def __init__(self, claims):
        self.claims = claims


class _Reg:
    async def get(self, gid):
        return default_graph_context() if gid == "default" else new_graph_context(gid)


async def test_verifier_maps_key_record_to_claims(monkeypatch):
    class _Store:
        async def lookup(self, k):
            return ApiKeyRecord("acme", ("acme",), False) if k == "good" else None
    monkeypatch.setattr(sh, "get_api_key_store", lambda: _Store())
    v = sh.RegistryTokenVerifier()
    tok = await v.verify_token("good")
    assert tok.claims == {"owner": "acme", "graph_ids": ["acme"], "is_admin": False}
    assert await v.verify_token("bad") is None


async def test_current_graph_http_uses_header(monkeypatch):
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Reg())
    monkeypatch.setattr(sh, "get_access_token", lambda: _Tok({"owner": "a", "graph_ids": ["acme", "acme_hr"], "is_admin": False}))
    monkeypatch.setattr(sh, "get_http_headers", lambda **kw: {"x-graph": "acme_hr"})
    assert (await sh.current_graph()).id == "acme_hr"


async def test_current_graph_http_refuses_foreign_graph(monkeypatch):
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Reg())
    monkeypatch.setattr(sh, "get_access_token", lambda: _Tok({"owner": "a", "graph_ids": ["acme"], "is_admin": False}))
    monkeypatch.setattr(sh, "get_http_headers", lambda **kw: {"x-graph": "other"})
    with pytest.raises(ToolError):
        await sh.current_graph()


async def test_current_graph_http_multi_graph_needs_header(monkeypatch):
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Reg())
    monkeypatch.setattr(sh, "get_access_token", lambda: _Tok({"owner": "a", "graph_ids": ["acme", "b"], "is_admin": False}))
    monkeypatch.setattr(sh, "get_http_headers", lambda **kw: {})
    with pytest.raises(ToolError):
        await sh.current_graph()


async def test_current_graph_stdio_uses_configured_graph(monkeypatch):
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Reg())
    monkeypatch.setattr(sh, "get_access_token", lambda: None)
    monkeypatch.setattr(sh, "get_http_headers", lambda **kw: {})
    monkeypatch.setattr(sh, "_configured_mcp_graph", lambda: "default")
    assert (await sh.current_graph()).id == "default"
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** in `src/mcp/_shared.py`:

```python
from fastapi import HTTPException
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token, get_http_headers

from src.api.graph_dep import choose_graph_id
from src.tenancy.api_keys import ApiKeyRecord, get_api_key_store
from src.tenancy.context import GraphContext
from src.tenancy.registry import GraphNotFound, GraphNotReady, get_graph_registry


class RegistryTokenVerifier(TokenVerifier):
    """Bearer token = API key; claims carry the key's graphs (R-A4)."""

    async def verify_token(self, token: str) -> AccessToken | None:
        rec = await get_api_key_store().lookup(token)
        if rec is None:
            return None
        return AccessToken(
            token=token, client_id=rec.owner, scopes=[],
            claims={"owner": rec.owner, "graph_ids": list(rec.graph_ids), "is_admin": rec.is_admin},
        )


def _configured_mcp_graph() -> str:
    return settings.mcp_graph  # adjust to the settings object that owns KB_MCP_* (see Files)


async def current_graph() -> GraphContext:
    tok = get_access_token()
    headers = get_http_headers(include={"x-graph"})
    if tok is None:
        gid = _configured_mcp_graph()
    else:
        c = tok.claims
        key = ApiKeyRecord(owner=c["owner"], graph_ids=tuple(c["graph_ids"]), is_admin=bool(c["is_admin"]))
        try:
            gid = choose_graph_id(key, headers.get("x-graph"))
        except HTTPException as exc:
            raise ToolError(str(exc.detail)) from None
    try:
        return await get_graph_registry().get(gid)
    except (GraphNotFound, GraphNotReady) as exc:
        raise ToolError(str(exc)) from None
```

`build_sse_auth()` returns `RegistryTokenVerifier()` when auth is required (keep the existing warning path when neither DB keys nor env keys can exist — i.e. keep the `_auth_required()` gate; drop the "API_KEYS empty → no auth" branch only if the registry is always consulted — keep it as is to preserve today's behaviour for keyless dev setups). Check `AccessToken`'s required fields (`token`, `client_id`, `scopes`, possibly `expires_at`) in `fastmcp/server/auth/auth.py:54` + the SDK base and fill them. Every tool in the three servers: first line `graph = await current_graph()`, then pass `graph` to `_r/_g/_c/_gs` (Task 6) or `graph_id=graph.id` into workflow params (search server) or `StatsRepository(graph=graph)` (stats server); ids via `graph_scoped_id`.
- [ ] **Step 4: Run** new test + `tests/test_mcp`, SUITE.
- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "feat(mcp): registry-backed bearer auth; every tool call bound to the connection's graph"
```

### Task 11: Ingest queue, scheduler, background jobs, scripts

**Files:**
- Modify: `src/ingest_queue/publisher.py` (message_id includes graph for non-default), `src/ingest_queue/consumer.py` (id via `graph_scoped_id("ingest", params.graph_id, params.doc_id)` for start and attach), `src/workflow/ingest_submit.py`, `src/workflow/ingest_scheduler.py` (dedupe key `(graph_id, doc_id)` instead of `doc_id`), `src/workflow/monitor/**` and `src/workflow/wiki/**` (run for `default` only in Plan A: their workflow inputs carry `graph_id="default"`; wiki activities skip with a log line when `graph_id != "default"`), `scripts/setup_monitor_schedule.py`, `scripts/setup_wiki_schedule.py` (explicit `graph_id="default"` in the scheduled input), all remaining `scripts/*.py` that build storage (add `--graph` CLI option defaulting to `default`, resolved via `new_graph_context`/`default_graph_context`); every other remaining `transitional_default_graph()` in `src/` outside workflow/api/mcp — find with `grep -rn transitional_default_graph src` — e.g. `src/ingestion/run.py` (CLI ingest: add `--graph`), `src/storage/backfill.py` (take `graph` from its caller), `src/bot/**` (Telegram bot queries one graph: new setting `bot_graph: str = "default"` read from env `BOT_GRAPH` on the bot settings class, resolved through `get_graph_registry()`; spec §4).
- Test: `tests/test_ingest_queue/test_consumer_graph.py`, `tests/test_workflow/test_scheduler_graph_dedupe.py`.

**Interfaces:**
- Consumes: Task 7 fields/ids.
- Produces: scheduler admission keyed by `f"{graph_id}:{doc_id}"`.

- [ ] **Step 1: Write the failing tests:**

```python
# tests/test_ingest_queue/test_consumer_graph.py
from src.ingest_queue import consumer
from src.workflow.contracts import IngestParams


class _Client:
    def __init__(self):
        self.ids = []

    async def execute_workflow(self, fn, params, *, id, **kw):
        self.ids.append(id)


async def test_default_graph_keeps_legacy_workflow_id():
    c = _Client()
    await consumer._start_or_attach(c, IngestParams(doc_id="d1", path="s3://b/k"))
    assert c.ids == ["ingest-d1"]


async def test_other_graph_gets_scoped_workflow_id():
    c = _Client()
    await consumer._start_or_attach(c, IngestParams(doc_id="d1", path="s3://b/k", graph_id="acme"))
    assert c.ids == ["ingest-acme-d1"]
```

```python
# tests/test_workflow/test_scheduler_graph_dedupe.py
from src.workflow.ingest_scheduler import admission_key
from src.workflow.contracts import IngestParams


def test_same_doc_id_in_two_graphs_is_two_admissions():
    a = IngestParams(doc_id="d1", path="p", graph_id="acme")
    b = IngestParams(doc_id="d1", path="p")
    assert admission_key(a) != admission_key(b)
    assert admission_key(b) == "default:d1"
```

(Use the real required fields of `IngestParams`.)
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** `ingest_scheduler.py`: `def admission_key(p: IngestParams) -> str: return f"{p.graph_id}:{p.doc_id}"`; use it everywhere the scheduler keys `_params`/`_running`/dedupe by `doc_id`; child id via `graph_scoped_id("ingest", p.graph_id, p.doc_id)`. Consumer: both the start id and the attach `get_workflow_handle(...)` id use `graph_scoped_id`. Publisher: `message_id=admission_key(params)` only when `params.graph_id != "default"` (keep `doc_id` for default).
- [ ] **Step 4: Run** new tests + `tests/test_ingest_queue tests/test_workflow tests/test_scripts`, SUITE.
- [ ] **Step 5: Commit**

```bash
git add src scripts tests
git commit -m "feat(ingest): graph-aware queue ids and scheduler admission; default-only monitor/wiki; scripts take --graph"
```

### Task 12: Guards, docs, graphify

**Files:**
- Create: `tests/test_tenancy/test_guards.py`
- Modify: `docs/ARCHITECTURE.md` (new section "Графы и изоляция" describing GraphContext, registry, physical names, how graph_id flows), `docs/DEPLOYMENT.md` (setup_db now creates `public.graphs`/`public.api_keys`, registers `default`, migrates each ready graph schema; new env `KB_MCP_GRAPH`; header `X-Graph`), `docs/runbook/mcp.md` (X-Graph / KB_MCP_GRAPH)

- [ ] **Step 1: Write the guard test:**

```python
"""Plan A invariants: no transitional default left; physical names only via GraphContext."""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def _hits(pattern: str, allow: set[str]) -> list[str]:
    rx = re.compile(pattern)
    out = []
    for p in SRC.rglob("*.py"):
        rel = str(p.relative_to(ROOT))
        if rel in allow:
            continue
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if rx.search(line):
                out.append(f"{rel}:{i}")
    return out


def test_no_transitional_default_left():
    assert _hits(r"transitional_default_graph", {"src/tenancy/context.py"}) == []


def test_chunk_collection_setting_only_read_by_tenancy():
    assert _hits(r"settings\.milvus\.collection", {"src/tenancy/context.py"}) == []


def test_no_hardcoded_space_or_collection_names():
    assert _hits(r"SPACE_NAME|[\"']entity_er_vec[\"']|[\"']community_report_vec[\"']|USE `kb`", {"src/tenancy/context.py"}) == []


def test_graph_store_builders_require_a_graph():
    import inspect

    from src.graph.nebula_store import build_nebula_graph_store
    from src.graph.store import build_graph_store
    for fn in (build_graph_store, build_nebula_graph_store):
        assert list(inspect.signature(fn).parameters) == ["graph"]
```

- [ ] **Step 2: Run** → it must PASS if Tasks 3–11 are complete; any hit is unfinished work from an earlier task — fix it at the source (not by widening the allow-list), note it in the commit body.
- [ ] **Step 3: Docs.** Write the sections listed above describing current behaviour only (Plan B items — creating/deleting graphs, key admin — are described as "not yet available").
- [ ] **Step 4: Run** SUITE, `tests/test_no_neo4j.py`, `uv run --extra dev pytest -q -p no:cacheprovider tests/eval --co`, `uv run --extra dev python -m compileall -q src scripts`. Then `graphify update .`.
- [ ] **Step 5: Commit**

```bash
git add tests/test_tenancy/test_guards.py docs graphify-out
git commit -m "test(tenancy): guard Plan A invariants; docs for graph-scoped foundation"
```
