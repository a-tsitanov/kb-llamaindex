# Multi-graph operations

Operator notes for graphs other than `default`. Design: `docs/superpowers/specs/2026-09-24-multi-graph-design.md`
(§3 + amendments 2026-10-17 / 2026-10-18) and `docs/superpowers/specs/2026-10-18-tenancy-authz-design.md`
(tenants + per-key authorization). Plans: `docs/superpowers/plans/2026-10-18-multi-graph-lifecycle.md`,
`docs/superpowers/plans/2026-10-18-tenancy-authz.md`.

Graphs are created **only explicitly**. An unknown `X-Graph` is 404 everywhere (ingest included) — nothing is
auto-provisioned. Graph id: `^[a-z][a-z0-9_]{1,30}$`; `default` is reserved and can never be created, dropped or
deleted.

## 1. Create

```bash
curl -X POST $API/admin/graphs -H "X-API-Key: $K" -H 'Content-Type: application/json' \
  -d '{"id":"acme","owner":"team"}'
# 202 {"id":"acme","status":"provisioning","workflow_id":"lifecycle-provision-acme"}

curl $API/admin/graphs/acme -H "X-API-Key: $K"   # poll until "status": "ready"
```

`ProvisionGraphWorkflow` (on the `graph_build` queue) creates the Nebula space `g_acme`, Milvus collections
`g_acme_chunks|_er_vec|_report_vec`, PG schema `g_acme` and MinIO prefix `acme/`. Every step is idempotent.

- `failed` → read `status_error`, fix the cause, `POST` the same body again: the row is resumed (202).
- `POST` for a slug that is taken → 409 `graph id is not available`, no second workflow. The body is the
  same whether the slug is yours (`ready` / `provisioning` / `deleting`) or another tenant's — otherwise
  the body of a conflict on your own graph would be the oracle telling the two apart. The real status goes
  to the API log only.
- The new graph is born in the calling key's tenant; `tenant_id` is never taken from the body.
- Other endpoints: `GET /admin/graphs` (list, filtered to your tenant under `enforce`),
  `PATCH /admin/graphs/acme` (`owner`, `max_inflight`). Rows carry `tenant_id`; `owner` stays free text and
  no longer controls access.

## 2. Use

| Client | How to select the graph |
|---|---|
| HTTP API | header `X-Graph: acme` (absent → `default`) |
| MCP | header `X-Graph`, else env `KB_MCP_GRAPH` (default `default`) |
| Telegram ingest | `tg_ingest --graph acme` or env `KB_GRAPH=acme` |
| Bot | env `BOT_GRAPH=acme` |

`tg_ingest` keeps sync cursors per graph: with a non-default `--graph` the
`--state` file becomes `<stem>.<graph>.json` (e.g. `tg_ingest.state.acme.json`),
so switching graphs bootstraps the new one instead of resuming `default`'s cursors.

A graph that is not `ready` answers 409 (HTTP) / `ToolError` (MCP).

## 3. Delete

```bash
curl -X DELETE "$API/admin/graphs/acme?confirm=acme" -H "X-API-Key: $K"
# 202 {"id":"acme","status":"deleting","workflow_id":"lifecycle-delete-acme"}
curl $API/admin/graphs/acme -H "X-API-Key: $K"   # 404 once gone
```

- Takes at least ~2 min: registry settle 35 s (so every process stops serving the graph) + drain grace 60 s,
  then the teardown steps.
- In-flight ingest workflows of that graph are **terminated**.
- Guards: `default` → 409; `confirm` ≠ id → 400; unknown id → 404; graph still `provisioning` → 409 (retry
  when `ready` or `failed`). Another tenant's graph → 404, dropped before `mark_deleting`, so nothing is
  started and nothing is disclosed. Activities refuse `default` even when called directly.
- Staging blobs are not purged by delete (per-run, removed by the orphan sweep).
- Re-creating the same id later is safe: per-graph caches are keyed by `id#generation`, so no process reuses
  the old Nebula session or retrievers.

## 4. Security: tenants, keys, AUTHZ_MODE

A key authenticates **and** authorizes (spec 2026-10-18; this cancels "keys authenticate only" from the
2026-10-17 amendment). Each key carries a tenant, a set of actions and an optional list of its own graphs:

| Field | Meaning |
|---|---|
| `tenant_id` | Whose key it is. A graph belongs to a tenant too; a key never sees another tenant's graph. |
| `scopes` | Any of `read`, `write`, `download_original`, `admin`. Handing out the source file is NOT part of `read`. |
| `graph_ids` | `NULL` = every graph of the tenant; a list narrows the key to those ids. |

