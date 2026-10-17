# Multi-graph (per-client / per-topic isolation) — design

Date: 2026-09-24
Status: approved in brainstorming, pending spec review
Sub-project 1. Depends on sub-project 0 (`2026-09-24-remove-neo4j-design.md`):
NebulaGraph is the only graph backend.

## Goal

Several fully isolated knowledge graphs in one deployment, instead of the
single `kb` graph. Used to isolate clients from each other and, optionally,
topics within one client.

Success criterion: a document ingested into graph A is never visible,
through any path (HTTP search/analyze/entities/stats, MCP tools, analytics,
communities), to a caller bound to graph B. Deleting B does not affect A.

## Decisions (from brainstorming)

| # | Decision |
|---|----------|
| D1 | Flat model: a graph is standalone; a client is the graph's `owner`. An API key grants a list of graphs. No cross-graph search in v1. |
| D2 | Graphs are created/deleted dynamically via admin API, async provisioning (`provisioning → ready`). |
| D3 | Physical isolation per graph: own Nebula space, own Milvus collections, own Postgres schema (schema-per-graph via `search_path`). |
| D4 | The graph is bound to the connection (HTTP `X-Graph` header, MCP URL/header), never a tool/LLM-chosen parameter. |
| D5 | Ingest: one shared FIFO queue, `graph_id` in `IngestParams`. No per-graph fairness in v1. Both queue backends (Temporal scheduler and RabbitMQ) supported. |
| D6 | Wiki / Wikibase: only for the `default` graph; skipped for other graphs until those modules are removed. |
| D7 | Existing data becomes graph `default` under its current physical names; no data migration, no re-ingest. |

## 1. Registry and GraphContext

### Global tables (Postgres schema `public`)

