# Remove Neo4j — design

Date: 2026-09-24
Status: approved in brainstorming, pending spec review
Sub-project 0 of the multi-graph effort (see `2026-09-24-multi-graph-design.md`).

## Goal

NebulaGraph becomes the only graph backend. Every Neo4j code path, setting,
dependency and test is removed. Pure refactor: no behaviour change for a
deployment already running `GRAPH_BACKEND=nebula` (production default).

Why now: the multi-graph work must thread a graph context through every
graph seam. Today each seam has two implementations (Neo4j-verbatim +
Nebula-nGQL). Removing one halves the multi-graph diff and the number of
places where isolation can be broken. Neo4j will never be used again.

## Scope

In scope:

- `GraphSettings.backend` (`GRAPH_BACKEND`) and its dispatch in
  `src/graph/store.py` — removed; `build_graph_store()` returns the Nebula
  store directly.
- `Neo4jSettings` (`NEO4J_*`) in `src/config.py` — removed.
- All `Neo4j*` classes and the neo4j branch of every `build_*` factory:
  `analytics_graph_ops`, `signals_graph_ops`, `er_graph_ops`,
  `events_graph_ops`, `events_llm_graph_ops`, `wiki_graph_ops`,
  `communities_graph_ops`, `domain_graph_ops`, `dynamics_graph_ops`,
  `aggregations_graph_ops`, `rollups_graph_ops`, `centrality_graph_ops`,
  `quality_graph_ops`, `graph_edge_export`, `community_vector_store`,
  `community_read`, `community_writeback`, `community_summarize`,
  `entity_vector_store`, `alert_store`. Where a factory then has a single
  implementation, the Protocol stays (it is the test seam) and the factory
  returns the Nebula class.
- Backend flags collapsed to their Nebula-era value, option removed:
  - `community_backend`: drop `"gds"`; values `leidenalg | graphscope`,
    default `leidenalg`.
  - `centrality_backend`: drop `"gds"`; only `igraph` remains → flag removed.
  - `er_vector_backend`: drop `"native"`; Milvus `entity_er_vec` only → flag
    removed.
  - `community_vector_backend`: drop `"native"`; Milvus
    `community_report_vec` only → flag removed.
- Neo4j-only modules/paths: `src/graph/write_retry.py` (Neo4j
  `TransientError` retry), Neo4j query-log wrapper and Bolt pool code in
  `store.py`, Neo4j vector/fulltext index DDL in `src/graph/index.py`, any
  `llama_index.graph_stores.neo4j` usage in `build_property_graph`,
  `graph_build`, `retriever`, `_search_deps`, `health` route.
- Dependencies: `llama-index-graph-stores-neo4j`, `neo4j` removed from
  `pyproject.toml` / `uv.lock` / `requirements.txt`.
- Tests: Neo4j-only tests deleted; parity tests (Neo4j vs Nebula) reduced
  to Nebula assertions; fakes that emulate Neo4j sessions removed.
- Config/compose/docs: `NEO4J_*` / `GRAPH_BACKEND` removed from
  `.env.example`, compose files, `docs/`; comments that explain behaviour
  "mirrors Neo4j" rewritten only where they would otherwise be wrong.

Out of scope:

- `graphscope` community backend — independent of Neo4j, kept.
- `er_verdict_cache_backend` (`postgres | graph`) — orthogonal, kept.
- Wiki / Wikibase modules — removed later, separately; only their Neo4j
  branches go here.
- Any Nebula behaviour change, schema change, or performance work.

## Approach

1. Delete bottom-up: settings and factory branches first, so the type
   checker / import errors enumerate every remaining caller.
2. Each `*_graph_ops` module: delete the `Neo4j*` class, make the factory
   return the Nebula class unconditionally, keep the Protocol.
3. `store.py`: `build_graph_store()` → `build_nebula_graph_store()`;
   `reset_*` test hook kept for Nebula.
4. Remove flags; any code branching on them keeps only the Nebula-era
   branch.
5. Guard test: `tests/test_no_neo4j.py` greps `src/` and `pyproject.toml`
   for `neo4j` (case-insensitive) and fails on any hit — comments
   included, so historical "mirrors Neo4j" remarks are rewritten or
   dropped.

## Verification

- Full test suite green (after Neo4j-only tests are removed).
- `graphify update .` run; `rg -i neo4j src pyproject.toml` empty.
- Live on .31: rebuild api + worker + mcp images, run one ingest, one
  search of each mode (local/global/drift/auto), community build,
  analytics materialize, `kb_analyze` trend query — results equivalent to
  pre-change.
- Eval (`tests/eval/`) on the default graph: no regression.

## Risks

- A Nebula path that silently relied on a Neo4j default (e.g. a flag whose
  default was `gds`/`native` and was only "forced" to Nebula values at
  runtime). Mitigation: removing the flags makes the forced value the only
  value; the live check covers community + analytics.
- Deployment `.env` on .31 still sets `NEO4J_*` / `GRAPH_BACKEND` — harmless
  (`extra="ignore"`), cleaned in the same deploy.
