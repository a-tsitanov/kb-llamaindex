# Multi-Graph Lifecycle (Plan B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Graphs other than `default` can be explicitly created (`POST /admin/graphs`) and deleted (`DELETE /admin/graphs/{id}`) through Temporal workflows, safely isolated from `default`, with the Plan-A blockers closed.

**Architecture:** A registry repo writes `public.graphs` rows; `ProvisionGraphWorkflow` / `DeleteGraphWorkflow` (on the `graph_build` worker pool) create or tear down the Nebula space, three Milvus collections, the PG schema and MinIO prefix through idempotent activities. Isolation hardening: pg_trgm moves to an `extensions` schema so a graph's `search_path` no longer falls back to `public` (R-P5); per-graph caches are keyed by `id#generation` so a deleted-then-recreated graph never reuses stale handles.

**Tech Stack:** Python 3.12, FastAPI, Temporal (temporalio 1.27, pydantic data converter), psycopg 3 + psycopg_pool, nebula3-python, pymilvus, minio, pytest (asyncio auto mode).

**Spec:** `docs/superpowers/specs/2026-09-24-multi-graph-design.md` (§3 Graph lifecycle; amendments 2026-10-17 and 2026-10-18). Plan A: `docs/superpowers/plans/2026-09-26-multi-graph-foundation.md`.

## Global Constraints

- Graphs are created ONLY explicitly; an unknown `X-Graph` stays 404 everywhere (amendment 2026-10-18). No auto-provisioning anywhere.
- ~~Any valid API key may call any endpoint incl. `/admin/graphs*`; no per-key authorization (amendment 2026-10-17). Do not reintroduce `is_admin` / `graph_ids`.~~ **CANCELLED by `docs/superpowers/specs/2026-10-18-tenancy-authz-design.md`** (implemented 2026-10-18): a key now carries `tenant_id`, `scopes` and `graph_ids`, and every seam authorizes through `authz.guard`. `graph_ids` IS back (a key may be narrowed to its own graphs); `is_admin` is NOT — the `admin` scope replaces it. Do not "restore" this constraint: it is encoded in `tests/test_tenancy/test_guards.py` the other way round now.
- Slug: `^[a-z][a-z0-9_]{1,30}$` via `validate_graph_id`; `default` is reserved and can never be provisioned, dropped or deleted.
- New graph physical names come only from `new_graph_context(id, nebula_partition_num=n)`: space `g_<id>`, collections `g_<id>_chunks|_er_vec|_report_vec`, schema `g_<id>`, MinIO prefix `<id>/`.
- `default` keeps legacy names (`kb`, `kb_llamaindex`, `entity_er_vec`, `community_report_vec`, `public`, `""`) and byte-identical Temporal workflow ids.
- Never write the word "neo4j" in `src/`, `scripts/`, `pyproject.toml` (guard `tests/test_no_neo4j.py`).
- No `transitional_default_graph` outside `src/tenancy/context.py` (guard `tests/test_tenancy/test_guards.py`).
- Lifecycle workflow ids: `lifecycle-provision-<id>`, `lifecycle-delete-<id>` (must not start with `graph-`, which `graph_scoped_id("graph", …)` owns).
- Commits: local only, one per task, message ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Never push. Subagents do not commit — the controller commits after the task gate.
- Test runner: `uv run --extra dev pytest -q -p no:cacheprovider <paths>`. Full suite before each commit: `uv run --extra dev pytest -q -p no:cacheprovider -x tests` (baseline 2466 passed, 2 xfailed).
- Run `graphify update .` after code changes (repo rule).
- Live stack checks (Task 12 smoke) only after the user answers «да».

## Review Focus

1. **Missing per-graph table after a partial migration** — a request on graph `acme` whose schema lacks a table must error, never read/write `default`'s `public` table. Pinned in Task 1 (`test_non_default_search_path_has_no_public`) and Task 2 (`test_missing_graph_tables_reports_absent`).
2. **Delete then re-create the same id within one process lifetime** — the API/MCP/worker must not reuse the old Nebula session or retrievers. Pinned in Task 3 (`test_new_generation_gets_new_store_and_closes_old`).
3. **Second `POST /admin/graphs` for an id that is `ready` / `provisioning` / `deleting`** — 409, no second workflow; for `failed` — resume (202). Pinned in Task 4 (`test_create_or_resume_*`) and Task 8 (`test_post_existing_ready_is_409`).
4. **`DELETE` on `default`, wrong `confirm`, unknown id** — 409 / 400 / 404, nothing dropped; activities refuse `default` even if called directly. Pinned in Task 5 (`test_drop_refuses_default_*`) and Task 8 (`test_delete_guards`).
5. **Provision step fails all retries** — row ends `failed` with `status_error`, not stuck in `provisioning`. Pinned in Task 7 (`test_provision_failure_marks_failed`).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/storage/pg_schema.py` (new) | Per-graph PG DDL (moved from `scripts/setup_db.py`), `migrate_graph_schema`, `graph_tables`, `missing_graph_tables`, `drop_graph_schema` |
| `scripts/setup_db.py` | Global DDL, pg_trgm→`extensions`, registry bootstrap; re-exports graph DDL names |
| `src/storage/pg_scope.py` | `search_path` = `<schema>, extensions` |
| `src/tenancy/context.py` | `GraphContext.generation`, `cache_key` |
| `src/tenancy/cache.py` (new) | `evict_stale_generations` |
| `src/tenancy/registry.py` | read `generation` |
| `src/tenancy/graph_repo.py` (new) | Registry writes + any-status reads |
| `src/graph/nebula_schema.py` | `verify_space_schema`, `drop_space` |
| `src/graph/entity_vector_store_milvus.py`, `community_vector_store_milvus.py` | public `ensure_collection()` (raises) |
| `src/storage/minio.py` | `delete_prefix` |
| `src/workflow/graph_lifecycle/{__init__,contracts,activities,workflows}.py` (new) | Provision/Delete workflows + activities |
| `src/workflow/worker.py` | register lifecycle on `graph_build` pool |
| `src/api/routes/graphs_admin.py` (new), `src/api/main.py` | `/admin/graphs` CRUD |
| `src/mcp/_shared.py` | R-P6: registry auth regardless of env keys |
| `src/workflow/monitor/activities.py`, `src/workflow/activities/build_property_graph.py`, `src/mcp/tools_server.py` | entity watch for every graph |
| `scripts/tg_ingest.py` | `--graph` → `X-Graph` |
| `scripts/smoke_graph_isolation.py` (new) | live end-to-end isolation smoke |

Out of scope (Plan C / later, stated so reviewers don't flag them): `POST /admin/graphs/refresh-all` + cron switch (operators call community-build/materialize per graph with `X-Graph`); `/admin/api-keys` endpoints (keys stay env/SQL managed); removing the transitional `graph_id="default"` defaults in Temporal inputs (needs a drained queue at deploy); per-graph ingest fairness; staging-bucket graph prefix (staging blobs are per-run, deleted on finalize, and swept as orphans — a deleted graph leaves nothing durable there); openclaw agent's MCP `X-Graph` (ops config of the agent, not code here); monitor/alerts/wiki/Wikibase stay default-only.

---

### Task 1: R-P5 — pg_trgm in `extensions`, no `public` fallback

**Files:**
- Modify: `scripts/setup_db.py:129-131` (`_PG_TRGM_DDL`), `scripts/setup_db.py:660-671` (`setup_postgres`)
- Modify: `src/storage/pg_scope.py:20-21`
- Test: `tests/test_storage/test_pg_scope.py`, `tests/test_scripts/test_setup_db_registry.py`

**Interfaces:**
- Produces: `search_path_sql(graph)` renders `SET search_path TO "<schema>", extensions`. `_PG_TRGM_DDL` creates schema `extensions`, installs/moves pg_trgm there. `_set_database_search_path(cur)` sets the DB default to `"$user", public, extensions`.

- [ ] **Step 1: Write the failing tests**

Replace `test_search_path_sql_quotes_identifier` in `tests/test_storage/test_pg_scope.py`:

```python
def test_search_path_sql_quotes_identifier():
    s = pg_scope.search_path_sql(new_graph_context("acme")).as_string(None)
    assert s == 'SET search_path TO "g_acme", extensions'
    default_sql = pg_scope.search_path_sql(default_graph_context()).as_string(None)
    assert default_sql == 'SET search_path TO "public", extensions'


def test_non_default_search_path_has_no_public():
    # R-P5: a missing per-graph table must error, never resolve to the
    # default graph's table in `public`.
    s = pg_scope.search_path_sql(new_graph_context("acme")).as_string(None)
    assert "public" not in s
```

Append to `tests/test_scripts/test_setup_db_registry.py`:

```python
def test_pg_trgm_lives_in_extensions_schema():
    ddl = setup_db._PG_TRGM_DDL
    assert "CREATE SCHEMA IF NOT EXISTS extensions" in ddl
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA extensions" in ddl
    assert "ALTER EXTENSION pg_trgm SET SCHEMA extensions" in ddl


def test_set_database_search_path_includes_extensions():
    cur = _Cur()
    setup_db._set_database_search_path(cur)
    (stmt, _), = cur.sql
    assert "ALTER DATABASE" in stmt and "extensions" in stmt and "current_database()" in stmt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_storage/test_pg_scope.py tests/test_scripts/test_setup_db_registry.py`
Expected: FAIL (`'SET search_path TO "g_acme", public'` mismatch; `AttributeError: _set_database_search_path`).

- [ ] **Step 3: Implement**

`src/storage/pg_scope.py`:

```python
def search_path_sql(graph: GraphContext) -> sql.Composed:
    # `extensions` (pg_trgm) instead of `public`: a graph schema missing a
    # table must fail loudly, not fall through to `default`'s public table
    # (R-P5).  Global tables are always addressed as `public.<t>`.
    return sql.SQL("SET search_path TO {}, extensions").format(sql.Identifier(graph.pg_schema))
```

Update the module docstring sentence "each graph's tables live in its own schema" to add: "pg_trgm lives in `extensions`, the only other schema on the path".

`scripts/setup_db.py` — replace `_PG_TRGM_DDL`:

```python
# pg_trgm lives in its own `extensions` schema so a graph's search_path
# (`<schema>, extensions`) never includes `public` (R-P5).  Existing
# deployments created it in `public`; move it (indexes keep working — they
# reference the opclass by OID).
_PG_TRGM_DDL = """
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA extensions;
DO $$
BEGIN
    IF (SELECT n.nspname FROM pg_extension e
        JOIN pg_namespace n ON n.oid = e.extnamespace
        WHERE e.extname = 'pg_trgm') <> 'extensions' THEN
        ALTER EXTENSION pg_trgm SET SCHEMA extensions;
    END IF;
END $$;
"""


def _set_database_search_path(cur) -> None:
    """Default path for connections that never pin a graph (bot, registry,
    RESET after a graph checkout): keep `public`, add `extensions` so
    trigram functions still resolve."""
    cur.execute(
        "DO $$ BEGIN EXECUTE format("
        "'ALTER DATABASE %I SET search_path TO \"$user\", public, extensions', "
        "current_database()); END $$;"
    )
```

In `setup_postgres`, after the `for stmt in GLOBAL_DDL:` loop add `_set_database_search_path(cur)`. Update the comment above `GLOBAL_DDL` ("pg_trgm is global … through the trailing `public`") to: "pg_trgm lives in `extensions`; GRAPH_DDL trigram indexes find `gin_trgm_ops` through the `extensions` entry of every graph's search_path."

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_storage tests/test_scripts`
Expected: PASS.

- [ ] **Step 5: Full suite + commit**

```bash
uv run --extra dev pytest -q -p no:cacheprovider -x tests
git add scripts/setup_db.py src/storage/pg_scope.py tests/test_storage/test_pg_scope.py tests/test_scripts/test_setup_db_registry.py
git commit -m "fix(tenancy): R-P5 — pg_trgm in extensions schema, graph search_path without public fallback

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Per-graph DDL in `src/storage/pg_schema.py` + table readiness check

**Files:**
- Create: `src/storage/pg_schema.py`
- Modify: `scripts/setup_db.py` (remove moved constants, import them back)
- Test: `tests/test_storage/test_pg_schema.py`

**Interfaces:**
- Produces:
  - `GRAPH_DDL: list[str]` (same contents/order as today)
  - `migrate_graph_schema(cur, graph: GraphContext) -> None` (unchanged behaviour)
  - `graph_tables() -> list[str]` — every table name created by `GRAPH_DDL`
  - `missing_graph_tables(cur, graph: GraphContext) -> list[str]`
  - `drop_graph_schema(cur, graph: GraphContext) -> None` — refuses `default` / `public`
- `scripts.setup_db` keeps attribute access to every moved name (tests use `setup_db._DOCUMENTS_DDL`).

- [ ] **Step 1: Write the failing tests**

`tests/test_storage/test_pg_schema.py`:

```python
import pytest

from src.storage import pg_schema
from src.tenancy.context import default_graph_context, new_graph_context


class _Cur:
    def __init__(self, existing=()):
        self.sql, self._existing = [], list(existing)

    def execute(self, q, params=None):
        self.sql.append((q.as_string(None) if hasattr(q, "as_string") else str(q), params))

    def fetchall(self):
        return [(t,) for t in self._existing]