```sql
CREATE TABLE IF NOT EXISTS graphs (
    id                     TEXT PRIMARY KEY,         -- slug, see below
    owner                  TEXT NOT NULL,
    status                 TEXT NOT NULL,            -- provisioning|ready|deleting|failed
    status_error           TEXT NOT NULL DEFAULT '',
    nebula_space           TEXT NOT NULL,
    chunks_collection      TEXT NOT NULL,
    er_vec_collection      TEXT NOT NULL,
    report_vec_collection  TEXT NOT NULL,
    pg_schema              TEXT NOT NULL,
    nebula_partition_num   INTEGER NOT NULL DEFAULT 10,
    max_inflight           INTEGER,                  -- reserved (future fairness), unused in v1
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS api_keys (
    key_hash    TEXT PRIMARY KEY,                    -- sha256 hex of the key
    owner       TEXT NOT NULL,
    graph_ids   TEXT[] NOT NULL DEFAULT '{}',
    is_admin    BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Bootstrap (idempotent, in `setup_db`):

- Row `default`: `kb` / `settings.milvus.collection` (`kb_llamaindex`) /
  `entity_er_vec` / `community_report_vec` / `public`, status `ready`.
- The existing configured API key is inserted as `is_admin=true`,
  `graph_ids={default}`.

### Graph id

Slug `^[a-z][a-z0-9_]{1,30}$`, validated on every entry point. It is
interpolated into DDL (`CREATE SPACE`, `CREATE SCHEMA`, collection names)
where bind parameters are impossible, so validation is the injection
defence. `default` is reserved.

New-graph physical names: space `g_<id>`, collections `g_<id>_chunks`,
`g_<id>_er_vec`, `g_<id>_report_vec`, PG schema `g_<id>`.

### GraphContext

Frozen dataclass: `id` + all physical names from the registry row. Resolved
by `GraphRegistry.get(graph_id)` with a short-TTL in-process cache
(invalidated on status change by the admin paths in the same process;
TTL bounds staleness elsewhere). Raises `GraphNotFound` / `GraphNotReady`.

### GraphResources

Replaces the process-global singletons. Keyed by `graph_id`, lazily built,
thread/async-safe:

- **Nebula:** one `ConnectionPool` per process (unchanged health-check
  config). One store per graph holding a session that issued
  `USE <space>` + `ensure_schema`; the reconnect closure re-acquires for
  the same space. `SPACE_NAME` constant in `nebula_schema.py` is removed —
  space comes from `GraphContext`; `ensure_schema(session, space)`.
- **Milvus:** chunk vector store / `ChunkRepository`, ER vector store,
  community-report vector store per graph, built from the context's
  collection names. `_COLLECTION` constants removed.
- **Postgres:** shared pools (`pg_pool`, `pg_sync_pool`). A scoped
  checkout helper sets `SET search_path TO <pg_schema>, public` on
  acquire; the pool `reset=` callback runs `RESET search_path` on return,
  so a schema never leaks into the next checkout. Global tables (`graphs`,
  `api_keys`, `bot_user`, `bot_request`) are addressed with the explicit
  `public.` prefix.
- **Search deps:** `src/workflow/_search_deps.py` `_state` and
  `src/mcp/tools_server.py` `_deps` become per-graph dicts. Graph-agnostic
  parts (LLM, embed model, reranker, LLM pool) stay process-global.

Graph-scoped PG tables (live in each graph schema): `documents`, `entity`,
`er_verdict`, `fact_supersede`, `ingest_metrics`, `stat_indicator`,
`stat_observation`. `migrate_graph_schema(ctx)` applies the same idempotent
DDL `setup_db` applies today, inside the graph schema.

## 2. Propagation of graph_id

### HTTP API

Dependency `resolve_graph` (FastAPI): reads `X-API-Key` → `api_keys` row
(by sha256), reads `X-Graph`.

| Case | Result |
|------|--------|
| Missing/unknown key | 401 |
| No `X-Graph`, key has exactly one graph | that graph |
| No `X-Graph`, key has several | 400 |
| Graph not in key's list (non-admin) | 403 |
| Graph does not exist | 404 |
| Graph status ≠ `ready` | 409 |

Returns `GraphContext`. All routes (`ingest`, `search_v2`, `analyze`,
`documents`, `entities`, `stats`, `stats_data`, `graph_admin`) take it via
`Depends` and pass `graph_id` onward. Admin graph/key endpoints require
`is_admin`. An admin key may address any graph (its `graph_ids` only sets
the implicit graph when `X-Graph` is absent).

### MCP

Graph bound at connection: URL `/mcp/<graph>/sse` or `X-Graph` header
during handshake. `build_sse_auth` validates key + graph with the same rules
as HTTP and rejects the handshake on failure. The resolved `GraphContext`
lives in the session context; tools (search 5, tools 18, stats 3) read it
from there. No graph parameter in any tool signature.

### Temporal

- `graph_id: str` added to `IngestParams`, `Ctx`, and the input models of
  every search, community, analytics, monitor workflow/activity.
- Activities resolve `GraphContext` from the registry; physical names are
  never carried in workflow inputs (no stale names in history).
- Workflow ids gain the graph: `ingest-{graph}-{doc_id}`,
  `graph-{graph}-{doc_id}`, `community-build-{graph}-{rid}`,
  `analytics-materialize-{graph}-{rid}`, `search-*-{graph}-{rid}`,
  `mcp-*-{graph}-{uuid}`. `ingest-scheduler` stays a single system-wide
  workflow; each pending `IngestParams` carries its `graph_id`.
- Transition: `graph_id` defaults to `"default"` while pre-deploy
  workflows drain; the default is removed in a follow-up once no running
  workflow lacks it.

### RabbitMQ

Single `ingest.pending` queue; `graph_id` inside the `IngestParams`
payload. Consumer uses the graph-prefixed workflow id.

### Failure discipline

- No fallback to `default` anywhere after the transition. Unknown or
  non-ready graph in an activity → non-retryable `ApplicationError`.
- Storage-touching functions take `GraphContext` (or resources built from
  it) as an explicit argument — no contextvar. A forgotten graph is a type
  error, not a silent write to `default`.

## 3. Graph lifecycle

### Create — `POST /admin/graphs` (admin)

Body: `id`, `owner`, optional `nebula_partition_num` (default 10).

1. Validate slug; insert row `status=provisioning`; return `202`.
2. `ProvisionGraphWorkflow` (id `graph-provision-{id}`), idempotent steps:
   - `CREATE SPACE IF NOT EXISTS g_<id> (partition_num=<n>, replica_factor=1, vid_type=FIXED_STRING(32))`;
     retry `USE` until the async space is ready; `ensure_schema`.
   - Create three Milvus collections with the same index params as the
     default graph (HNSW, `settings.milvus.dim`).
   - `CREATE SCHEMA IF NOT EXISTS g_<id>`; `migrate_graph_schema`.
   - `status=ready`.
   - Retries exhausted → `status=failed`, `status_error` set. A repeated
     `POST` with the same id on a `failed` graph resumes provisioning.

`GET /admin/graphs`, `GET /admin/graphs/{id}`: registry rows.
`PATCH /admin/graphs/{id}`: `owner`, `max_inflight` only.

### Delete — `DELETE /admin/graphs/{id}?confirm=<id>` (admin)

- `default` is not deletable (409). `confirm` must equal `id` (400).
- `status=deleting` immediately; requests for it get 409.
- `DeleteGraphWorkflow`: cancel/await in-flight ingest workflows of the
  graph; `DROP SPACE`; drop three collections; `DROP SCHEMA g_<id> CASCADE`;
  delete MinIO objects under `<id>/` in upload + staging buckets; remove
  the graph from every `api_keys.graph_ids`; delete the registry row.

### MinIO

New graphs store objects under key prefix `<graph>/` in `kb-uploads` and
`kb-staging`. `default` keeps its unprefixed keys.

### Schema migrations on deploy

`setup_db` iterates all `ready` graphs: `migrate_graph_schema` + Nebula
`ensure_schema` for each. DDL must stay idempotent.

### API keys — `POST /admin/api-keys`, `DELETE /admin/api-keys/{hash}` (admin)

Key generated server-side, returned once; only sha256 stored.

## 4. Background jobs and per-graph compute

- **Community build / analytics materialize:** run for the graph from
  `X-Graph`. `POST /admin/graphs/refresh-all` starts build + materialize
  sequentially over all `ready` graphs. Overlap guard is per graph. The .31
  cron (`agent_v2/scripts/`, every 6h) switches to `refresh-all`.
  Leiden / igraph computed in-worker one graph at a time.
- **Entity resolution:** per-graph `er_verdict` + `er_vec`; identical names
  in two graphs are distinct vertices in distinct spaces (intended).
- **Monitor / alerts:** `monitor-sweep` iterates graphs; alert state lives
  in the graph's store (verify during planning that nothing alert-related
  is process-global).
- **Stats:** `stat_*` in the graph schema; stats MCP server uses the
  session's graph.
- **Telegram bot:** `bot_user` / `bot_request` stay global; bot queries
  the graph named by setting `BOT_GRAPH` (default `default`).
- **openclaw agents:** choose a graph by their MCP server URL.
- **Wiki / Wikibase:** activities run only when `graph_id == "default"`,
  otherwise skip with a log line.
- **Shared, not per-graph:** LLM pool, reranker, embeddings, Temporal
  worker + task queues.

## 5. Errors, testing, rollout

### Testing (TDD; extend `tests/`)

Unit:

- slug validation incl. DDL-injection attempts;
- `resolve_graph`: every row of the status table in §2;
- PG scoped checkout sets `search_path`; reset on return; a second
  checkout does not inherit it;
- Nebula per-graph session issues `USE <space>`; reconnect re-USEs the
  same space;
- graph-prefixed workflow ids;
- registry cache TTL + invalidation;
- MCP handshake rejects wrong/missing graph.

Guard test: fails if any module under `src/` calls the graph/vector/PG
factories bypassing `GraphResources`, or references
`settings.milvus.collection` / collection-name constants outside the
registry bootstrap.

Isolation test (integration, live stack, marked):

- create graphs `a`, `b`; ingest one doc into each with a unique entity;
- for each graph: search (local/global/drift/auto), analyze, entities,
  stats, community build + read, every MCP tool — never returns the other
  graph's entity/chunk/community;
- delete `b` → `a` and `default` unaffected; `b`'s space, collections,
  schema, MinIO prefix gone.

Regression: existing suite + `tests/eval/` on `default` unchanged.

### Rollout

1. Sub-project 0 (remove Neo4j) deployed and eval-checked.
2. Deploy multi-graph with only `default` registered — no behaviour change;
   pre-deploy workflows drain via the `graph_id="default"` default.
3. On .31 create a test graph, run the isolation test manually.
4. Onboard the first client graph.
5. Remove the transitional `graph_id` default.

Rollback: `default` uses unchanged physical names, so reverting code needs
no data rollback; graphs created after deploy become unreachable until
re-deploy.

## Out of scope (backlog)

- Per-graph fairness for ingest admission and the LLM pool (see
  brainstorming note: on RabbitMQ this needs a queue per graph with
  prefetch-quota + global semaphore; on Temporal, quota-aware pick in the
  scheduler).
- Cross-graph search / client → graphs hierarchy.
- Per-graph wiki / Wikibase.
- Per-bot-user graph selection.

## Amendment 2026-10-17 — keys authenticate only

User decision, supersedes parts of D1 and the auth sections above:

- **D1 "an API key grants a list of graphs" is withdrawn.** There is no
  per-key graph authorization in this service. Any valid API key may read and
  write **any** graph; per-graph access control belongs to a separate layer
  (out of scope here).
- **Admin gating is withdrawn.** No admin keys: `is_admin` and `graph_ids` are
  dropped from `public.api_keys` (now `key_hash`, `owner`, `created_at`) and
  from `ApiKeyRecord` (`owner` only). Admin endpoints (`/admin/graph/*`,
  `/admin/wiki/*`, `/admin/monitor/*`, `POST /api/v1/admin/communities/rebuild`)
  require just a valid key.
- **Graph selection (HTTP):** only the `X-Graph` header; absent → `default`.
  Missing key → 401, invalid key → 403, invalid slug → 400 `invalid X-Graph`,
  unknown graph → 404, not `ready` → 409. The "key has several graphs → 400"
  and "graph not in key's list → 403" rows of the table above no longer apply.
- **Graph selection (MCP):** `X-Graph` header if present, else `KB_MCP_GRAPH`
  (default `default`) — the same for HTTP with or without auth and for stdio.
  The token verifier validates the key only (claims: `owner`). Invalid /
  unknown / not-ready graph → `ToolError`.
- Unchanged: env `API_KEYS` stay valid (legacy fallback, pruned by
  `owner='legacy-env'` in `setup_db`); default-only feature limits (wiki,
  monitor 409; Wikibase skip; entity-watch `ToolError`) — those are feature
  limits, not authorization.
