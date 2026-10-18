# Multi-graph operations

Operator notes for graphs other than `default`. Design: `docs/superpowers/specs/2026-09-24-multi-graph-design.md`
(§3 + amendments 2026-10-17 / 2026-10-18). Plan: `docs/superpowers/plans/2026-10-18-multi-graph-lifecycle.md`.

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
- `POST` for an id that is `ready` / `provisioning` / `deleting` → 409, no second workflow.
- Other endpoints: `GET /admin/graphs` (list), `PATCH /admin/graphs/acme` (`owner`, `max_inflight`).

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
  when `ready` or `failed`). Activities refuse `default` even when called directly.
- Staging blobs are not purged by delete (per-run, removed by the orphan sweep).
- Re-creating the same id later is safe: per-graph caches are keyed by `id#generation`, so no process reuses
  the old Nebula session or retrievers.

## 4. Security

Any valid API key can create and delete graphs (amendment 2026-10-17 — keys authenticate, they do not
authorize). If clients hold keys, restrict `/admin/*` at the reverse proxy.

## 5. Deploy

1. Run `setup_db` first: it moves `pg_trgm` to the `extensions` schema, adds `graphs.generation` and sets the
   database `search_path`. A graph schema's `search_path` is `<schema>, extensions` — no `public` fallback, so
   a missing per-graph table errors instead of silently reading `default`'s.
2. Restart the API, every MCP server and **all** worker pools — the `graph_build` pool runs the lifecycle
   workflows.

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

Every line must print `PASS`; exit code 0.