def test_graph_tables_cover_core_tables():
    tables = pg_schema.graph_tables()
    for t in ("documents", "ingest_metrics", "entity", "er_verdict", "watch", "entity_alias"):
        assert t in tables
    assert "graphs" not in tables and "api_keys" not in tables
    assert len(tables) == len(set(tables))


def test_missing_graph_tables_reports_absent():
    all_tables = pg_schema.graph_tables()
    cur = _Cur(existing=[t for t in all_tables if t != "entity"])
    assert pg_schema.missing_graph_tables(cur, new_graph_context("acme")) == ["entity"]
    stmt, params = cur.sql[-1]
    assert "information_schema.tables" in stmt and params == ("g_acme",)


def test_missing_graph_tables_empty_when_complete():
    cur = _Cur(existing=pg_schema.graph_tables())
    assert pg_schema.missing_graph_tables(cur, new_graph_context("acme")) == []


def test_migrate_creates_schema_then_runs_graph_ddl():
    cur = _Cur()
    pg_schema.migrate_graph_schema(cur, new_graph_context("acme"))
    stmts = [s for s, _ in cur.sql]
    assert stmts[0] == 'CREATE SCHEMA IF NOT EXISTS "g_acme"'
    assert stmts[1] == 'SET search_path TO "g_acme", extensions'
    assert stmts[-1] == "RESET search_path"
    assert len(stmts) == len(pg_schema.GRAPH_DDL) + 3


def test_drop_graph_schema_cascades():
    cur = _Cur()
    pg_schema.drop_graph_schema(cur, new_graph_context("acme"))
    assert cur.sql == [('DROP SCHEMA IF EXISTS "g_acme" CASCADE', None)]


def test_drop_refuses_default_schema():
    with pytest.raises(ValueError):
        pg_schema.drop_graph_schema(_Cur(), default_graph_context())


def test_setup_db_reexports_moved_names():
    from scripts import setup_db

    assert setup_db.GRAPH_DDL is pg_schema.GRAPH_DDL
    assert setup_db._DOCUMENTS_DDL is pg_schema._DOCUMENTS_DDL
    assert setup_db.migrate_graph_schema is pg_schema.migrate_graph_schema
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_storage/test_pg_schema.py`
Expected: FAIL `ModuleNotFoundError: src.storage.pg_schema`.

- [ ] **Step 3: Implement**

Create `src/storage/pg_schema.py`. Move **verbatim** from `scripts/setup_db.py` (cut, do not copy): `_DOCUMENTS_DDL`, `_BACKFILL_SOURCE_CHANNEL_SQL`, `_INGEST_METRICS_DDL`, `_FACT_SUPERSEDE_DDL`, `_sql_in_list`, `_STAT_INDICATOR_DDL`, `_STAT_INDICATOR_CONSTRAINTS_DDL`, `_STAT_OBSERVATION_DDL`, `_ER_VERDICT_DDL`, `_ENTITY_DDL`, `_ENTITY_INDEXES_DDL`, `_WATCH_DDL`, `_WATCH_INDEXES_DDL`, `_ENTITY_RESOLUTION_DDL`, `_STAT_INDEXES_DDL`, `GRAPH_DDL`, `migrate_graph_schema` (with their comments). Module header and new helpers:

```python
"""Per-graph Postgres schema: the DDL every graph gets in its own schema
(``public`` for `default`), plus readiness and teardown helpers used by
``setup_db`` and graph provisioning."""

from __future__ import annotations

import re

from psycopg import sql

from src.stats.align import GRANULARITIES, VALUE_KINDS
from src.tenancy.context import GraphContext

# ... moved constants, _sql_in_list, GRAPH_DDL, migrate_graph_schema ...

_CREATE_TABLE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+([a-z_][a-z0-9_]*)", re.IGNORECASE)


def graph_tables() -> list[str]:
    """Every table GRAPH_DDL creates, in DDL order, without duplicates."""
    seen: list[str] = []
    for stmt in GRAPH_DDL:
        for name in _CREATE_TABLE.findall(stmt):
            if name not in seen:
                seen.append(name)
    return seen


def missing_graph_tables(cur, graph: GraphContext) -> list[str]:
    """Tables of GRAPH_DDL absent from ``graph``'s schema (empty = complete).
    Provisioning sets a graph `ready` only when this is empty."""
    cur.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
        (graph.pg_schema,),
    )
    present = {r[0] for r in cur.fetchall()}
    return [t for t in graph_tables() if t not in present]


def drop_graph_schema(cur, graph: GraphContext) -> None:
    """``DROP SCHEMA … CASCADE`` for a non-default graph.  Refuses `default`
    and anything not named ``g_<id>`` — this must never touch `public`."""
    if graph.is_default or graph.pg_schema != f"g_{graph.id}":
        raise ValueError(f"refusing to drop schema {graph.pg_schema!r} of graph {graph.id!r}")
    cur.execute(
        sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(graph.pg_schema)),
    )
```

In the moved `migrate_graph_schema`, keep the local `from src.storage.pg_scope import search_path_sql` import. In `scripts/setup_db.py` add after the existing imports:

```python
from src.storage.pg_schema import (  # noqa: F401 — re-exported for tests/ops
    _BACKFILL_SOURCE_CHANNEL_SQL,
    _DOCUMENTS_DDL,
    _ENTITY_DDL,
    _ENTITY_INDEXES_DDL,
    _ENTITY_RESOLUTION_DDL,
    _ER_VERDICT_DDL,
    _FACT_SUPERSEDE_DDL,
    _INGEST_METRICS_DDL,
    _STAT_INDEXES_DDL,
    _STAT_INDICATOR_CONSTRAINTS_DDL,
    _STAT_INDICATOR_DDL,
    _STAT_OBSERVATION_DDL,
    _WATCH_DDL,
    _WATCH_INDEXES_DDL,
    GRAPH_DDL,
    migrate_graph_schema,
)
```

Remove `from src.stats.align import …` from setup_db if nothing else there uses it (ruff F401 will tell).

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_storage/test_pg_schema.py tests/test_scripts && uv run --extra dev ruff check src/storage/pg_schema.py scripts/setup_db.py`
Expected: PASS, ruff clean. If `test_migrate_creates_schema_then_runs_graph_ddl` count is off, GRAPH_DDL was not moved intact — fix the move, not the test.

- [ ] **Step 5: Full suite + commit**

```bash
uv run --extra dev pytest -q -p no:cacheprovider -x tests
git add src/storage/pg_schema.py scripts/setup_db.py tests/test_storage/test_pg_schema.py
git commit -m "refactor(tenancy): per-graph DDL in src/storage/pg_schema with table readiness + guarded drop

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Graph generation + generation-keyed caches

**Files:**
- Modify: `src/tenancy/context.py` (`GraphContext`), `src/tenancy/registry.py` (`_COLS`, `_context_from_row`)
- Create: `src/tenancy/cache.py`
- Modify: `scripts/setup_db.py` (`_GRAPHS_DDL`, `_ready_graphs` SELECT)
- Modify caches: `src/graph/nebula_store.py:460-478`, `src/workflow/_search_deps.py:58-70`, `src/mcp/tools_server.py:93-144`, `src/api/routes/graph_admin.py:32-41`, `src/api/routes/entities.py:30-45`
- Test: `tests/test_tenancy/test_cache.py`, `tests/test_tenancy/test_registry.py`, `tests/test_graph/test_nebula_store_generation.py`

**Interfaces:**
- Produces:
  - `GraphContext.generation: int = 0` (last field), `GraphContext.cache_key -> str` = `f"{id}#{generation}"`
  - `evict_stale_generations(cache: dict[str, V], graph: GraphContext) -> list[V]`
  - `public.graphs.generation BIGINT NOT NULL DEFAULT 0`
- Every per-graph cache is keyed by `graph.cache_key` and evicts stale generations of the same id on a miss.

- [ ] **Step 1: Write the failing tests**

`tests/test_tenancy/test_cache.py`:

```python
from dataclasses import replace

from src.tenancy.cache import evict_stale_generations
from src.tenancy.context import default_graph_context, new_graph_context


def test_cache_key_includes_generation():
    g = replace(new_graph_context("acme"), generation=7)
    assert g.cache_key == "acme#7"
    assert default_graph_context().cache_key == "default#0"


def test_evict_drops_only_older_generations_of_same_id():
    old = replace(new_graph_context("acme"), generation=1)
    new = replace(new_graph_context("acme"), generation=2)
    other = new_graph_context("acme_x")
    cache = {old.cache_key: "o", new.cache_key: "n", other.cache_key: "x"}
    assert evict_stale_generations(cache, new) == ["o"]
    assert cache == {new.cache_key: "n", other.cache_key: "x"}
```

Append to `tests/test_tenancy/test_registry.py`:

```python
async def test_generation_read_from_row():
    row = _row("acme") | {"generation": 42}
    reg = GraphRegistry(loader=_Loader({"acme": row}))
    assert (await reg.get("acme")).generation == 42


def test_registry_selects_generation():
    from src.tenancy import registry

    assert "generation" in registry._COLS
```

`tests/test_graph/test_nebula_store_generation.py`:

```python
from dataclasses import replace

from src.graph import nebula_store
from src.tenancy.context import new_graph_context


class _Sess:
    released = 0

    def execute(self, stmt):
        raise AssertionError("not used")

    def release(self):
        _Sess.released += 1


def test_new_generation_gets_new_store_and_closes_old(monkeypatch):
    nebula_store.reset_nebula_stores_for_tests()
    monkeypatch.setattr(nebula_store, "_shared_pool", lambda: object())
    monkeypatch.setattr(nebula_store, "_acquire_session", lambda pool, u, p: _Sess())
    monkeypatch.setattr(nebula_store, "ensure_schema", lambda sess, graph: None)
    g1 = replace(new_graph_context("acme"), generation=1)
    g2 = replace(new_graph_context("acme"), generation=2)
    s1 = nebula_store.build_nebula_graph_store(g1)
    assert nebula_store.build_nebula_graph_store(g1) is s1
    s2 = nebula_store.build_nebula_graph_store(g2)
    assert s2 is not s1 and s2.graph.generation == 2
    assert _Sess.released == 1
    assert list(nebula_store._stores) == ["acme#2"]
    nebula_store.reset_nebula_stores_for_tests()
```

If `ensure_schema` is imported into `nebula_store` under another name, patch that name (check `grep -n "ensure_schema" src/graph/nebula_store.py`).

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_tenancy tests/test_graph/test_nebula_store_generation.py`
Expected: FAIL (`ModuleNotFoundError: src.tenancy.cache`, `TypeError: unexpected keyword 'generation'`).

- [ ] **Step 3: Implement**

`src/tenancy/context.py` — add last field and property to `GraphContext`:

```python
    minio_prefix: str
    # Bumped each time a graph id is (re)created, so per-process caches
    # never hand a re-created graph the dropped one's sessions/handles.
    generation: int = 0

    @property
    def is_default(self) -> bool:
        return self.id == DEFAULT_GRAPH_ID

    @property
    def cache_key(self) -> str:
        return f"{self.id}#{self.generation}"
```

`src/tenancy/cache.py`:

```python
"""Per-graph cache keys that survive a graph id being deleted and re-created."""

from __future__ import annotations

from typing import TypeVar

from src.tenancy.context import GraphContext

V = TypeVar("V")


def evict_stale_generations(cache: dict[str, V], graph: GraphContext) -> list[V]:
    """Remove entries of older generations of ``graph.id`` (keys
    ``"<id>#<gen>"``) and return them so the caller can close resources."""
    prefix = f"{graph.id}#"
    stale = [k for k in cache if k.startswith(prefix) and k != graph.cache_key]
    return [cache.pop(k) for k in stale]
```

`src/tenancy/registry.py`: append `, generation` to `_COLS`; in `_context_from_row` add `generation=int(row.get("generation") or 0),`.

`scripts/setup_db.py` `_GRAPHS_DDL`: add column line `generation             BIGINT NOT NULL DEFAULT 0,` after `max_inflight`, and after the `CREATE TABLE` statement inside the same string add:

```sql
ALTER TABLE public.graphs ADD COLUMN IF NOT EXISTS generation BIGINT NOT NULL DEFAULT 0;
```

In `_ready_graphs` add `generation` to the SELECT column list (after `pg_schema`).

Rekey caches (each: lookup and insert by `graph.cache_key`; on miss, evict stale generations first):

`src/graph/nebula_store.py` `build_nebula_graph_store`:

```python
    key = graph.cache_key
    store = _stores.get(key)
    if store is not None:
        return store
    with _lock:
        store = _stores.get(key)
        if store is None:
            from src.tenancy.cache import evict_stale_generations

            for stale in evict_stale_generations(_stores, graph):
                stale.close()
            pool = _shared_pool()
            # ... unchanged session factory ...
            store = NebulaGraphStore(_new_session(), reconnect=_new_session, graph=graph)
            _stores[key] = store
    return store
```

`src/workflow/_search_deps.py` `_slot`: use `graph.cache_key`; before creating a slot call `evict_stale_generations(_per_graph, graph)` (import at top from `src.tenancy.cache`). Update the comment "keyed by ``graph.id``" → "keyed by ``graph.cache_key``".