Tenants and keys are created **only** by CLI — there is no HTTP route, by design:

```bash
uv run python -m scripts.tenant_admin create --id acme --name 'ACME Inc'
uv run python -m scripts.tenant_admin key --tenant acme --owner ci --scopes read,write
uv run python -m scripts.tenant_admin key --tenant acme --owner bot --scopes read --graphs acme_news
uv run python -m scripts.tenant_admin list          # no raw keys, ever
uv run python -m scripts.tenant_admin revoke --key-hash <sha256>
```

The raw key is printed once and only its sha256 is stored: a lost key is re-issued, never recovered.
A revoke is not instant — `ApiKeyStore` caches a lookup (and its absence) for 30 s in every api/mcp
process; restart api + mcp-* when it has to take effect now.

Keys from the env `API_KEYS` stay valid and keep full rights in tenant `default`.

**`AUTHZ_MODE`** (`off` | `log` | `enforce`, default `log`) is the one switch, and it gates both the
decision and the repository-level tenant filters:

| Mode | Effect |
|---|---|
| `off` | Emergency lever: nothing filters, nothing refuses — behaviour from before this feature. |
| `log` | Decision computed, refusal logged as `authz would-deny key_owner=… reason=…`, request allowed. **Not protection**: a foreign graph is still readable and deletable, and `GET /admin/graphs` still lists everything. |
| `enforce` | Refusals applied (403 for a missing right on your own graph, 404 for someone else's graph) and the list is filtered. |

Rollout order (`setup_db` to completion → restart → a day in `log` → `enforce`) is in
[`DEPLOYMENT.md` §5a](DEPLOYMENT.md). What leaks by design, even under `enforce`: whether a graph slug
is taken (`POST` answers 202 or 409), because physical names are derived from the id, so the id space is
global; and a timing difference between an absent graph (negative cache 2 s) and a foreign one (30 s).

MCP: `KB_MCP_REQUIRE_AUTH=false` and stdio have no token, hence **no authorization at all** — acceptable for
a local stdio client, not for a server on a network port. See [`runbook/mcp.md` §6](runbook/mcp.md).

If clients hold keys, restricting `/admin/*` at the reverse proxy is still a sensible second layer.

## 5. Deploy

1. Run `setup_db` first **and let it finish**: it moves `pg_trgm` to the `extensions` schema, adds
   `graphs.generation` and sets the database `search_path`; it also creates `public.tenants` (+ tenant
   `default`), adds `graphs.tenant_id` and `api_keys.tenant_id|scopes|graph_ids`, and once grandfathers
   existing keys to full rights (marker `authz_grandfather_v1` in `public.schema_migration`). A graph
   schema's `search_path` is `<schema>, extensions` — no `public` fallback, so a missing per-graph table
   errors instead of silently reading `default`'s.
2. Only then restart the API, every MCP server and **all** worker pools — the `graph_build` pool runs the
   lifecycle workflows. On the offline cluster `depends_on` is reset, so step 1 is a manual
   `run --rm --no-deps init python -m scripts.setup_db` (`deploy/offline/DEPLOYMENT.md` §11).
3. Code that comes up before the migration does not fail: a key row without a `scopes` column is read as
   full rights (fail-open) with a one-off warning. Until the migration has run, `enforce` protects nothing.

## 6. Default-only features

Wiki, Wikibase push and monitor alerts work on `default` only. Entity watch works on every graph.

## 7. Community / analytics refresh for a new graph

The host cron refreshes `default` only (until `refresh-all` exists). For another graph call, with
`X-Graph: acme`:

```bash
curl -X POST $API/api/v1/admin/communities/rebuild -H "X-API-Key: $K" -H "X-Graph: acme"
curl -X POST $API/admin/graph/materialize          -H "X-API-Key: $K" -H "X-Graph: acme"
```

## Live isolation smoke

`scripts/smoke_graph_isolation.py` creates a graph, ingests one document, proves `default` cannot see it and
deletes it. It touches a real stack — run only with explicit approval:

```bash
uv run python -m scripts.smoke_graph_isolation --api-base http://localhost:8000 --api-key "$KB_API_KEY" \
  [--graph smoke_iso] [--timeout 900]
```

With a second tenant's key it also proves cross-tenant isolation (list / GET / data / POST / DELETE all
behave as if the other tenant's graph did not exist). That part only makes sense under
`AUTHZ_MODE=enforce` — in `log` it is expected to fail:

```bash
uv run python -m scripts.smoke_graph_isolation --api-base http://localhost:8000 --api-key "$KEY_A" \
  --api-key-b "$KEY_B" --graph-b "$GRAPH_OF_B"
```

Every line must print `PASS`; exit code 0.