`src/mcp/tools_server.py` `_init`: replace the three `graph.id` uses with `graph.cache_key`; inside the lock, before building, call `evict_stale_generations(_deps_by_graph, graph)`.

`src/api/routes/graph_admin.py` `_store` and `src/api/routes/entities.py` `_retriever`: same pattern (`cache_key`, evict on miss); update the "keyed by ``graph.id``" comments.

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_tenancy tests/test_graph tests/test_mcp tests/test_api tests/test_workflow`
Expected: PASS. Tests that assert `_per_graph["acme"]` / `_deps_by_graph["default"]` must change to the `cache_key` (`"acme#0"`, `"default#0"`) — update them, they are asserting the key format.

- [ ] **Step 5: Full suite + commit**

```bash
uv run --extra dev pytest -q -p no:cacheprovider -x tests
git add -A src/tenancy src/graph/nebula_store.py src/workflow/_search_deps.py src/mcp/tools_server.py src/api/routes/graph_admin.py src/api/routes/entities.py scripts/setup_db.py tests
git commit -m "feat(tenancy): graph generation; per-graph caches keyed by id#generation, stale evicted

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Registry write repo (`src/tenancy/graph_repo.py`)

**Files:**
- Create: `src/tenancy/graph_repo.py`
- Test: `tests/test_tenancy/test_graph_repo.py`

**Interfaces:**
- Consumes: `new_graph_context`, `_context_from_row`, `GraphNotFound`.
- Produces (all async, module-level, take optional `conn_factory` for tests — an async-context-manager factory yielding a psycopg-like connection):
  - `ROW_COLS: str`
  - `@dataclass(frozen=True) class CreateOutcome: kind: Literal["created", "resumed", "conflict"]; status: str`
  - `create_or_resume(graph_id: str, owner: str, partition_num: int, *, conn_factory=None) -> CreateOutcome`
  - `get_row(graph_id, *, conn_factory=None) -> dict | None`
  - `list_rows(*, conn_factory=None) -> list[dict]`
  - `patch_row(graph_id, *, owner: str | None, max_inflight: int | None, conn_factory=None) -> dict | None`
  - `set_status(graph_id, status: str, error: str = "", *, conn_factory=None) -> None`
  - `mark_deleting(graph_id, *, conn_factory=None) -> str | None` — returns previous status, `None` if no row
  - `delete_row(graph_id, *, conn_factory=None) -> None`
  - `load_context_any_status(graph_id, *, conn_factory=None) -> GraphContext` (raises `GraphNotFound`)
  - `list_ready_contexts(*, conn_factory=None) -> list[GraphContext]`

- [ ] **Step 1: Write the failing tests**

`tests/test_tenancy/test_graph_repo.py`:

```python
from contextlib import asynccontextmanager

import pytest

from src.tenancy import graph_repo
from src.tenancy.context import new_graph_context
from src.tenancy.registry import GraphNotFound


class _Cur:
    def __init__(self, results):
        self.results, self.sql = list(results), []

    async def execute(self, q, params=None):
        self.sql.append((str(q), params))

    async def fetchone(self):
        return self.results.pop(0) if self.results else None

    async def fetchall(self):
        return self.results.pop(0) if self.results else []


class _Conn:
    def __init__(self, cur):
        self.cur, self.commits = cur, 0

    def cursor(self, row_factory=None):
        cur = self.cur

        @asynccontextmanager
        async def cm():
            yield cur
        return cm()

    async def commit(self):
        self.commits += 1


def _factory(results):
    cur = _Cur(results)
    conn = _Conn(cur)

    @asynccontextmanager
    async def f():
        yield conn
    return f, cur, conn


def _row(gid, status="ready", generation=5):
    c = new_graph_context(gid)
    return {"id": gid, "owner": "o", "status": status, "status_error": "",
            "nebula_space": c.nebula_space, "nebula_partition_num": 10,
            "chunks_collection": c.chunks_collection, "er_vec_collection": c.er_vec_collection,
            "report_vec_collection": c.report_vec_collection, "pg_schema": c.pg_schema,
            "max_inflight": None, "generation": generation,
            "created_at": None, "updated_at": None}


async def test_create_or_resume_inserts_new_row():
    f, cur, conn = _factory([{"id": "acme"}])
    out = await graph_repo.create_or_resume("acme", "team", 12, conn_factory=f)
    assert out == graph_repo.CreateOutcome("created", "provisioning")
    stmt, params = cur.sql[0]
    assert "INSERT INTO public.graphs" in stmt and "ON CONFLICT (id) DO NOTHING" in stmt
    assert "clock_timestamp()" in stmt
    assert params[:4] == ("acme", "team", "g_acme", 12)
    assert conn.commits == 1


async def test_create_or_resume_resumes_failed():
    f, cur, _ = _factory([None, {"id": "acme"}])
    out = await graph_repo.create_or_resume("acme", "team", 10, conn_factory=f)
    assert out == graph_repo.CreateOutcome("resumed", "provisioning")
    assert "status = 'failed'" in cur.sql[1][0]


@pytest.mark.parametrize("status", ["ready", "provisioning", "deleting"])
async def test_create_or_resume_conflicts(status):
    f, _, _ = _factory([None, None, {"status": status}])
    out = await graph_repo.create_or_resume("acme", "team", 10, conn_factory=f)
    assert out == graph_repo.CreateOutcome("conflict", status)


async def test_create_rejects_default_and_bad_slug():
    from src.tenancy.context import InvalidGraphId

    for gid in ("default", "Bad"):
        with pytest.raises(InvalidGraphId):
            await graph_repo.create_or_resume(gid, "o", 10, conn_factory=_factory([])[0])


async def test_load_context_any_status_ignores_status():
    f, _, _ = _factory([_row("acme", status="provisioning", generation=9)])
    g = await graph_repo.load_context_any_status("acme", conn_factory=f)
    assert g.id == "acme" and g.generation == 9


async def test_load_context_any_status_missing():
    f, _, _ = _factory([None])
    with pytest.raises(GraphNotFound):
        await graph_repo.load_context_any_status("acme", conn_factory=f)


async def test_mark_deleting_returns_previous_status():
    f, cur, _ = _factory([{"prev": "ready"}])
    assert await graph_repo.mark_deleting("acme", conn_factory=f) == "ready"
    assert "status = 'deleting'" in cur.sql[0][0]


async def test_list_ready_contexts():
    f, cur, _ = _factory([[_row("acme"), _row("beta")]])
    gs = await graph_repo.list_ready_contexts(conn_factory=f)
    assert [g.id for g in gs] == ["acme", "beta"]
    assert "status = 'ready'" in cur.sql[0][0]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_tenancy/test_graph_repo.py`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/tenancy/graph_repo.py`:

```python
"""Writes to the graph registry (``public.graphs``) and status-agnostic reads
for the lifecycle workflows.  Request-path reads go through the cached
:class:`~src.tenancy.registry.GraphRegistry` instead."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

from psycopg.rows import dict_row

from src.tenancy.context import DEFAULT_GRAPH_ID, GraphContext, new_graph_context
from src.tenancy.registry import GraphNotFound, _context_from_row

ROW_COLS = (
    "id, owner, status, status_error, nebula_space, nebula_partition_num, "
    "chunks_collection, er_vec_collection, report_vec_collection, pg_schema, "
    "max_inflight, generation, created_at, updated_at"
)

ConnFactory = Callable[[], AbstractAsyncContextManager[Any]]


@asynccontextmanager
async def _pool_conn():
    from src.storage.pg_pool import get_pg_pool

    pool = await get_pg_pool()
    async with pool.connection(timeout=5) as conn:
        yield conn


@dataclass(frozen=True)
class CreateOutcome:
    kind: Literal["created", "resumed", "conflict"]
    status: str


async def create_or_resume(
    graph_id: str, owner: str, partition_num: int, *, conn_factory: ConnFactory | None = None,
) -> CreateOutcome:
    """Insert a `provisioning` row; a `failed` row is reset to
    `provisioning` (resume); any other existing row is a conflict."""
    g = new_graph_context(graph_id, nebula_partition_num=partition_num)  # validates, rejects default
    async with (conn_factory or _pool_conn)() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "INSERT INTO public.graphs (id, owner, status, nebula_space, nebula_partition_num, "
                "chunks_collection, er_vec_collection, report_vec_collection, pg_schema, generation) "
                "VALUES (%s, %s, 'provisioning', %s, %s, %s, %s, %s, %s, "
                "(extract(epoch from clock_timestamp()) * 1000000)::bigint) "
                "ON CONFLICT (id) DO NOTHING RETURNING id",
                (g.id, owner, g.nebula_space, g.nebula_partition_num, g.chunks_collection,
                 g.er_vec_collection, g.report_vec_collection, g.pg_schema),
            )
            if await cur.fetchone() is not None:
                outcome = CreateOutcome("created", "provisioning")
            else:
                await cur.execute(
                    "UPDATE public.graphs SET status = 'provisioning', status_error = '', "
                    "updated_at = now() WHERE id = %s AND status = 'failed' RETURNING id",
                    (g.id,),
                )
                if await cur.fetchone() is not None:
                    outcome = CreateOutcome("resumed", "provisioning")
                else:
                    await cur.execute("SELECT status FROM public.graphs WHERE id = %s", (g.id,))
                    row = await cur.fetchone()
                    outcome = CreateOutcome("conflict", row["status"] if row else "unknown")
        await conn.commit()
    return outcome


async def get_row(graph_id: str, *, conn_factory: ConnFactory | None = None) -> dict | None:
    async with (conn_factory or _pool_conn)() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(f"SELECT {ROW_COLS} FROM public.graphs WHERE id = %s", (graph_id,))
            return await cur.fetchone()


async def list_rows(*, conn_factory: ConnFactory | None = None) -> list[dict]:
    async with (conn_factory or _pool_conn)() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(f"SELECT {ROW_COLS} FROM public.graphs ORDER BY id")
            return await cur.fetchall()


async def patch_row(
    graph_id: str, *, owner: str | None, max_inflight: int | None,
    conn_factory: ConnFactory | None = None,
) -> dict | None:
    async with (conn_factory or _pool_conn)() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "UPDATE public.graphs SET owner = COALESCE(%s, owner), "
                "max_inflight = COALESCE(%s, max_inflight), updated_at = now() "
                f"WHERE id = %s RETURNING {ROW_COLS}",
                (owner, max_inflight, graph_id),
            )
            row = await cur.fetchone()
        await conn.commit()
    return row


async def set_status(
    graph_id: str, status: str, error: str = "", *, conn_factory: ConnFactory | None = None,
) -> None:
    async with (conn_factory or _pool_conn)() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE public.graphs SET status = %s, status_error = %s, updated_at = now() "
                "WHERE id = %s",
                (status, error[:2000], graph_id),
            )
        await conn.commit()


async def mark_deleting(graph_id: str, *, conn_factory: ConnFactory | None = None) -> str | None:
    """Set `deleting`; return the previous status (None = no such graph)."""
    if graph_id == DEFAULT_GRAPH_ID:
        raise ValueError("the default graph is not deletable")
    async with (conn_factory or _pool_conn)() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "UPDATE public.graphs g SET status = 'deleting', updated_at = now() "
                "FROM (SELECT id, status AS prev FROM public.graphs WHERE id = %s FOR UPDATE) old "
                "WHERE g.id = old.id RETURNING old.prev AS prev",
                (graph_id,),
            )
            row = await cur.fetchone()
        await conn.commit()
    return row["prev"] if row else None


async def delete_row(graph_id: str, *, conn_factory: ConnFactory | None = None) -> None:
    async with (conn_factory or _pool_conn)() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM public.graphs WHERE id = %s", (graph_id,))
        await conn.commit()


async def load_context_any_status(
    graph_id: str, *, conn_factory: ConnFactory | None = None,
) -> GraphContext:
    row = await get_row(graph_id, conn_factory=conn_factory)
    if row is None:
        raise GraphNotFound(graph_id)
    return _context_from_row(row)


async def list_ready_contexts(*, conn_factory: ConnFactory | None = None) -> list[GraphContext]:
    async with (conn_factory or _pool_conn)() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"SELECT {ROW_COLS} FROM public.graphs WHERE status = 'ready' ORDER BY id",
            )
            return [_context_from_row(r) for r in await cur.fetchall()]
```

`mark_deleting` refuses `default` itself (defence in depth beyond the route guard); add this test:

```python
async def test_mark_deleting_refuses_default():
    with pytest.raises(ValueError):
        await graph_repo.mark_deleting("default", conn_factory=_factory([])[0])
```

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_tenancy`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev pytest -q -p no:cacheprovider -x tests
git add src/tenancy/graph_repo.py tests/test_tenancy/test_graph_repo.py
git commit -m "feat(tenancy): graph registry write repo (create/resume, status, delete, any-status reads)

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Storage provision/teardown primitives

**Files:**
- Modify: `src/graph/nebula_schema.py` (add `expected_tags`, `expected_edges`, `verify_space_schema`, `drop_space`)
- Modify: `src/graph/entity_vector_store_milvus.py`, `src/graph/community_vector_store_milvus.py` (public `ensure_collection`)
- Modify: `src/storage/minio.py` (`delete_prefix`)
- Test: `tests/test_graph/test_nebula_lifecycle.py`, `tests/test_graph/test_milvus_ensure_collection.py`, `tests/test_storage/test_minio.py`

**Interfaces:**
- Produces:
  - `nebula_schema.expected_tags() -> list[str]`, `expected_edges() -> list[str]` (parsed from `SCHEMA_DDL`)
  - `nebula_schema.verify_space_schema(session, graph) -> list[str]` — missing tag/edge names (`["<space unusable>"]` if `USE` fails)
  - `nebula_schema.drop_space(session, graph) -> None` — refuses default / non-`g_<id>`; raises `RuntimeError` on failure
  - `MilvusEntityVectorStore.ensure_collection()` / `MilvusCommunityReportVectorStore.ensure_collection()` — create if missing, **raise** on error (`_ensure` keeps fail-open by wrapping it)
  - `MinioStorage.delete_prefix(prefix: str) -> int` — removes all objects under prefix; refuses `""` and prefixes without trailing `/`

- [ ] **Step 1: Write the failing tests**

`tests/test_graph/test_nebula_lifecycle.py`:

```python
import pytest

from src.graph import nebula_schema
from src.tenancy.context import default_graph_context, new_graph_context


class _Resp:
    def __init__(self, ok=True, names=()):
        self.ok, self.names = ok, list(names)

    def is_succeeded(self):
        return self.ok

    def error_msg(self):
        return "boom"

    def keys(self):
        return ["Name"]

    def row_size(self):
        return len(self.names)

    def row_values(self, i):
        class _V:
            def __init__(self, v):
                self.v = v

            def cast(self):
                return self.v
        return [_V(self.names[i])]


class _Sess:
    def __init__(self, responses):
        self.responses, self.stmts = responses, []

    def execute(self, stmt):
        self.stmts.append(stmt)
        for prefix, resp in self.responses.items():
            if stmt.startswith(prefix):
                return resp
        return _Resp()


def test_expected_names_parsed_from_ddl():
    assert {"Entity", "Community"} <= set(nebula_schema.expected_tags())
    assert {"RELATED", "MENTIONS", "IN_COMMUNITY"} <= set(nebula_schema.expected_edges())


def test_verify_reports_missing():
    sess = _Sess({
        "SHOW TAGS": _Resp(names=[t for t in nebula_schema.expected_tags() if t != "Community"]),
        "SHOW EDGES": _Resp(names=nebula_schema.expected_edges()),
    })
    assert nebula_schema.verify_space_schema(sess, new_graph_context("acme")) == ["Community"]
    assert sess.stmts[0] == "USE `g_acme`;"


def test_verify_space_unusable():
    sess = _Sess({"USE": _Resp(ok=False)})
    assert nebula_schema.verify_space_schema(sess, new_graph_context("acme")) == ["<space unusable>"]


def test_drop_space_statement():
    sess = _Sess({})
    nebula_schema.drop_space(sess, new_graph_context("acme"))
    assert sess.stmts == ["DROP SPACE IF EXISTS `g_acme`;"]


def test_drop_refuses_default_space():
    with pytest.raises(ValueError):
        nebula_schema.drop_space(_Sess({}), default_graph_context())


def test_drop_space_failure_raises():
    with pytest.raises(RuntimeError):
        nebula_schema.drop_space(_Sess({"DROP SPACE": _Resp(ok=False)}), new_graph_context("acme"))
```

`tests/test_graph/test_milvus_ensure_collection.py`:

```python
import pytest

from src.graph.community_vector_store_milvus import MilvusCommunityReportVectorStore
from src.graph.entity_vector_store_milvus import MilvusEntityVectorStore


class _Client:
    def __init__(self, exists=False, fail=False):
        self.exists, self.fail, self.created = exists, fail, []

    def has_collection(self, name):
        if self.fail:
            raise ConnectionError("milvus down")
        return self.exists

    def create_schema(self, **kw):
        class _S:
            def add_field(self, *a, **k):
                pass
        return _S()

    def prepare_index_params(self):
        class _I:
            def add_index(self, **k):
                pass
        return _I()

    def create_collection(self, collection_name, **kw):
        self.created.append(collection_name)


@pytest.mark.parametrize("cls", [MilvusEntityVectorStore, MilvusCommunityReportVectorStore])
def test_ensure_collection_creates(cls):
    c = _Client()
    cls("g_acme_x", client=c).ensure_collection()
    assert c.created == ["g_acme_x"]


@pytest.mark.parametrize("cls", [MilvusEntityVectorStore, MilvusCommunityReportVectorStore])
def test_ensure_collection_raises_but_private_ensure_fails_open(cls):
    with pytest.raises(ConnectionError):
        cls("g_acme_x", client=_Client(fail=True)).ensure_collection()
    cls("g_acme_x", client=_Client(fail=True))._ensure()  # still fail-open
```

Append to `tests/test_storage/test_minio.py` (reuse the file's existing fake-client style if there is one; otherwise this standalone fake):

```python
def test_delete_prefix_removes_all_under_prefix():
    from types import SimpleNamespace

    from src.storage.minio import MinioStorage

    removed = []

    class _C:
        def list_objects(self, bucket, prefix, recursive):
            assert recursive and prefix == "acme/"
            return [SimpleNamespace(object_name="acme/a"), SimpleNamespace(object_name="acme/b/c")]

        def remove_object(self, bucket, name):
            removed.append(name)

    s = MinioStorage.__new__(MinioStorage)
    s._client, s._bucket = _C(), "kb-uploads"
    assert s.delete_prefix("acme/") == 2
    assert removed == ["acme/a", "acme/b/c"]


def test_delete_prefix_refuses_root():
    import pytest

    from src.storage.minio import MinioStorage

    s = MinioStorage.__new__(MinioStorage)
    for bad in ("", "acme"):
        with pytest.raises(ValueError):
            s.delete_prefix(bad)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_graph/test_nebula_lifecycle.py tests/test_graph/test_milvus_ensure_collection.py tests/test_storage/test_minio.py`
Expected: FAIL (missing functions/methods).

- [ ] **Step 3: Implement**

`src/graph/nebula_schema.py` (append; `re` import at top):

```python
_TAG_RE = re.compile(r"CREATE TAG IF NOT EXISTS `(\w+)`")
_EDGE_RE = re.compile(r"CREATE EDGE IF NOT EXISTS `(\w+)`")


def expected_tags() -> list[str]:
    return [m for s in SCHEMA_DDL for m in _TAG_RE.findall(s)]


def expected_edges() -> list[str]:
    return [m for s in SCHEMA_DDL for m in _EDGE_RE.findall(s)]


def _names(resp: Any) -> set[str]:
    cols = resp.keys()
    idx = cols.index("Name")
    return {resp.row_values(i)[idx].cast() for i in range(resp.row_size())}


def verify_space_schema(session: Any, graph: Any) -> list[str]:
    """Strict post-provision check (``ensure_schema`` is fail-open): the
    missing tag/edge names, or ``["<space unusable>"]`` if ``USE`` fails."""
    if not session.execute(f"USE `{graph.nebula_space}`;").is_succeeded():
        return ["<space unusable>"]
    tags = session.execute("SHOW TAGS;")
    edges = session.execute("SHOW EDGES;")
    if not (tags.is_succeeded() and edges.is_succeeded()):
        return ["<space unusable>"]
    have = _names(tags) | _names(edges)
    return [n for n in [*expected_tags(), *expected_edges()] if n not in have]


def drop_space(session: Any, graph: Any) -> None:
    """``DROP SPACE`` for a non-default graph; raises on failure."""
    if graph.is_default or graph.nebula_space != f"g_{graph.id}":
        raise ValueError(f"refusing to drop space {graph.nebula_space!r} of graph {graph.id!r}")
    resp = session.execute(f"DROP SPACE IF EXISTS `{graph.nebula_space}`;")
    if not resp.is_succeeded():
        raise RuntimeError(f"DROP SPACE {graph.nebula_space} failed: {resp.error_msg()}")
```

Milvus stores — split `_ensure` in both classes (example for entity store; same shape for community store with its own fields/log text):

```python
    def ensure_collection(self) -> None:
        """Create the collection if missing.  Raises on any Milvus error
        (provisioning needs a hard signal); request paths use ``_ensure``."""
        if self._ensured:
            return
        if not self._client.has_collection(self._collection):
            ...  # the existing create_schema / prepare_index_params / create_collection body, unchanged
        self._ensured = True

    def _ensure(self) -> None:
        try:
            self.ensure_collection()
        except Exception as exc:
            logger.warning("ensure entity_er_vec collection failed: {e}", e=exc)
```

`src/storage/minio.py` — add to `MinioStorage`:

```python
    def delete_prefix(self, prefix: str) -> int:
        """Remove every object under ``prefix`` (a graph's ``<id>/``).
        Refuses the bucket root.  Returns the number removed."""
        if not prefix or not prefix.endswith("/"):
            raise ValueError(f"refusing to delete prefix {prefix!r}")
        n = 0
        for obj in self._client.list_objects(self._bucket, prefix=prefix, recursive=True):
            self._client.remove_object(self._bucket, obj.object_name)
            n += 1
        return n
```

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_graph tests/test_storage`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev pytest -q -p no:cacheprovider -x tests
git add src/graph/nebula_schema.py src/graph/entity_vector_store_milvus.py src/graph/community_vector_store_milvus.py src/storage/minio.py tests/test_graph tests/test_storage/test_minio.py
git commit -m "feat(tenancy): strict provision/teardown primitives for nebula, milvus, minio

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Lifecycle contracts + activities

**Files:**
- Create: `src/workflow/graph_lifecycle/__init__.py` (empty docstring module), `contracts.py`, `activities.py`
- Test: `tests/test_workflow/test_graph_lifecycle_activities.py`

**Interfaces:**
- Consumes: Task 2 (`migrate_graph_schema`, `missing_graph_tables`, `drop_graph_schema`), Task 4 (`graph_repo.*`), Task 5 primitives, `nebula_store._shared_pool/_acquire_session/_lock`, `build_vector_store`, `build_minio_storage`, `get_temporal_client`, `graph_scoped_id`.
- Produces (Temporal activity names = function names):
  - contracts: `GraphLifecycleIn(graph_id: str)`, `DeleteGraphIn(graph_id: str, registry_settle_s: int = 35, drain_grace_s: int = 60)`, `SetStatusIn(graph_id: str, status: str, error: str = "")`, `LifecycleResult(graph_id: str, status: str, error: str = "")`
  - activities: `provision_nebula(GraphLifecycleIn)`, `provision_milvus(GraphLifecycleIn)`, `provision_pg(GraphLifecycleIn)`, `set_graph_status(SetStatusIn)`, `terminate_graph_ingests(GraphLifecycleIn) -> int`, `drop_nebula(GraphLifecycleIn)`, `drop_milvus(GraphLifecycleIn)`, `drop_pg(GraphLifecycleIn)`, `purge_minio(GraphLifecycleIn) -> int`, `delete_graph_row(GraphLifecycleIn)`
  - `LIFECYCLE_ACTIVITIES: list` of all of the above
- Every activity loads the context with `graph_repo.load_context_any_status`; every one refuses `default` with `ApplicationError(type="DefaultGraphProtected", non_retryable=True)`; a missing row → `ApplicationError(type="GraphUnavailable", non_retryable=True)` except in drop/purge/delete steps, where a missing row means "already gone" → return without error.

- [ ] **Step 1: Write the failing tests**

`tests/test_workflow/test_graph_lifecycle_activities.py`:

```python
from dataclasses import replace

import pytest
from temporalio.exceptions import ApplicationError

from src.tenancy.context import new_graph_context
from src.tenancy.registry import GraphNotFound
from src.workflow.graph_lifecycle import activities as A
from src.workflow.graph_lifecycle.contracts import GraphLifecycleIn, SetStatusIn

ACME = replace(new_graph_context("acme"), generation=3)


@pytest.fixture
def repo(monkeypatch):
    calls = []

    async def load(gid, **kw):
        if gid == "gone":
            raise GraphNotFound(gid)
        return ACME

    async def set_status(gid, status, error="", **kw):
        calls.append(("status", gid, status, error))

    async def delete_row(gid, **kw):
        calls.append(("delete", gid))

    monkeypatch.setattr(A.graph_repo, "load_context_any_status", load)
    monkeypatch.setattr(A.graph_repo, "set_status", set_status)
    monkeypatch.setattr(A.graph_repo, "delete_row", delete_row)
    return calls


@pytest.mark.parametrize("fn", [A.provision_nebula, A.provision_milvus, A.provision_pg,
                                A.drop_nebula, A.drop_milvus, A.drop_pg, A.purge_minio,
                                A.terminate_graph_ingests, A.delete_graph_row])
async def test_drop_refuses_default_everywhere(fn, repo):
    with pytest.raises(ApplicationError) as ei:
        await fn(GraphLifecycleIn(graph_id="default"))
    assert ei.value.type == "DefaultGraphProtected" and ei.value.non_retryable


async def test_provision_unknown_graph_is_non_retryable(repo):
    with pytest.raises(ApplicationError) as ei:
        await A.provision_pg(GraphLifecycleIn(graph_id="gone"))
    assert ei.value.type == "GraphUnavailable" and ei.value.non_retryable


async def test_drop_on_missing_row_is_noop(repo):
    assert await A.drop_pg(GraphLifecycleIn(graph_id="gone")) is None


async def test_provision_pg_raises_when_tables_missing(repo, monkeypatch):
    monkeypatch.setattr(A, "_pg_provision_sync", lambda g: ["entity"])
    with pytest.raises(ApplicationError) as ei:
        await A.provision_pg(GraphLifecycleIn(graph_id="acme"))
    assert "entity" in str(ei.value) and not ei.value.non_retryable


async def test_provision_nebula_raises_when_schema_missing(repo, monkeypatch):
    monkeypatch.setattr(A, "_nebula_provision_sync", lambda g: ["Community"])
    with pytest.raises(ApplicationError):
        await A.provision_nebula(GraphLifecycleIn(graph_id="acme"))


async def test_provision_milvus_checks_all_three(repo, monkeypatch):
    seen = []
    monkeypatch.setattr(A, "_milvus_provision_sync", lambda g: seen.append(g.id) or [])
    await A.provision_milvus(GraphLifecycleIn(graph_id="acme"))
    assert seen == ["acme"]


async def test_set_status_invalidates_local_registry(repo, monkeypatch):
    invalidated = []

    class _Reg:
        def invalidate(self, gid=None):
            invalidated.append(gid)

    monkeypatch.setattr(A, "get_graph_registry", lambda: _Reg())
    await A.set_graph_status(SetStatusIn(graph_id="acme", status="ready"))
    assert repo == [("status", "acme", "ready", "")] and invalidated == ["acme"]


async def test_terminate_graph_ingests_targets_scoped_ids(repo, monkeypatch):
    monkeypatch.setattr(A, "_inflight_doc_ids", _async_return(["d1", "d2"]))
    terminated = []

    class _H:
        def __init__(self, wid):
            self.wid = wid

        async def terminate(self, reason=None):
            if self.wid.endswith("d2") and self.wid.startswith("graph-"):
                from temporalio.service import RPCError, RPCStatusCode
                raise RPCError("not found", RPCStatusCode.NOT_FOUND, b"")
            terminated.append(self.wid)

    class _Client:
        def get_workflow_handle(self, wid):
            return _H(wid)

    monkeypatch.setattr(A, "get_temporal_client", _async_return(_Client()))
    n = await A.terminate_graph_ingests(GraphLifecycleIn(graph_id="acme"))
    assert terminated == ["ingest-acme-d1", "graph-acme-d1", "ingest-acme-d2"]
    assert n == 3


def _async_return(value):
    async def f(*a, **k):
        return value
    return f
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_workflow/test_graph_lifecycle_activities.py`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/workflow/graph_lifecycle/contracts.py`:

```python
"""Temporal payloads for graph provisioning / deletion (ids only — the
physical names are always re-read from the registry row)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class GraphLifecycleIn(_Frozen):
    graph_id: str


class DeleteGraphIn(_Frozen):
    graph_id: str
    # > GraphRegistry TTL (30 s): every process sees `deleting` before teardown.
    registry_settle_s: int = 35
    # Let terminated workflows' in-flight activities finish before dropping.
    drain_grace_s: int = 60


class SetStatusIn(_Frozen):
    graph_id: str
    status: str
    error: str = ""


class LifecycleResult(_Frozen):
    graph_id: str
    status: str
    error: str = ""
```

`src/workflow/graph_lifecycle/activities.py`:

```python
"""Idempotent steps of graph provisioning / deletion.

Each step re-reads the registry row (any status) and refuses `default`.
Sync storage clients run in a thread; the step raises (retryable) when its
strict post-check fails, so the workflow can mark the graph `failed`."""

from __future__ import annotations

import asyncio

import psycopg
from loguru import logger
from temporalio import activity
from temporalio.exceptions import ApplicationError

from src.config import settings
from src.tenancy import graph_repo
from src.tenancy.context import DEFAULT_GRAPH_ID, GraphContext, graph_scoped_id
from src.tenancy.registry import GraphNotFound, get_graph_registry
from src.workflow.client import get_temporal_client
from src.workflow.graph_lifecycle.contracts import GraphLifecycleIn, SetStatusIn


def _protect(graph_id: str) -> None:
    if graph_id == DEFAULT_GRAPH_ID:
        raise ApplicationError(
            "the default graph cannot be provisioned or dropped",
            type="DefaultGraphProtected", non_retryable=True,
        )


async def _load(graph_id: str) -> GraphContext:
    _protect(graph_id)
    try:
        return await graph_repo.load_context_any_status(graph_id)
    except GraphNotFound as exc:
        raise ApplicationError(str(exc), type="GraphUnavailable", non_retryable=True) from exc


async def _load_or_none(graph_id: str) -> GraphContext | None:
    _protect(graph_id)
    try:
        return await graph_repo.load_context_any_status(graph_id)
    except GraphNotFound:
        return None


# ── sync bodies (patched in tests) ─────────────────────────────────────

def _nebula_session():
    from src.graph import nebula_store

    with nebula_store._lock:
        pool = nebula_store._shared_pool()
    cfg = settings.nebula
    return nebula_store._acquire_session(pool, cfg.user, cfg.password.get_secret_value())


def _nebula_provision_sync(graph: GraphContext) -> list[str]:
    from src.graph.nebula_schema import ensure_schema, verify_space_schema

    sess = _nebula_session()
    try:
        ensure_schema(sess, graph, use_attempts=60, use_delay_s=1.0)
        return verify_space_schema(sess, graph)
    finally:
        sess.release()


def _nebula_drop_sync(graph: GraphContext) -> None:
    from src.graph.nebula_schema import drop_space

    sess = _nebula_session()
    try:
        drop_space(sess, graph)
    finally:
        sess.release()


def _milvus_client():
    from pymilvus import MilvusClient

    return MilvusClient(uri=settings.milvus.uri, timeout=settings.milvus.timeout_s)


def _milvus_provision_sync(graph: GraphContext) -> list[str]:
    from src.graph.community_vector_store_milvus import MilvusCommunityReportVectorStore
    from src.graph.entity_vector_store_milvus import MilvusEntityVectorStore
    from src.retrieval.vector_index import build_vector_store

    build_vector_store(graph)  # MilvusVectorStore creates the chunks collection on open
    client = _milvus_client()
    try:
        MilvusEntityVectorStore(graph.er_vec_collection, client=client).ensure_collection()
        MilvusCommunityReportVectorStore(graph.report_vec_collection, client=client).ensure_collection()
        names = (graph.chunks_collection, graph.er_vec_collection, graph.report_vec_collection)
        return [n for n in names if not client.has_collection(n)]
    finally:
        client.close()


def _milvus_drop_sync(graph: GraphContext) -> None:
    client = _milvus_client()
    try:
        for name in (graph.chunks_collection, graph.er_vec_collection, graph.report_vec_collection):
            if not name.startswith(f"g_{graph.id}_"):
                raise ValueError(f"refusing to drop collection {name!r}")
            if client.has_collection(name):
                client.drop_collection(name)
    finally:
        client.close()


def _pg_connect():
    pg = settings.postgres
    return psycopg.connect(pg.dsn, connect_timeout=pg.connect_timeout_s, autocommit=True)


def _pg_provision_sync(graph: GraphContext) -> list[str]:
    from src.storage.pg_schema import migrate_graph_schema, missing_graph_tables

    with _pg_connect() as conn, conn.cursor() as cur:
        migrate_graph_schema(cur, graph)
        return missing_graph_tables(cur, graph)


def _pg_drop_sync(graph: GraphContext) -> None:
    from src.storage.pg_schema import drop_graph_schema

    with _pg_connect() as conn, conn.cursor() as cur:
        drop_graph_schema(cur, graph)


def _minio_purge_sync(graph: GraphContext) -> int:
    from src.storage.minio import build_minio_storage

    return build_minio_storage().delete_prefix(graph.minio_prefix)


async def _inflight_doc_ids(graph: GraphContext) -> list[str]:
    from src.storage.pg_scope import graph_connection

    async with graph_connection(graph, timeout=5) as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT id::text FROM documents WHERE status IN ('pending', 'processing')",
        )
        return [r[0] for r in await cur.fetchall()]


def _check(step: str, graph: GraphContext, missing: list[str]) -> None:
    if missing:
        raise ApplicationError(f"{step}: graph {graph.id!r} missing {missing}", type="ProvisionIncomplete")


# ── provisioning ──────────────────────────────────────────────────────

@activity.defn
async def provision_nebula(inp: GraphLifecycleIn) -> None:
    graph = await _load(inp.graph_id)
    _check("nebula", graph, await asyncio.to_thread(_nebula_provision_sync, graph))


@activity.defn
async def provision_milvus(inp: GraphLifecycleIn) -> None:
    graph = await _load(inp.graph_id)
    _check("milvus", graph, await asyncio.to_thread(_milvus_provision_sync, graph))


@activity.defn
async def provision_pg(inp: GraphLifecycleIn) -> None:
    graph = await _load(inp.graph_id)
    _check("postgres", graph, await asyncio.to_thread(_pg_provision_sync, graph))


@activity.defn
async def set_graph_status(inp: SetStatusIn) -> None:
    _protect(inp.graph_id)
    await graph_repo.set_status(inp.graph_id, inp.status, inp.error)
    get_graph_registry().invalidate(inp.graph_id)  # this process; others within the TTL


# ── deletion ──────────────────────────────────────────────────────────

@activity.defn
async def terminate_graph_ingests(inp: GraphLifecycleIn) -> int:
    """Terminate the ingest + graph-build workflows of the graph's
    pending/processing documents.  Queued-but-unstarted documents fail on
    their own: their first activity cannot resolve a `deleting` graph."""
    from temporalio.service import RPCError, RPCStatusCode

    graph = await _load_or_none(inp.graph_id)
    if graph is None:
        return 0
    client = await get_temporal_client()
    n = 0
    for doc_id in await _inflight_doc_ids(graph):
        for prefix in ("ingest", "graph"):
            wid = graph_scoped_id(prefix, graph.id, doc_id)
            try:
                await client.get_workflow_handle(wid).terminate(reason=f"graph {graph.id} deleted")
                n += 1
            except RPCError as exc:
                if exc.status != RPCStatusCode.NOT_FOUND:
                    raise
        activity.heartbeat(n)
    logger.info("graph delete: terminated {n} workflow(s)  graph={g}", n=n, g=graph.id)
    return n


@activity.defn
async def drop_nebula(inp: GraphLifecycleIn) -> None:
    graph = await _load_or_none(inp.graph_id)
    if graph is not None:
        await asyncio.to_thread(_nebula_drop_sync, graph)


@activity.defn
async def drop_milvus(inp: GraphLifecycleIn) -> None:
    graph = await _load_or_none(inp.graph_id)
    if graph is not None:
        await asyncio.to_thread(_milvus_drop_sync, graph)


@activity.defn
async def drop_pg(inp: GraphLifecycleIn) -> None:
    graph = await _load_or_none(inp.graph_id)
    if graph is not None:
        await asyncio.to_thread(_pg_drop_sync, graph)


@activity.defn
async def purge_minio(inp: GraphLifecycleIn) -> int:
    graph = await _load_or_none(inp.graph_id)
    if graph is None:
        return 0
    return await asyncio.to_thread(_minio_purge_sync, graph)


@activity.defn
async def delete_graph_row(inp: GraphLifecycleIn) -> None:
    _protect(inp.graph_id)
    await graph_repo.delete_row(inp.graph_id)
    get_graph_registry().invalidate(inp.graph_id)


LIFECYCLE_ACTIVITIES = [
    provision_nebula, provision_milvus, provision_pg, set_graph_status,
    terminate_graph_ingests, drop_nebula, drop_milvus, drop_pg, purge_minio, delete_graph_row,
]
```

Check `ensure_schema`'s import name/signature in `nebula_schema` (`ensure_schema(session, graph, *, use_attempts, use_delay_s)` — confirmed). If `RPCError`'s constructor differs in temporalio 1.27, adjust the test's construction (`RPCError(message, status, raw_grpc_status)`), not the activity.

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_workflow/test_graph_lifecycle_activities.py tests/test_tenancy/test_guards.py tests/test_no_neo4j.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev pytest -q -p no:cacheprovider -x tests
git add src/workflow/graph_lifecycle tests/test_workflow/test_graph_lifecycle_activities.py
git commit -m "feat(tenancy): graph lifecycle activities (provision/verify/teardown), default protected

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: `ProvisionGraphWorkflow` + `DeleteGraphWorkflow` + worker registration

**Files:**
- Create: `src/workflow/graph_lifecycle/workflows.py`
- Modify: `src/workflow/worker.py` (`workflows_for_group["graph_build"]`, `graph_build` Worker activities)
- Test: `tests/test_workflow/test_graph_lifecycle_workflows.py`

**Interfaces:**
- Consumes: Task 6 contracts and activity names.
- Produces: `ProvisionGraphWorkflow.run(GraphLifecycleIn) -> LifecycleResult` (`status` = `ready` | `failed`); `DeleteGraphWorkflow.run(DeleteGraphIn) -> LifecycleResult` (`status` = `deleted` | `failed`); `provision_workflow_id(gid) = f"lifecycle-provision-{gid}"`, `delete_workflow_id(gid) = f"lifecycle-delete-{gid}"`. Both on `settings.temporal.graph_build_task_queue`.

- [ ] **Step 1: Write the failing tests**

`tests/test_workflow/test_graph_lifecycle_workflows.py`:

```python
import uuid

import pytest
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from src.workflow.graph_lifecycle.contracts import DeleteGraphIn, GraphLifecycleIn
from src.workflow.graph_lifecycle.workflows import (
    DeleteGraphWorkflow,
    ProvisionGraphWorkflow,
    delete_workflow_id,
    provision_workflow_id,
)

LOG: list = []


def _stub(name, fail=False):
    @activity.defn(name=name)
    async def _a(inp):
        # untyped param: the pydantic converter hands the stub a plain dict
        LOG.append((name, inp.get("status") if isinstance(inp, dict) else None))
        if fail:
            raise ApplicationError(f"{name} broke", type="ProvisionIncomplete", non_retryable=True)
        return 0
    return _a


def _acts(fail_step=None):
    names = ["provision_nebula", "provision_milvus", "provision_pg", "set_graph_status",
             "terminate_graph_ingests", "drop_nebula", "drop_milvus", "drop_pg",
             "purge_minio", "delete_graph_row"]
    return [_stub(n, fail=(n == fail_step)) for n in names]


async def _run(wf, arg, acts):
    try:
        env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"temporal test server unavailable: {exc}")
    async with env, Worker(env.client, task_queue="t-life", workflows=[wf], activities=acts,
                           workflow_runner=UnsandboxedWorkflowRunner()):
        return await env.client.execute_workflow(
            wf.run, arg, id=f"t-{uuid.uuid4().hex}", task_queue="t-life",
        )


def test_workflow_ids():
    assert provision_workflow_id("acme") == "lifecycle-provision-acme"
    assert delete_workflow_id("acme") == "lifecycle-delete-acme"


async def test_provision_happy_path_marks_ready():
    LOG.clear()
    out = await _run(ProvisionGraphWorkflow, GraphLifecycleIn(graph_id="acme"), _acts())
    assert out.status == "ready"
    assert [n for n, _ in LOG] == ["provision_nebula", "provision_milvus", "provision_pg",
                                   "set_graph_status"]
    assert LOG[-1] == ("set_graph_status", "ready")


async def test_provision_failure_marks_failed():
    LOG.clear()
    out = await _run(ProvisionGraphWorkflow, GraphLifecycleIn(graph_id="acme"),
                     _acts(fail_step="provision_milvus"))
    assert out.status == "failed" and "provision_milvus broke" in out.error
    assert LOG[-1] == ("set_graph_status", "failed")
    assert "provision_pg" not in [n for n, _ in LOG]


async def test_delete_order():
    LOG.clear()
    out = await _run(DeleteGraphWorkflow, DeleteGraphIn(graph_id="acme"), _acts())
    assert out.status == "deleted"
    assert [n for n, _ in LOG] == ["terminate_graph_ingests", "drop_nebula", "drop_milvus",
                                   "drop_pg", "purge_minio", "delete_graph_row"]


async def test_delete_failure_marks_failed_and_keeps_row():
    LOG.clear()
    out = await _run(DeleteGraphWorkflow, DeleteGraphIn(graph_id="acme"), _acts(fail_step="drop_pg"))
    assert out.status == "failed"
    assert ("set_graph_status", "failed") in LOG
    assert "delete_graph_row" not in [n for n, _ in LOG]


def test_registered_on_graph_build_pool():
    from src.workflow import worker
    from src.workflow.graph_lifecycle.activities import LIFECYCLE_ACTIVITIES

    wfs = worker.workflows_for_group("graph_build")
    assert ProvisionGraphWorkflow in wfs and DeleteGraphWorkflow in wfs
    assert all(a in worker.GRAPH_BUILD_POOL_ACTIVITIES for a in LIFECYCLE_ACTIVITIES)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_workflow/test_graph_lifecycle_workflows.py`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/workflow/graph_lifecycle/workflows.py`:

```python
"""Graph provisioning / deletion workflows (spec §3).

Provision: nebula space → milvus collections → PG schema → `ready`;
any step exhausting its retries → `failed` (+ error).  A repeated
`POST /admin/graphs` on a `failed` graph starts this again (steps are
idempotent).  Delete: wait for every process to see `deleting`, terminate
the graph's in-flight ingests, let their activities drain, drop storage,
delete the registry row; a failure leaves the row `failed` for a retry."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from src.workflow.graph_lifecycle.contracts import (
        DeleteGraphIn,
        GraphLifecycleIn,
        LifecycleResult,
        SetStatusIn,
    )

_RETRY = RetryPolicy(
    maximum_attempts=5, initial_interval=timedelta(seconds=2), maximum_interval=timedelta(seconds=30),
)
_STEP = timedelta(minutes=5)


def provision_workflow_id(graph_id: str) -> str:
    return f"lifecycle-provision-{graph_id}"


def delete_workflow_id(graph_id: str) -> str:
    return f"lifecycle-delete-{graph_id}"


async def _step(name: str, arg) -> None:
    await workflow.execute_activity(
        name, arg, start_to_close_timeout=_STEP, heartbeat_timeout=timedelta(minutes=2),
        retry_policy=_RETRY,
    )


def _cause(exc: ActivityError) -> str:
    return str(exc.cause or exc)


@workflow.defn
class ProvisionGraphWorkflow:
    @workflow.run
    async def run(self, inp: GraphLifecycleIn) -> LifecycleResult:
        try:
            for name in ("provision_nebula", "provision_milvus", "provision_pg"):
                await _step(name, inp)
        except ActivityError as exc:
            err = _cause(exc)
            await _step("set_graph_status", SetStatusIn(graph_id=inp.graph_id, status="failed", error=err))
            return LifecycleResult(graph_id=inp.graph_id, status="failed", error=err)
        await _step("set_graph_status", SetStatusIn(graph_id=inp.graph_id, status="ready"))
        return LifecycleResult(graph_id=inp.graph_id, status="ready")


@workflow.defn
class DeleteGraphWorkflow:
    @workflow.run
    async def run(self, inp: DeleteGraphIn) -> LifecycleResult:
        gid = GraphLifecycleIn(graph_id=inp.graph_id)
        await workflow.sleep(timedelta(seconds=inp.registry_settle_s))
        try:
            await _step("terminate_graph_ingests", gid)
            await workflow.sleep(timedelta(seconds=inp.drain_grace_s))
            for name in ("drop_nebula", "drop_milvus", "drop_pg", "purge_minio"):
                await _step(name, gid)
        except ActivityError as exc:
            err = _cause(exc)
            await _step("set_graph_status", SetStatusIn(graph_id=inp.graph_id, status="failed", error=err))
            return LifecycleResult(graph_id=inp.graph_id, status="failed", error=err)
        await _step("delete_graph_row", gid)
        return LifecycleResult(graph_id=inp.graph_id, status="deleted")
```

Note: a delete that ends `failed` leaves the row `failed`; `DELETE` again restarts it (Task 8), and `POST` would resume *provisioning* — acceptable: the operator chooses.

`src/workflow/worker.py`:

```python
from src.workflow.graph_lifecycle.activities import LIFECYCLE_ACTIVITIES
from src.workflow.graph_lifecycle.workflows import DeleteGraphWorkflow, ProvisionGraphWorkflow

# graph_build pool: offline community/analytics builds + graph lifecycle.
GRAPH_BUILD_POOL_ACTIVITIES = [*GRAPH_BUILD_ACTIVITIES, *LIFECYCLE_ACTIVITIES]
```

In `workflows_for_group`: `"graph_build": [CommunityBuildWorkflow, AnalyticsMaterializeWorkflow, ProvisionGraphWorkflow, DeleteGraphWorkflow],`. In the `graph_build` branch of `_build_worker`: `activities=GRAPH_BUILD_POOL_ACTIVITIES,`. Add a line to the module docstring: `* **graph_build** — … + graph provision/delete workflows.`

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_workflow`
Expected: PASS (time-skipping server skips gracefully if unavailable — if it skips, say so in the report).

- [ ] **Step 5: Commit**

```bash
uv run --extra dev pytest -q -p no:cacheprovider -x tests
git add src/workflow/graph_lifecycle/workflows.py src/workflow/worker.py tests/test_workflow/test_graph_lifecycle_workflows.py
git commit -m "feat(tenancy): ProvisionGraphWorkflow and DeleteGraphWorkflow on the graph_build pool

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: `/admin/graphs` API

**Files:**
- Create: `src/api/routes/graphs_admin.py`
- Modify: `src/api/main.py` (include router after `graph_admin.router`)
- Test: `tests/test_api/test_graphs_admin.py`

**Interfaces:**
- Consumes: `graph_repo` (Task 4), workflow classes + ids (Task 7), `require_api_key`, `get_temporal_client`.
- Produces:
  - `POST /admin/graphs` body `{"id": str, "owner": str, "nebula_partition_num": int = 10}` (1..1000) → 202 `{"id", "status": "provisioning", "workflow_id"}`; 400 invalid/reserved id; 409 `{"detail": "graph 'x' is <status>"}` if exists and not `failed`; 500 if the workflow cannot be started (row set `failed`).
  - `GET /admin/graphs` → `[row…]`; `GET /admin/graphs/{id}` → row | 404.
  - `PATCH /admin/graphs/{id}` body `{"owner"?: str, "max_inflight"?: int ≥ 1}` → row | 404.
  - `DELETE /admin/graphs/{id}?confirm=<id>` → 202 `{"id", "status": "deleting", "workflow_id"}`; 409 for `default` or `provisioning`; 400 if `confirm != id`; 404 unknown.
  - All endpoints: `Depends(require_api_key)` only (no `X-Graph`).

- [ ] **Step 1: Write the failing tests**

`tests/test_api/test_graphs_admin.py`:

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_api_key
from src.api.routes import graphs_admin
from src.tenancy import graph_repo
from src.tenancy.api_keys import ApiKeyRecord


class _Client:
    def __init__(self, fail=False):
        self.started, self.fail = [], fail

    async def start_workflow(self, run, arg, *, id, task_queue, **kw):
        if self.fail:
            raise RuntimeError("temporal down")
        self.started.append((id, arg.graph_id))

        class _H:
            pass
        h = _H()
        h.id = id
        return h


@pytest.fixture
def ctx(monkeypatch):
    state = {"client": _Client(), "outcome": graph_repo.CreateOutcome("created", "provisioning"),
             "row": None, "prev": "ready", "statuses": []}

    async def _client():
        return state["client"]

    async def create(gid, owner, n, **kw):
        if gid in ("default", "Bad"):
            from src.tenancy.context import InvalidGraphId
            raise InvalidGraphId(gid)
        return state["outcome"]

    async def get_row(gid, **kw):
        return state["row"]

    async def mark_deleting(gid, **kw):
        return state["prev"]

    async def set_status(gid, status, error="", **kw):
        state["statuses"].append((gid, status))

    monkeypatch.setattr(graphs_admin, "get_temporal_client", _client)
    monkeypatch.setattr(graphs_admin.graph_repo, "create_or_resume", create)
    monkeypatch.setattr(graphs_admin.graph_repo, "get_row", get_row)
    monkeypatch.setattr(graphs_admin.graph_repo, "mark_deleting", mark_deleting)
    monkeypatch.setattr(graphs_admin.graph_repo, "set_status", set_status)
    app = FastAPI()
    app.include_router(graphs_admin.router)
    app.dependency_overrides[require_api_key] = lambda: ApiKeyRecord(owner="t")
    state["http"] = TestClient(app)
    return state


def test_post_creates_and_starts_workflow(ctx):
    r = ctx["http"].post("/admin/graphs", json={"id": "acme", "owner": "team"})
    assert r.status_code == 202
    assert r.json() == {"id": "acme", "status": "provisioning",
                        "workflow_id": "lifecycle-provision-acme"}
    assert ctx["client"].started == [("lifecycle-provision-acme", "acme")]


def test_post_resume_failed_starts_again(ctx):
    ctx["outcome"] = graph_repo.CreateOutcome("resumed", "provisioning")
    assert ctx["http"].post("/admin/graphs", json={"id": "acme", "owner": "t"}).status_code == 202


@pytest.mark.parametrize("status", ["ready", "provisioning", "deleting"])
def test_post_existing_ready_is_409(ctx, status):
    ctx["outcome"] = graph_repo.CreateOutcome("conflict", status)
    r = ctx["http"].post("/admin/graphs", json={"id": "acme", "owner": "t"})
    assert r.status_code == 409 and status in r.json()["detail"]
    assert ctx["client"].started == []


@pytest.mark.parametrize("gid", ["default", "Bad"])
def test_post_invalid_id_400(ctx, gid):
    assert ctx["http"].post("/admin/graphs", json={"id": gid, "owner": "t"}).status_code == 400


def test_post_workflow_start_failure_marks_failed(ctx):
    ctx["client"] = _Client(fail=True)
    r = ctx["http"].post("/admin/graphs", json={"id": "acme", "owner": "t"})
    assert r.status_code == 500
    assert ctx["statuses"] == [("acme", "failed")]


def test_get_unknown_404(ctx):
    assert ctx["http"].get("/admin/graphs/acme").status_code == 404


def test_delete_guards(ctx):
    http = ctx["http"]
    assert http.delete("/admin/graphs/default?confirm=default").status_code == 409
    assert http.delete("/admin/graphs/acme?confirm=acmee").status_code == 400
    assert http.delete("/admin/graphs/acme").status_code == 422  # confirm required
    ctx["prev"] = None
    assert http.delete("/admin/graphs/acme?confirm=acme").status_code == 404
    assert ctx["client"].started == []


def test_delete_provisioning_is_409(ctx):
    ctx["row"] = {"id": "acme", "status": "provisioning"}
    r = ctx["http"].delete("/admin/graphs/acme?confirm=acme")
    assert r.status_code == 409


def test_delete_starts_workflow(ctx):
    ctx["row"] = {"id": "acme", "status": "ready"}
    r = ctx["http"].delete("/admin/graphs/acme?confirm=acme")
    assert r.status_code == 202
    assert r.json()["workflow_id"] == "lifecycle-delete-acme"
    assert ctx["client"].started == [("lifecycle-delete-acme", "acme")]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_api/test_graphs_admin.py`
Expected: FAIL `ImportError: graphs_admin`.

- [ ] **Step 3: Implement**

`src/api/routes/graphs_admin.py`:

```python
"""Graph lifecycle admin API (spec §3): explicit create / list / patch /
delete.  Graphs are never created implicitly (amendment 2026-10-18).  Any
valid API key may call these (amendment 2026-10-17)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from src.api.auth import require_api_key
from src.config import settings
from src.tenancy import graph_repo
from src.tenancy.context import DEFAULT_GRAPH_ID, InvalidGraphId
from src.workflow.client import get_temporal_client
from src.workflow.graph_lifecycle.contracts import DeleteGraphIn, GraphLifecycleIn
from src.workflow.graph_lifecycle.workflows import (
    DeleteGraphWorkflow,
    ProvisionGraphWorkflow,
    delete_workflow_id,
    provision_workflow_id,
)

router = APIRouter(prefix="/admin/graphs", tags=["admin"], dependencies=[Depends(require_api_key)])


class CreateGraphBody(BaseModel):
    id: str
    owner: str = Field(min_length=1)
    nebula_partition_num: int = Field(default=10, ge=1, le=1000)


class PatchGraphBody(BaseModel):
    owner: str | None = Field(default=None, min_length=1)
    max_inflight: int | None = Field(default=None, ge=1)


async def _start(run, arg, wid: str) -> str:
    client = await get_temporal_client()
    handle = await client.start_workflow(
        run, arg, id=wid, task_queue=settings.temporal.graph_build_task_queue,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    return handle.id


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_graph(body: CreateGraphBody) -> dict:
    try:
        outcome = await graph_repo.create_or_resume(body.id, body.owner, body.nebula_partition_num)
    except InvalidGraphId as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    if outcome.kind == "conflict":
        raise HTTPException(status.HTTP_409_CONFLICT, f"graph {body.id!r} is {outcome.status}")
    try:
        wid = await _start(ProvisionGraphWorkflow.run, GraphLifecycleIn(graph_id=body.id),
                           provision_workflow_id(body.id))
    except Exception as exc:
        await graph_repo.set_status(body.id, "failed", f"workflow start failed: {exc}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            f"provisioning failed to start: {exc}") from exc
    return {"id": body.id, "status": "provisioning", "workflow_id": wid}


@router.get("")
async def list_graphs() -> list[dict]:
    return await graph_repo.list_rows()


@router.get("/{graph_id}")
async def get_graph(graph_id: str) -> dict:
    row = await graph_repo.get_row(graph_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"graph {graph_id!r} not found")
    return row


@router.patch("/{graph_id}")
async def patch_graph(graph_id: str, body: PatchGraphBody) -> dict:
    row = await graph_repo.patch_row(graph_id, owner=body.owner, max_inflight=body.max_inflight)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"graph {graph_id!r} not found")
    return row


@router.delete("/{graph_id}", status_code=status.HTTP_202_ACCEPTED)
async def delete_graph(graph_id: str, confirm: str = Query(...)) -> dict:
    if graph_id == DEFAULT_GRAPH_ID:
        raise HTTPException(status.HTTP_409_CONFLICT, "the default graph cannot be deleted")
    if confirm != graph_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "confirm must equal the graph id")
    row = await graph_repo.get_row(graph_id)
    if row is not None and row["status"] == "provisioning":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"graph {graph_id!r} is provisioning; retry when ready or failed")
    if await graph_repo.mark_deleting(graph_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"graph {graph_id!r} not found")
    try:
        wid = await _start(DeleteGraphWorkflow.run, DeleteGraphIn(graph_id=graph_id),
                           delete_workflow_id(graph_id))
    except Exception as exc:
        await graph_repo.set_status(graph_id, "failed", f"delete start failed: {exc}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            f"delete failed to start: {exc}") from exc
    return {"id": graph_id, "status": "deleting", "workflow_id": wid}
```

`src/api/main.py`: import `graphs_admin` with the other routes and add `app.include_router(graphs_admin.router)` after `app.include_router(graph_admin.router)`.

If `test_get_unknown_404` hits `mark_deleting`'s stub instead of `get_row` — no; it calls GET. If the `DELETE` test with `row=None` and `prev=None` returns 404 — correct path.

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_api`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev pytest -q -p no:cacheprovider -x tests
git add src/api/routes/graphs_admin.py src/api/main.py tests/test_api/test_graphs_admin.py
git commit -m "feat(api): /admin/graphs — explicit graph create/list/patch/delete via lifecycle workflows

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: R-P6 — MCP HTTP auth uses the key registry, not the env list

**Files:**
- Modify: `src/mcp/_shared.py` (`assert_api_key_env_set`, `is_valid_key`, `build_sse_auth`)
- Test: `tests/test_mcp/test_auth.py`

**Interfaces:**
- Produces: `build_sse_auth()` → `RegistryTokenVerifier()` whenever `KB_MCP_REQUIRE_AUTH` is not disabled (DB keys suffice; env may be empty). `assert_api_key_env_set()` no longer exits on empty env (warns instead). `is_valid_key` removed if unused (grep shows no callers outside `_shared.py`).

- [ ] **Step 1: Update the tests**

In `tests/test_mcp/test_auth.py` replace `test_build_sse_auth_returns_none_when_no_keys` with:

```python
def test_build_sse_auth_uses_registry_even_without_env_keys(monkeypatch):
    # R-P6: DB-only key deployments must still get auth on HTTP transports.
    monkeypatch.setenv("KB_MCP_REQUIRE_AUTH", "true")
    monkeypatch.setattr(
        _shared, "settings",
        SimpleNamespace(api=SimpleNamespace(keys_list=[])),
    )
    assert isinstance(_shared.build_sse_auth(), _shared.RegistryTokenVerifier)


def test_startup_check_does_not_exit_without_env_keys(monkeypatch):
    monkeypatch.setenv("KB_MCP_REQUIRE_AUTH", "true")
    monkeypatch.setattr(
        _shared, "settings",
        SimpleNamespace(api=SimpleNamespace(keys_list=[])),
    )
    _shared.assert_api_key_env_set()  # must not raise SystemExit
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_mcp/test_auth.py`
Expected: FAIL (returns `None`; `SystemExit`).

- [ ] **Step 3: Implement**

`src/mcp/_shared.py`:

```python
def assert_api_key_env_set() -> None:
    """Startup notice.  Auth (when on) validates bearer tokens against the
    API-key registry (`public.api_keys` + legacy env keys), so an empty
    ``API_KEYS`` env is fine when keys live in the DB (R-P6)."""
    if not _auth_required():
        logger.warning(
            "MCP auth DISABLED via KB_MCP_REQUIRE_AUTH=false — "
            "anyone reaching this port can call tools",
        )
        return
    if not settings.api.keys_list:
        logger.info("MCP auth: API_KEYS env empty — relying on public.api_keys only")


def build_sse_auth() -> RegistryTokenVerifier | None:
    """FastMCP auth provider for HTTP transports: a ``RegistryTokenVerifier``
    unless ``KB_MCP_REQUIRE_AUTH`` is disabled.  Keys come from the registry
    (DB + legacy env), so an empty env no longer disables auth (R-P6).
    Evaluated once at import time; stdio is unaffected."""
    if not _auth_required():
        return None
    return RegistryTokenVerifier()
```

Delete `is_valid_key` (run `grep -rn "is_valid_key" src tests` first; if anything references it, keep it but make it `return provided and await`-free equivalent — expected: no references).

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_mcp`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev pytest -q -p no:cacheprovider -x tests
git add src/mcp/_shared.py tests/test_mcp/test_auth.py
git commit -m "fix(mcp): R-P6 — HTTP auth via key registry even when API_KEYS env is empty

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Entity watch for every graph

**Files:**
- Modify: `src/workflow/monitor/activities.py:266-280` (`sweep_watch`)
- Modify: `src/workflow/activities/build_property_graph.py:145-161` (journal gate)
- Modify: `src/mcp/tools_server.py:930-939` (`_watch_graph`)
- Test: `tests/test_workflow/test_sweep_watch_graphs.py`; update existing tests asserting the default-only refusal/skip.

**Interfaces:**
- Consumes: `graph_repo.list_ready_contexts()` (Task 4), `default_graph_context`.
- Produces: `sweep_watch()` sweeps `default` + every `ready` graph, summing `by_kind`; one graph's failure is logged and recorded in `error` (`"<gid>: <err>; …"`) without stopping the others. Journals are written for every graph. MCP watch tools accept any graph.

- [ ] **Step 1: Write the failing tests**

`tests/test_workflow/test_sweep_watch_graphs.py`:

```python
from contextlib import asynccontextmanager

from src.tenancy.context import default_graph_context, new_graph_context
from src.workflow.monitor import activities as M


async def test_sweep_watch_covers_all_ready_graphs(monkeypatch):
    seen = []

    async def ready(**kw):
        return [default_graph_context(), new_graph_context("acme"), new_graph_context("beta")]

    async def run(repo):
        seen.append(repo.graph.id)
        if repo.graph.id == "beta":
            raise RuntimeError("beta broke")
        return {"new_mention": 2}

    class _Repo:
        def __init__(self, *, graph):
            self.graph = graph

    @asynccontextmanager
    async def hb(*a, **k):
        yield

    monkeypatch.setattr(M.graph_repo, "list_ready_contexts", ready)
    monkeypatch.setattr(M, "run_watch_sweep", run)
    monkeypatch.setattr(M, "WatchRepository", _Repo)
    monkeypatch.setattr(M, "heartbeat_every", hb)
    out = await M.sweep_watch()
    assert seen == ["default", "acme", "beta"]
    assert out.events == 4 and out.by_kind == {"new_mention": 4}
    assert "beta: beta broke" in out.error


async def test_sweep_watch_includes_default_when_registry_down(monkeypatch):
    async def ready(**kw):
        raise ConnectionError("pg down")

    seen = []

    async def run(repo):
        seen.append(repo.graph.id)
        return {}

    class _Repo:
        def __init__(self, *, graph):
            self.graph = graph

    @asynccontextmanager
    async def hb(*a, **k):
        yield

    monkeypatch.setattr(M.graph_repo, "list_ready_contexts", ready)
    monkeypatch.setattr(M, "run_watch_sweep", run)
    monkeypatch.setattr(M, "WatchRepository", _Repo)
    monkeypatch.setattr(M, "heartbeat_every", hb)
    await M.sweep_watch()
    assert seen == ["default"]
```

`WatchRepository` must expose `.graph` — if it stores `_graph` only, the fake above is what's used, so no change needed in the real class.

Find the existing default-only tests and flip them:
`grep -rn "default-only\|only for the default graph\|journals skipped" tests` — update each to assert the non-default graph now works (watch tool accepts `acme`; `record_watch_journals` is called for `acme`).

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_workflow/test_sweep_watch_graphs.py`
Expected: FAIL (`AttributeError: graph_repo` / only default swept).

- [ ] **Step 3: Implement**

`src/workflow/monitor/activities.py` — replace `sweep_watch` (import `from src.tenancy import graph_repo` and `default_graph_context` at the top; drop the now-unused `DEFAULT_GRAPH_ID`/`resolve_graph_for_activity` imports if ruff flags them):

```python
async def _watch_graphs() -> list[GraphContext]:
    """`default` + every ready graph; `default` alone if the registry is down."""
    try:
        graphs = await graph_repo.list_ready_contexts()
    except Exception as exc:
        logger.warning("sweep_watch: registry unavailable ({e}); default only", e=exc)
        graphs = []
    if not any(g.is_default for g in graphs):
        graphs.insert(0, default_graph_context())
    return graphs


@activity.defn
async def sweep_watch() -> WatchSweepResult:
    """Entity-watch sweep over every ready graph: journals past their
    cursors -> watch_event rows for subscribed entities.  Fail-soft per
    graph: one graph's error never stops the others."""
    by_kind: dict[str, int] = {}
    errors: list[str] = []
    async with heartbeat_every(30.0, {"stage": "watch"}):
        for graph in await _watch_graphs():
            try:
                for kind, n in (await run_watch_sweep(WatchRepository(graph=graph))).items():
                    by_kind[kind] = by_kind.get(kind, 0) + n
            except Exception as exc:
                logger.warning("sweep_watch failed  graph={g}: {e}", g=graph.id, e=exc)
                errors.append(f"{graph.id}: {exc}")
    return WatchSweepResult(events=sum(by_kind.values()), by_kind=by_kind, error="; ".join(errors))
```

`src/workflow/activities/build_property_graph.py` — replace the `if graph.is_default: … else: logger.debug(...)` block with the unconditional call and fix the comment:

```python
        # Entity-watch journals: every entity of this document + the pairs
        # the write just created (every graph; the monitor sweeps them all).
        # Fail-open inside — never fails the build.
        ctx = merged.kg.parsed.ctx
        from src.storage.watch import WatchRepository

        await record_watch_journals(
            WatchRepository(graph=graph), entities, relations, created_pairs,
            doc_id=ctx.doc_id, doc_date_epoch=ctx.doc_date_epoch, backfill=ctx.backfill,
        )
```

`src/mcp/tools_server.py` — `_watch_graph` becomes:

```python
async def _watch_graph() -> GraphContext:
    """The tool's graph (any ready graph — the monitor sweeps all of them)."""
    return await current_graph()
```

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_workflow tests/test_mcp tests/test_storage/test_watch_repository.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev pytest -q -p no:cacheprovider -x tests
git add src/workflow/monitor/activities.py src/workflow/activities/build_property_graph.py src/mcp/tools_server.py tests
git commit -m "feat(watch): entity watch on every graph — per-graph journals, sweep over all ready graphs

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: `tg_ingest --graph`

**Files:**
- Modify: `scripts/tg_ingest.py` (`main` argparse + the three `httpx.AsyncClient(...)` constructions)
- Test: `tests/test_scripts/test_tg_ingest_graph.py`

**Interfaces:**
- Produces: `client_headers(graph: str | None) -> dict[str, str]` (module-level) — `{"X-Graph": graph}` or `{}`; `--graph` (default env `KB_GRAPH`, else none → server default). Every `httpx.AsyncClient` in `main` gets `headers=client_headers(args.graph)`, so `post_ingest` (and any other call) inherits `X-Graph`.

- [ ] **Step 1: Write the failing test**

`tests/test_scripts/test_tg_ingest_graph.py`:

```python
import pytest

from scripts import tg_ingest


def test_client_headers():
    assert tg_ingest.client_headers(None) == {}
    assert tg_ingest.client_headers("acme") == {"X-Graph": "acme"}


def test_client_headers_rejects_bad_slug():
    with pytest.raises(ValueError):
        tg_ingest.client_headers("Bad;Id")


async def test_post_ingest_inherits_client_graph_header():
    import httpx

    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(202, json={"job_id": "00000000-0000-0000-0000-000000000000"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                 headers=tg_ingest.client_headers("acme")) as http:
        ok = await tg_ingest.post_ingest(http, "http://x", "k", "f.txt", "t", "2026-10-18", None)
    assert ok and seen["x-graph"] == "acme" and seen["x-api-key"] == "k"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_scripts/test_tg_ingest_graph.py`
Expected: FAIL `AttributeError: client_headers`.

- [ ] **Step 3: Implement**

In `scripts/tg_ingest.py` add near `post_ingest`:

```python
def client_headers(graph: str | None) -> dict[str, str]:
    """Default headers for every KB call: ``X-Graph`` when a graph is set
    (absent → the server uses `default`)."""
    if not graph:
        return {}
    from src.tenancy.context import validate_graph_id

    return {"X-Graph": validate_graph_id(graph)}
```

In `main`: add

```python
    p.add_argument(
        "--graph", default=os.environ.get("KB_GRAPH") or None,
        help="target graph id (X-Graph); default: server's `default` graph",
    )
```

and change each of the three `httpx.AsyncClient(timeout=30.0)` to `httpx.AsyncClient(timeout=30.0, headers=client_headers(args.graph))`. Add `KB_GRAPH` to `docker-compose.tg-ingest.yml` environment as `KB_GRAPH: ${KB_GRAPH:-}` if that file lists env vars explicitly.

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_scripts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run --extra dev pytest -q -p no:cacheprovider -x tests
git add scripts/tg_ingest.py tests/test_scripts/test_tg_ingest_graph.py docker-compose.tg-ingest.yml
git commit -m "feat(tg_ingest): --graph / KB_GRAPH sends X-Graph on every KB call

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Live isolation smoke script + docs (live run gated on «да»)

**Files:**
- Create: `scripts/smoke_graph_isolation.py`
- Create: `docs/multi-graph-ops.md`
- Modify: `docs/superpowers/specs/2026-09-24-multi-graph-design.md` (append "Implementation status 2026-10-18")
- Test: `tests/test_scripts/test_smoke_graph_isolation.py` (pure helpers only)

**Interfaces:**
- Produces: `python -m scripts.smoke_graph_isolation --api-base URL --api-key KEY [--graph smoke_iso] [--timeout 900]` → exit 0 when all checks pass; prints one line per check. Helper `wait_for(fn, *, timeout_s, interval_s) -> T` (pure, tested).

- [ ] **Step 1: Write the failing test**

`tests/test_scripts/test_smoke_graph_isolation.py`:

```python
import pytest

from scripts import smoke_graph_isolation as S


async def test_wait_for_returns_first_truthy():
    calls = iter([None, None, {"status": "ready"}])

    async def probe():
        return next(calls)

    assert await S.wait_for(probe, timeout_s=5, interval_s=0) == {"status": "ready"}


async def test_wait_for_times_out():
    async def probe():
        return None

    with pytest.raises(TimeoutError):
        await S.wait_for(probe, timeout_s=0.05, interval_s=0.01)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_scripts/test_smoke_graph_isolation.py`
Expected: FAIL `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`scripts/smoke_graph_isolation.py`:

```python
"""Live smoke: create a graph, ingest into it, prove `default` cannot see it,
delete it.  Touches a real stack — run only with explicit approval.

    uv run python -m scripts.smoke_graph_isolation --api-base http://localhost:8000 --api-key K
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

T = TypeVar("T")


async def wait_for(
    probe: Callable[[], Awaitable[T | None]], *, timeout_s: float, interval_s: float = 3.0,
) -> T:
    deadline = time.monotonic() + timeout_s
    while True:
        value = await probe()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise TimeoutError("condition not met in time")
        await asyncio.sleep(interval_s)


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    if not ok:
        raise SystemExit(1)


async def run(api_base: str, api_key: str, gid: str, timeout_s: float) -> None:
    key = {"X-API-Key": api_key}
    in_g = {**key, "X-Graph": gid}
    token = f"smokeiso{uuid.uuid4().hex[:8]}"
    async with httpx.AsyncClient(base_url=api_base, timeout=60.0) as http:
        r = await http.post("/api/v1/ingest", headers=in_g,
                            files={"file": ("x.txt", b"x", "text/plain")},
                            data={"document_date": "2026-10-18"})
        _check("unknown graph ingest is 404 (no auto-create)", r.status_code == 404, str(r.status_code))

        r = await http.post("/admin/graphs", headers=key, json={"id": gid, "owner": "smoke"})
        _check("create accepted", r.status_code == 202, r.text)

        async def ready():
            row = (await http.get(f"/admin/graphs/{gid}", headers=key)).json()
            if row.get("status") == "failed":
                raise SystemExit(f"FAIL  provisioning failed: {row.get('status_error')}")
            return row if row.get("status") == "ready" else None
        await wait_for(ready, timeout_s=300)
        _check("graph ready", True)

        text = f"{token} Corporation signed a contract with {token} Holdings in Berlin.".encode()
        r = await http.post("/api/v1/ingest", headers=in_g,
                            files={"file": (f"{token}.txt", text, "text/plain")},
                            data={"document_date": "2026-10-18"})
        _check("ingest into new graph accepted", r.status_code == 202, r.text)
        job = r.json()["job_id"]

        async def done():
            j = (await http.get(f"/api/v1/ingest/{job}", headers=in_g)).json()
            if j.get("status") == "failed":
                raise SystemExit(f"FAIL  ingest failed: {j.get('error')}")
            return j if j.get("status") == "completed" else None
        await wait_for(done, timeout_s=timeout_s, interval_s=10)
        _check("ingest completed in new graph", True)

        r = await http.get(f"/api/v1/ingest/{job}", headers=key)
        _check("job invisible from default", r.status_code == 404, str(r.status_code))

        hits_g = (await http.get("/api/v1/entities", headers=in_g, params={"query": token})).json()
        hits_d = (await http.get("/api/v1/entities", headers=key, params={"query": token})).json()
        _check("entity found in new graph", bool(hits_g), str(hits_g)[:200])
        _check("entity absent from default", not hits_d, str(hits_d)[:200])

        r = await http.delete(f"/admin/graphs/{gid}", headers=key, params={"confirm": gid})
        _check("delete accepted", r.status_code == 202, r.text)

        async def gone():
            return (await http.get(f"/admin/graphs/{gid}", headers=key)).status_code == 404
        await wait_for(gone, timeout_s=600, interval_s=10)
        _check("graph deleted", True)

        r = await http.get(f"/api/v1/ingest/{job}", headers=in_g)
        _check("deleted graph is 404", r.status_code == 404, str(r.status_code))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--api-base", default="http://localhost:8000")
    p.add_argument("--api-key", required=True)
    p.add_argument("--graph", default="smoke_iso")
    p.add_argument("--timeout", type=float, default=900.0, help="ingest completion timeout, s")
    a = p.parse_args()
    asyncio.run(run(a.api_base, a.api_key, a.graph, a.timeout))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

If `/api/v1/entities` returns an object (not a list), adapt the two `bool(...)` checks to the actual field holding results — read `src/api/routes/entities.py:find_entities` return shape first.

`docs/multi-graph-ops.md` — operator notes, sections:
1. Create: `curl -X POST $API/admin/graphs -H "X-API-Key: $K" -H 'Content-Type: application/json' -d '{"id":"acme","owner":"team"}'`, poll `GET /admin/graphs/acme` until `ready`; `failed` → read `status_error`, fix, `POST` again (resumes).
2. Use: send `X-Graph: acme` (HTTP), MCP header `X-Graph` or `KB_MCP_GRAPH`, `tg_ingest --graph acme`, bot `BOT_GRAPH=acme`.
3. Delete: `curl -X DELETE "$API/admin/graphs/acme?confirm=acme" -H "X-API-Key: $K"`; takes ≥ ~2 min (registry settle 35 s + drain 60 s); in-flight ingests of that graph are terminated.
4. Security: any valid key can create/delete graphs (amendment 2026-10-17) — restrict `/admin/*` at the proxy if clients hold keys.
5. Deploy: run `setup_db` first (moves pg_trgm to `extensions`, adds `graphs.generation`, sets DB search_path); restart API, MCP and all worker pools (`graph_build` pool runs lifecycle).
6. Default-only features: wiki, Wikibase push, monitor alerts. Entity watch works on every graph.
7. Community/analytics refresh for a new graph: call `POST /api/v1/...community-build` and `/admin/graph/materialize` with `X-Graph: acme` (cron covers `default` only until `refresh-all`).

Append to the spec:

```markdown
## Implementation status 2026-10-18 (Plan B)

Implemented per `docs/superpowers/plans/2026-10-18-multi-graph-lifecycle.md`: §3 create/list/patch/delete
with ProvisionGraphWorkflow / DeleteGraphWorkflow (ids `lifecycle-provision-<id>` / `lifecycle-delete-<id>`
on the graph_build queue); R-P5 (pg_trgm in `extensions`, search_path `<schema>, extensions`, `ready` only
when every GRAPH_DDL table exists); per-graph caches keyed by `id#generation` (`graphs.generation`);
R-P6; entity watch on every graph. Delete does not purge staging blobs (per-run, orphan-swept).
Deferred: `refresh-all`, `/admin/api-keys`, removal of transitional `graph_id` defaults.
```

- [ ] **Step 4: Run tests + graphify**

Run: `uv run --extra dev pytest -q -p no:cacheprovider -x tests && graphify update .`
Expected: full suite PASS (≈ baseline + new tests, 2 xfailed).

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke_graph_isolation.py tests/test_scripts/test_smoke_graph_isolation.py docs/multi-graph-ops.md docs/superpowers/specs/2026-09-24-multi-graph-design.md graphify-out
git commit -m "docs(tenancy): graph lifecycle ops guide, live isolation smoke script, spec status

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Live smoke — ONLY after the user answers «да»**

Describe in one line to the user: "Живой smoke на локальном стеке agent_v2: setup_db, рестарт api/mcp/worker, создать граф smoke_iso, ingest 1 документ, проверить изоляцию, удалить граф. Ок?" Wait for «да». Then:

```bash
uv run python scripts/setup_db.py
# rebuild/restart api, mcp-*, worker per local_dev_run_gotchas
uv run python -m scripts.smoke_graph_isolation --api-base http://localhost:8000 --api-key "$KB_API_KEY"
```

Expected: every line `PASS`, exit 0. Also confirm after delete: `SHOW SPACES` has no `g_smoke_iso`; Milvus has no `g_smoke_iso_*`; `\dn` has no `g_smoke_iso`.
