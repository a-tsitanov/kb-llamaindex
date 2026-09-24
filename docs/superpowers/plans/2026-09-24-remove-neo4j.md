# Remove Neo4j Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make NebulaGraph the only graph backend: delete every Neo4j code path, setting, dependency, script and test, with no behaviour change for a `GRAPH_BACKEND=nebula` deployment.

**Architecture:** Two phases. Phase A moves the unit-test harness from its Neo4j pin to Nebula and ports/deletes the tests that only exercised Neo4j branches — after it, no test touches Neo4j code, so Phase B can delete that code freely while the suite stays green. Phase B deletes bottom-up: factory branches → inline branches → GDS/flags → store/settings → deps/scripts/docs, then a guard test locks it in.

**Tech Stack:** Python 3.12, pytest (`uv run --extra dev pytest`), nebula3-python, pymilvus, llama-index-core, Temporal.

**Spec:** `docs/superpowers/specs/2026-09-24-remove-neo4j-design.md`

## Global Constraints

- No behaviour change for a Nebula deployment: every kept code path is the one that ran under `settings.graph.backend == "nebula"`.
- Kept, not touched: `graphscope` community backend, `er_verdict_cache_backend` (`postgres | graph`), wiki/Wikibase modules (only their Neo4j branches go).
- `community_backend` becomes `Literal["leidenalg", "graphscope"]`, default `"leidenalg"`.
- Removed flags: `GRAPH_BACKEND` (`GraphSettings`), `NEO4J_*` (`Neo4jSettings`), `centrality_backend`, `er_vector_backend`, `community_vector_backend`.
- Removed deps: `llama-index-graph-stores-neo4j`, `neo4j`.
- Historical docs under `docs/superpowers/{plans,specs}/` and `docs/superpowers/nebula-cutover-*.md` are NOT edited (they are records).
- Test command everywhere: `uv run --extra dev pytest -q -p no:cacheprovider --ignore=tests/eval -m "not integration"`; referred to below as **SUITE**.
- Git: commit locally per task on branch `a-tsitanov/tenant` (or a feature branch cut from it). **Never push.** Never `git stash` / `git checkout` another branch.
- After the last task: `graphify update .`

## Baseline (measured 2026-09-24 on f2a2f19)

SUITE on HEAD: `43 failed, 2223 passed, 23 skipped`.

- 2 genuine failures, unrelated to Neo4j removal except the first:
  - `tests/test_config/test_graph_settings.py::test_graph_backend_defaults_to_neo4j` — asserts the old `neo4j` default (fixed in Task 1).
  - `tests/test_scripts/test_make_env.py` — 4 env vars without a description (`BOT_AGENT_BASE`, `BOT_AGENT_TOKEN`, `SIGNALS_SOURCE_TRUST`, `SIGNALS_SOURCE_TRUST_DEFAULT`); out of scope, stays failing.
- ~41 order-dependent failures: `tests/test_config/test_llm_factory.py` does `importlib.reload(src.config)`, so modules hold two different `settings` objects; the autouse pin in `tests/conftest.py:29` sets `backend="neo4j"` on one while modules read `nebula` from the other. Each of those files passes alone. The pin removal in Task 1 eliminates this class.

With the pin flipped to `nebula`, SUITE fails 102 tests across 31 files — the set Phase A must resolve (list in Task 1 Step 1).

**Gate for every task:** SUITE failures ⊆ {`test_make_env.py::*`}. Before Task 1 that gate is the baseline above.

## Review Focus

1. A Nebula deployment whose `.env` never set `TEMPORAL_COMMUNITY_BACKEND` — must now get `leidenalg`, not crash on a removed `gds` value. Pinned by Task 6 Step 1 test `test_community_backend_default_is_leidenalg`.
2. An old `.env` that still sets `GRAPH_BACKEND=nebula`, `NEO4J_URI`, `TEMPORAL_COMMUNITY_BACKEND=gds`, `AGENT_ER_VECTOR_BACKEND=native` — the first three settings classes ignore unknown keys (`extra="ignore"`), but `TEMPORAL_COMMUNITY_BACKEND=gds` is a *known* key with a now-invalid value and would fail validation at startup. Pinned by Task 6 test `test_legacy_gds_value_maps_to_leidenalg`.
3. A test file that silently loses coverage of backend-agnostic logic (fallbacks, budgets, descent) because its Neo4j fake was deleted instead of ported. Pinned by Task 1–4 rule "delete only with a named Nebula counterpart" + per-task counterpart list in the commit message.
4. `import neo4j` left in a lazily-imported module (only fails when that path runs in prod). Pinned by Task 9 guard test scanning `src/`, `scripts/`, `pyproject.toml`.
5. Ingest write under hub-node contention after `write_with_retry` removal — Nebula never raised Neo4j `TransientError`, so the wrapper was a pass-through; the Temporal activity retry remains the backstop. Pinned by Task 8 Step 1 test `test_build_property_graph_writes_without_retry_wrapper`.

---

## Phase A — tests off Neo4j

### Triage rule (applies to Tasks 1–4)

For every test that fails once the pin is gone:

- **Delete** it if what it asserts is Neo4j-specific: Cypher text, `param_map` shape, a `Neo4j*` class, GDS calls, `Neo4jPropertyGraphStore` behaviour. Before deleting, find the Nebula test that covers the same *behaviour* (`grep -rn "<function under test>" tests/ | grep -i nebula`) and list `deleted → counterpart` in the commit message. If no counterpart exists, **port** instead.
- **Port** it if it asserts backend-agnostic behaviour (ranking, fallbacks, budgets, fail-soft, parsing) through a fake store that answers Cypher. Replace the fake with one that answers the nGQL the Nebula branch issues (copy query-matching style from existing Nebula fakes, e.g. `tests/test_graph/test_nebula_store_writes.py::_FakeSession`, `tests/test_retrieval/test_nebula_read_slice.py::_FakeStore`) and set `settings.graph.backend` is no longer needed. Keep the assertion unchanged.
- Never weaken an assertion to make a port pass. If the Nebula branch genuinely behaves differently, stop and report — that is a behaviour difference the spec forbids hiding.

### Task 1: Drop the Neo4j pin; fix config tests

**Files:**
- Modify: `tests/conftest.py:28-38`
- Modify: `tests/test_config/test_graph_settings.py`
- Modify: `tests/test_config/test_community_backend.py`

**Interfaces:**
- Produces: a test harness where modules see the production default `settings.graph.backend == "nebula"`; Tasks 2–4 start from its failure list.

- [ ] **Step 1: Record the failure list**

Delete the `_pin_graph_backend_neo4j` fixture (lines 28–38 of `tests/conftest.py`) entirely. Run SUITE and save the failure list:

```bash
uv run --extra dev pytest -q -p no:cacheprovider --ignore=tests/eval -m "not integration" 2>&1 | grep FAILED | sort > /tmp/neo4j_pin_removed.txt; wc -l /tmp/neo4j_pin_removed.txt
```

Expected: ~102 lines across the 31 files: `test_workflow/test_search_global.py` (11), `test_retrieval/test_graph_walk_retriever.py` (8), `test_workflow/test_search_community.py` (6), `test_graph/test_index.py` (6), `test_graph/test_alerts.py` (6), `test_workflow/test_push_wikibase.py` (5), `test_workflow/test_materialize_activities.py` (5), `test_graph/test_communities.py` (5), `test_graph/test_analysis.py` (5), `test_mcp/test_tools_server_trend.py` (4), `test_graph/test_retriever_triplet_parse.py` (4), `test_analytics/test_connections.py` (4), `test_workflow/test_monitor_activities.py` (3), `test_mcp/test_stats_pipeline.py` (3), `test_graph/test_first_seen_index.py` (3), `test_retrieval/test_graph_path_depth.py` (2), `test_graph/test_community_leiden_extract.py` (2), `test_analytics/test_signals.py` (2), `test_analytics/test_materialize.py` (2), `test_analytics/test_centrality.py` (2), and 1 each in `test_workflow/test_search_documents_activity.py`, `test_workflow/test_merge_and_resolve.py`, `test_workflow/test_build_property_graph.py`, `test_graph/test_wiki_dirty.py`, `test_graph/test_retriever_fulltext.py`, `test_config/test_graph_settings.py`, `test_analytics/test_events_llm.py`, `test_analytics/test_domain.py`, `test_analytics/test_communities.py`, `test_analytics/test_aggregations.py`, `test_scripts/test_make_env.py`.

- [ ] **Step 2: Rewrite `tests/test_config/test_graph_settings.py`**

`GraphSettings` is deleted in Task 7; until then keep only what survives. Replace the file with:

```python
"""NebulaGraph connection settings."""
from __future__ import annotations


def test_nebula_settings_default_port(monkeypatch):
    monkeypatch.delenv("NEBULA_PORT", raising=False)
    from src.config import NebulaSettings

    assert NebulaSettings().port == 9669
```

(Keep any other `NebulaSettings` tests already in the file below this one unchanged.)

- [ ] **Step 3: Triage `tests/test_config/test_community_backend.py`**

Apply the triage rule: delete cases asserting the `"gds"` default/value; keep `leidenalg`/`graphscope` cases. (Task 6 adds the new default test.)

- [ ] **Step 4: Run config tests**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_config`
Expected: only `test_make_env`-unrelated passes; no failures in `tests/test_config/`.

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_config
git commit -m "test: drop neo4j backend pin from harness; nebula is the tested default"
```

### Task 2: Port/delete graph-layer tests

**Files (modify/delete per triage rule):**
`tests/test_graph/test_index.py`, `test_alerts.py`, `test_communities.py`, `test_analysis.py`, `test_retriever_triplet_parse.py`, `test_first_seen_index.py`, `test_community_leiden_extract.py`, `test_wiki_dirty.py`, `test_retriever_fulltext.py`; `tests/test_retrieval/test_graph_walk_retriever.py`, `test_graph_path_depth.py`.

**Interfaces:**
- Consumes: Task 1 failure list.
- Produces: nothing new; these files green without Neo4j fakes.

- [ ] **Step 1: Per file, list failing tests from `/tmp/neo4j_pin_removed.txt` and classify** each as delete (with counterpart) or port. Write the classification as a comment block at the top of your working notes, not in the repo.

- [ ] **Step 2: Apply** deletions and ports. Porting example — a Cypher-answering fake:

```python
class _FakeStore:
    def structured_query(self, query, param_map=None):
        if "MATCH (e:__Entity__)" in query:
            return [{"name": "A", "description": "x"}]
        return []
```

becomes an nGQL-answering fake keyed on what the Nebula branch sends:

```python
class _FakeStore:
    def __init__(self, rows_by_prefix):
        self.rows_by_prefix = rows_by_prefix
        self.queries = []

    def structured_query(self, query, param_map=None):
        self.queries.append(query)
        for prefix, rows in self.rows_by_prefix.items():
            if query.lstrip().startswith(prefix):
                return rows
        return []
```

with the test supplying e.g. `{"LOOKUP ON `Entity`": [...], "FETCH PROP ON `Entity`": [...]}` matching the statements in the Nebula branch of the function under test.

- [ ] **Step 3: Run**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_graph tests/test_retrieval`
Expected: 0 failures.

- [ ] **Step 4: Commit** with the `deleted → counterpart` list in the body:

```bash
git add tests/test_graph tests/test_retrieval
git commit -m "test(graph): port backend-agnostic graph tests to nebula fakes, drop neo4j-only cases" -m "<deleted → counterpart list>"
```

### Task 3: Port/delete analytics + MCP tests

**Files:** `tests/test_analytics/test_connections.py`, `test_signals.py`, `test_materialize.py`, `test_centrality.py`, `test_events_llm.py`, `test_domain.py`, `test_communities.py`, `test_aggregations.py`; `tests/test_mcp/test_tools_server_trend.py`, `test_stats_pipeline.py`.

**Interfaces:** Consumes Task 1 list. Produces green files.

Special cases:
- `test_tools_server_trend.py`: `topic_trend` is refused on backends in `_TOPIC_TREND_UNSUPPORTED_BACKENDS` (`src/mcp/tools_server.py:529`). Keep the tests that assert the Nebula outcome; delete Neo4j-success cases.
- `test_materialize.py` link-prediction cases: under Nebula `link_prediction` is a documented no-op returning 0 (`src/analytics/materialize.py:182-186`). The ported test asserts `== 0` and no store call.

- [ ] **Step 1: Classify** each failing test (delete-with-counterpart / port).
- [ ] **Step 2: Apply** using the fake pattern from Task 2 Step 2.
- [ ] **Step 3: Run** `uv run --extra dev pytest -q -p no:cacheprovider tests/test_analytics tests/test_mcp` — expected 0 failures.
- [ ] **Step 4: Commit**

```bash
git add tests/test_analytics tests/test_mcp
git commit -m "test(analytics,mcp): port to nebula fakes, drop neo4j-only cases" -m "<deleted → counterpart list>"
```

### Task 4: Port/delete workflow tests

**Files:** `tests/test_workflow/test_search_global.py`, `test_search_community.py`, `test_push_wikibase.py`, `test_materialize_activities.py`, `test_monitor_activities.py`, `test_search_documents_activity.py`, `test_merge_and_resolve.py`, `test_build_property_graph.py`.

Special cases:
- `test_search_global.py` descent/semantic tests (11): backend-agnostic (budget, fallback-to-lexical, finest-relevant-child). Port: the Nebula branch reads the tree with `MATCH (c:\`Community\`) WHERE c.\`Community\`.level == 0 ...`, children with `GO FROM "<vid>" OVER \`PARENT_OF\`` + `FETCH PROP ON \`Community\``, and vectors via `_attach_report_vecs_nebula` from the Milvus report-vec store (`src/workflow/search/activities/global_search.py:184-215`). Monkeypatch `build_community_report_vector_store` to a fake returning `{community_id: vec}`; use `community_vid(id, level)` from `src.graph.community_writeback` to build expected vids.
- `test_search_community.py` (6): summarize path; port to the Nebula summarize/writeback classes' queries.
- `test_push_wikibase.py` (5): only default-graph wiki; if the failures come from the Neo4j entity read, port the fake to Nebula entity rows.
- `test_build_property_graph.py` (1): the Neo4j-only `build_property_graph_index` step; delete (Nebula skips it, counterpart: the Nebula upsert test in the same file).

- [ ] **Step 1: Classify.**
- [ ] **Step 2: Apply.**
- [ ] **Step 3: Full SUITE**

Run: SUITE
Expected: failures ⊆ {`tests/test_scripts/test_make_env.py::*`}. The ~41 order-dependent failures from the baseline are gone too.

- [ ] **Step 4: Commit**

```bash
git add tests/test_workflow
git commit -m "test(workflow): port search/community/monitor tests to nebula fakes, drop neo4j-only cases" -m "<deleted → counterpart list>"
```

---

## Phase B — delete Neo4j code

### Task 5: Collapse factory dispatch (graph-ops + stores)

**Files (modify):** `src/graph/analytics_graph_ops.py`, `signals_graph_ops.py`, `er_graph_ops.py`, `events_graph_ops.py`, `events_llm_graph_ops.py`, `wiki_graph_ops.py`, `communities_graph_ops.py`, `domain_graph_ops.py`, `dynamics_graph_ops.py`, `aggregations_graph_ops.py`, `rollups_graph_ops.py`, `centrality_graph_ops.py`, `quality_graph_ops.py`, `graph_edge_export.py`, `community_read.py`, `community_writeback.py`, `community_summarize.py`, `alert_store.py`, `community_vector_store.py`, `entity_vector_store.py`; `src/graph/merge_and_resolve.py:278`, `src/workflow/activities/merge_and_resolve.py:283`.
**Test:** `tests/test_graph/test_factories_nebula_only.py` (create)

**Interfaces:**
- Produces: every `build_*(store)` factory returns its Nebula/Milvus class unconditionally; Protocols kept. Class names unchanged (`Nebula*`, `Milvus*`).

- [ ] **Step 1: Write the failing test**

```python
"""Every graph-ops factory returns the Nebula implementation; no Neo4j class remains."""
from __future__ import annotations

import importlib

import pytest

FACTORIES = [
    ("src.graph.analytics_graph_ops", "build_analytics_graph_ops"),
    ("src.graph.signals_graph_ops", "build_signals_graph_ops"),
    ("src.graph.er_graph_ops", "build_er_graph_ops"),
    ("src.graph.events_graph_ops", "build_events_graph_ops"),
    ("src.graph.events_llm_graph_ops", "build_events_llm_graph_ops"),
    ("src.graph.wiki_graph_ops", "build_wiki_graph_ops"),
    ("src.graph.communities_graph_ops", "build_communities_graph_ops"),
    ("src.graph.domain_graph_ops", "build_domain_graph_ops"),
    ("src.graph.dynamics_graph_ops", "build_dynamics_graph_ops"),
    ("src.graph.aggregations_graph_ops", "build_aggregations_graph_ops"),
    ("src.graph.rollups_graph_ops", "build_rollups_graph_ops"),
    ("src.graph.centrality_graph_ops", "build_centrality_graph_ops"),
    ("src.graph.quality_graph_ops", "build_quality_graph_ops"),
    ("src.graph.graph_edge_export", "build_graph_edge_export"),
    ("src.graph.community_read", "build_community_read"),
    ("src.graph.community_writeback", "build_community_writeback"),
    ("src.graph.community_summarize", "build_community_summarize"),
    ("src.graph.alert_store", "build_alert_store"),
]


@pytest.mark.parametrize(("mod", "fn"), FACTORIES)
def test_factory_returns_nebula_impl(mod, fn):
    m = importlib.import_module(mod)
    obj = getattr(m, fn)(object())
    assert type(obj).__name__.startswith("Nebula"), type(obj).__name__


@pytest.mark.parametrize(("mod", "_fn"), FACTORIES)
def test_no_neo4j_class_left(mod, _fn):
    m = importlib.import_module(mod)
    assert not [n for n in vars(m) if n.startswith("Neo4j")]


def test_vector_stores_are_milvus(monkeypatch):
    from src.graph import community_vector_store_milvus as cm
    from src.graph import entity_vector_store_milvus as em
    from src.graph.community_vector_store import build_community_report_vector_store
    from src.graph.entity_vector_store import build_entity_vector_store

    monkeypatch.setattr(cm.MilvusCommunityReportVectorStore, "__init__", lambda self: None)
    monkeypatch.setattr(em.MilvusEntityVectorStore, "__init__", lambda self: None)
    assert type(build_community_report_vector_store(object())).__name__ == "MilvusCommunityReportVectorStore"
    assert type(build_entity_vector_store(object())).__name__ == "MilvusEntityVectorStore"
```

If a Nebula class constructor rejects `object()` (e.g. requires `_exec`), pass a minimal `types.SimpleNamespace(structured_query=lambda *a, **k: [])` instead — adjust the one call, not the assertion.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_graph/test_factories_nebula_only.py`
Expected: `test_no_neo4j_class_left` FAILS for every module (Neo4j classes exist).

- [ ] **Step 3: Implement.** In each module: delete the `class Neo4j…` and every Cypher constant / helper / import used only by it; replace the factory body:

```python
def build_communities_graph_ops(store: Any) -> CommunitiesGraphOps:
    return NebulaCommunitiesGraphOps(store)
```

For the vector stores:

```python
def build_entity_vector_store(graph_store: Any) -> EntityVectorStore:
    from src.graph.entity_vector_store_milvus import MilvusEntityVectorStore

    return MilvusEntityVectorStore()
```

(same shape for `build_community_report_vector_store`). In both `merge_and_resolve.py` files remove the `isinstance(_evs, Neo4jEntityVectorStore)` branch, keeping the Milvus path. Remove now-unused `from src.config import settings` imports (ruff will flag them).

- [ ] **Step 4: Run** the new test file, then SUITE. Expected: new file green; SUITE gate holds.
- [ ] **Step 5: Commit**

```bash
git add src/graph src/workflow/activities/merge_and_resolve.py tests/test_graph/test_factories_nebula_only.py
git commit -m "refactor(graph): graph-ops and vector-store factories return nebula/milvus only; delete Neo4j* classes"
```

### Task 6: Inline branches, GDS, and backend flags

**Files (modify):**
- Inline `settings.graph.backend` branches — keep the Nebula branch body, delete the other branch and its now-dead helpers (`_stamp_first_seen_neo4j`, `_load_stored_neo4j`, `_DESCENT_ROOT_CYPHER`, `_WATCHED_EDGES_CYPHER`, GDS `_run(graph_name)` paths, etc.):
  `src/graph/analysis.py:188,406,436,462,493,545`, `src/graph/first_seen.py:74`, `src/graph/edge_conflicts.py:139,167`, `src/graph/retriever.py:327,415,526` (+ `Neo4jPropertyGraphStore` import at :277), `src/graph/index.py:62`, `src/mcp/tools_server.py:107,529-531`, `src/workflow/_search_deps.py:73`, `src/workflow/monitor/activities.py:59,114,133`, `src/workflow/search/activities/global_search.py:120,187,200`, `src/workflow/search/activities/documents.py:94`, `src/workflow/activities/build_property_graph.py:117`, `src/workflow/analytics/materialize_activities.py:46,72,204`, `src/analytics/materialize.py:54,182`.
- GDS community path: `src/graph/communities.py` (GDS projection/stream/drop Cypher at ~61–140, `_group…` helpers only used by GDS, dispatch at :452–490, :547, :585, :708).
- Config: `src/config.py:443-454` (`community_backend`, `centrality_backend`), `:686-701` (`er_vector_backend`, `community_vector_backend`).
- **Test:** `tests/test_config/test_community_backend.py`, `tests/test_graph/test_nebula_only_branches.py` (create)

**Interfaces:**
- Consumes: Task 5 factories.
- Produces: `settings.temporal.community_backend: Literal["leidenalg", "graphscope"]`, default `"leidenalg"`; legacy value `"gds"` accepted and mapped to `"leidenalg"` with a warning. No `settings.graph.backend` reads remain except in `src/graph/store.py` (removed in Task 7).

Branch-rewrite rules (apply mechanically):

```python
# A: if/else → keep nebula body
if settings.graph.backend == "nebula":
    X
else:            # or no else, fall-through
    Y
# ⇒
X

# B: early-return guard for non-nebula
if store is None or settings.graph.backend != "nebula":
    return {...}
# ⇒
if store is None:
    return {...}

# C: neo4j-only block
if settings.graph.backend != "nebula":
    Y
# ⇒ (delete)

# D: boolean flag
nebula = settings.graph.backend == "nebula"
# ⇒ inline True, then simplify the uses
```

For `tools_server.py:529`: `_TOPIC_TREND_UNSUPPORTED_BACKENDS` contained `"nebula"`; replace the condition with an unconditional return of the same unavailable message, then keep the message text but drop the `{settings.graph.backend}` interpolation (write `"nebula"` literally).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_config/test_community_backend.py`:

```python
def test_community_backend_default_is_leidenalg(monkeypatch):
    monkeypatch.delenv("TEMPORAL_COMMUNITY_BACKEND", raising=False)
    monkeypatch.delenv("COMMUNITY_BACKEND", raising=False)
    from src.config import TemporalSettings

    assert TemporalSettings().community_backend == "leidenalg"


def test_legacy_gds_value_maps_to_leidenalg(monkeypatch):
    from src.config import TemporalSettings

    s = TemporalSettings(community_backend="gds")
    assert s.community_backend == "leidenalg"


def test_removed_flags_are_gone():
    from src.config import AgentSettings, TemporalSettings

    assert "centrality_backend" not in TemporalSettings.model_fields
    assert "er_vector_backend" not in AgentSettings.model_fields
    assert "community_vector_backend" not in AgentSettings.model_fields
```

Class names verified: `TemporalSettings` (env prefix `TEMPORAL_`), `AgentSettings` (`AGENT_`).

Create `tests/test_graph/test_nebula_only_branches.py`:

```python
"""No module outside the store factory branches on settings.graph.backend."""
from __future__ import annotations

import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
ALLOWED = {SRC / "graph" / "store.py", SRC / "config.py"}
PATTERN = re.compile(r"settings\.graph\.backend|community_backend\s*==\s*[\"']gds|gds\.")


def test_no_backend_branches_outside_store():
    hits = [
        f"{p.relative_to(SRC)}:{i}"
        for p in SRC.rglob("*.py")
        if p not in ALLOWED
        for i, line in enumerate(p.read_text().splitlines(), 1)
        if PATTERN.search(line)
    ]
    assert hits == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run --extra dev pytest -q -p no:cacheprovider tests/test_config/test_community_backend.py tests/test_graph/test_nebula_only_branches.py`
Expected: FAIL (default is `gds`; flags exist; ~50 branch hits).

- [ ] **Step 3: Implement config** in `src/config.py`:

```python
    # Community-detection backend. "leidenalg" = in-worker hierarchical
    # Leiden over the edge export; "graphscope" = distributed single-level
    # Leiden. "gds" (Neo4j GDS) was removed with Neo4j; a legacy "gds" value
    # in an old .env maps to "leidenalg".
    community_backend: Literal["leidenalg", "graphscope"] = "leidenalg"

    @field_validator("community_backend", mode="before")
    @classmethod
    def _map_legacy_gds(cls, v: object) -> object:
        if v == "gds":
            logger.warning("TEMPORAL_COMMUNITY_BACKEND=gds is no longer supported; using leidenalg")
            return "leidenalg"
        return v
```

(import `field_validator` from pydantic and `logger` from loguru if the module lacks them). Delete `centrality_backend`, `er_vector_backend`, `community_vector_backend` fields with their comments.

- [ ] **Step 4: Implement branch rewrites** in every file listed above using rules A–D; delete the GDS path from `communities.py` so dispatch is:

```python
    if settings.temporal.community_backend == "graphscope":
        ...existing graphscope block unchanged...
    else:
        ...existing leidenalg block unchanged...
```

Remove the `_DESCENT_ROOT_CYPHER`-style constants, GDS Cypher strings, and imports that became unused. Run `uv run ruff check src --select F401,F811,F841` and fix what it reports in touched files.

- [ ] **Step 5: Run** the two test files, then SUITE. Expected: green; gate holds.
- [ ] **Step 6: Commit**

```bash
git add src tests/test_config/test_community_backend.py tests/test_graph/test_nebula_only_branches.py
git commit -m "refactor: drop neo4j/GDS branches and backend flags; community_backend defaults to leidenalg"
```

### Task 7: Store, settings, write-retry, health

**Files:**
- Modify: `src/graph/store.py` (delete Neo4j construction, Bolt pool, query-log wrapper, `build_neo4j_graph_store`, `reset_neo4j_graph_store`; `build_graph_store()` returns `build_nebula_graph_store()`), `src/graph/backend.py` (docstring), `src/graph/index.py` (Neo4j fulltext/vector DDL constants and the `_skip_on_nebula`-style wrapper — every wrapped fn now becomes a no-op; delete the wrapped fns and their call sites if they only did Neo4j DDL), `src/api/routes/health.py` (Neo4j probe → Nebula probe or removal), `src/workflow/activities/build_property_graph.py` + `src/workflow/activities/inject_canonical.py` (call `graph_store.upsert_*` / `inject_canonical_entities` directly), `src/config.py` (delete `Neo4jSettings`, `GraphSettings`, and the `neo4j` / `graph` fields on `Settings`).
- Delete: `src/graph/write_retry.py`, its tests (`grep -rl write_retry tests`).
- Test: `tests/test_graph/test_store.py`, `tests/test_workflow/test_build_property_graph.py`

**Interfaces:**
- Produces: `src.graph.store.build_graph_store() -> NebulaGraphStore`; `settings.neo4j` and `settings.graph` no longer exist.

- [ ] **Step 1: Write the failing tests**

In `tests/test_graph/test_store.py` (replace Neo4j cases):

```python
def test_build_graph_store_is_nebula(monkeypatch):
    import src.graph.nebula_store as ns
    from src.graph import store

    sentinel = object()
    monkeypatch.setattr(ns, "build_nebula_graph_store", lambda: sentinel)
    assert store.build_graph_store() is sentinel


def test_settings_have_no_neo4j_or_graph_section():
    from src.config import settings

    assert not hasattr(settings, "neo4j")
    assert not hasattr(settings, "graph")
```

In `tests/test_workflow/test_build_property_graph.py`:

```python
def test_build_property_graph_writes_without_retry_wrapper():
    import src.workflow.activities.build_property_graph as bpg

    assert not hasattr(bpg, "write_with_retry")
```

- [ ] **Step 2: Run to verify failure** — `uv run --extra dev pytest -q -p no:cacheprovider tests/test_graph/test_store.py tests/test_workflow/test_build_property_graph.py` → FAIL.

- [ ] **Step 3: Implement.** `src/graph/store.py` becomes:

```python
"""Graph store factory — NebulaGraph is the only backend."""

from __future__ import annotations

from src.graph.nebula_store import NebulaGraphStore, build_nebula_graph_store


def build_graph_store() -> NebulaGraphStore:
    """Return the process-global NebulaGraph store."""
    return build_nebula_graph_store()
```

Keep any other public name from the old `store.py` that callers import (`grep -rn "from src.graph.store import" src tests`); delete ones that are Neo4j-only and fix their callers. In activities replace `await asyncio.to_thread(write_with_retry, graph_store.upsert_nodes, entities)` with `await asyncio.to_thread(graph_store.upsert_nodes, entities)` (same for relations and `inject_canonical_entities`), and drop the comments about `Neo.TransientError`.

- [ ] **Step 4: Run** the two test files, then SUITE. Expected: green; gate holds.
- [ ] **Step 5: Commit**

```bash
git add -A src tests
git commit -m "refactor: nebula-only graph store; remove Neo4jSettings, GraphSettings, write_retry"
```

### Task 8: Scripts, eval, deps, env, docs

**Files:**
- Scripts (`scripts/`): for each of `wipe_db.py`, `check_ingestion.py`, `diag_kg_lightrag.py`, `backfill_report_vec_milvus.py`, `backfill_er_vec_milvus.py`, `backfill_er_vector.py`, `reresolve_graph.py`, `setup_wikibase.py`, `backfill_first_seen.py`, `make_env.py`, `start.sh`, `smoke_wikibase_push.py`, `merge_identifier_duplicates.py`, `setup_db.py`: if the script only serves Neo4j (reads/writes via Cypher or `neo4j` driver with no Nebula path — e.g. `backfill_er_vector.py` native-index backfill, Neo4j→Milvus backfills whose source is Neo4j), **delete** it; otherwise strip the Neo4j branch/args. `make_env.py`: remove `NEO4J_*`, `GRAPH_BACKEND`, `TEMPORAL_CENTRALITY_BACKEND`, `AGENT_ER_VECTOR_BACKEND`, `AGENT_COMMUNITY_VECTOR_BACKEND` entries.
- Eval (`tests/eval/`): delete Neo4j-only benches and parity scripts: `migration/parity_read.py`, `migration/parity_write.py`, `bench_community_backends.py` (gds vs leidenalg), `scale/bench_er_native.py`, `scale/bench_graph_write.py` if Neo4j-bound; strip Neo4j mentions from `graph_depth_probes.py`, `scale/bench_walk.py`, `scale/synth.py`, `scale/run_scale_bench.py`, `test_scale_bench_smoke.py`, both READMEs.
- Deps: `pyproject.toml` (remove `llama-index-graph-stores-neo4j`, `neo4j`), regenerate `uv.lock` (`uv lock`), `requirements.txt` if it lists them.
- Env: `.env.example`, `.env.prod.example`, `.env.reference`, `docker-compose.yml`, `docker-compose.prod.yml` — remove `NEO4J_*`, `GRAPH_BACKEND`, removed flags, and the "neo4j service was removed" comment.
- Living docs: `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`, `docs/QUICKSTART.md`, `docs/ANALYTICS-GUIDE.md`, `docs/runbook/mcp.md`, `docs/runbook/graph-analytics.md`, `docs/bruno/Admin/Rebuild Communities.bru` — describe Nebula only.

**Interfaces:** none produced.

- [ ] **Step 1: Apply** the edits/deletions above.
- [ ] **Step 2: Lock** — `uv lock` then `uv run --extra dev python -c "import importlib.util as u; assert u.find_spec('neo4j') is None"`. Expected: no AssertionError.
- [ ] **Step 3: Run** SUITE and `uv run --extra dev pytest -q -p no:cacheprovider tests/test_scripts`. Expected: gate holds (`test_make_env` may still fail only for the 4 pre-existing undocumented vars).
- [ ] **Step 4: Commit**

```bash
git add -A scripts tests/eval pyproject.toml uv.lock requirements.txt .env.example .env.prod.example .env.reference docker-compose.yml docker-compose.prod.yml docs/ARCHITECTURE.md docs/DEPLOYMENT.md docs/QUICKSTART.md docs/ANALYTICS-GUIDE.md docs/runbook docs/bruno
git commit -m "chore: remove neo4j from scripts, eval benches, deps, env templates and docs"
```

### Task 9: Guard test + comment sweep + final verification

**Files:**
- Create: `tests/test_no_neo4j.py`
- Modify: any `src/`/`scripts/` file whose comments/docstrings still mention Neo4j (e.g. `src/graph/entity_resolution.py` has ~21 docstring/comment mentions; `src/storage/wikibase.py` ~17).

- [ ] **Step 1: Write the guard test**

```python
"""Neo4j is gone for good: no mention in code, scripts or dependencies."""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "src", ROOT / "scripts"]
FILES = [ROOT / "pyproject.toml"]
NEEDLE = re.compile(r"neo4j", re.IGNORECASE)


def _hits():
    paths = [p for t in TARGETS for p in t.rglob("*") if p.is_file() and p.suffix in {".py", ".sh", ".toml", ".yml", ".yaml"}]
    paths += FILES
    return [
        f"{p.relative_to(ROOT)}:{i}"
        for p in paths
        for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1)
        if NEEDLE.search(line)
    ]


def test_no_neo4j_mentions():
    assert _hits() == []
```

- [ ] **Step 2: Run to verify it fails** — `uv run --extra dev pytest -q -p no:cacheprovider tests/test_no_neo4j.py` → FAIL listing remaining comment mentions.
- [ ] **Step 3: Sweep** each hit: rewrite comments to describe the Nebula behaviour, or drop comments that only contrasted with Neo4j. No code changes in this step — if a hit is code, it belongs to an earlier task: fix it and note it in the commit.
- [ ] **Step 4: Run** the guard, then SUITE. Expected: guard green; gate holds.
- [ ] **Step 5: Update graph + commit**

```bash
graphify update .
git add -A src scripts tests/test_no_neo4j.py graphify-out
git commit -m "test: guard against any neo4j reference; sweep remaining comments"
```

- [ ] **Step 6: Live verification (needs user go-ahead — deploy is outward-facing).** On .31: rebuild api + worker + mcp-search images from this branch, remove `NEO4J_*`/`GRAPH_BACKEND`/removed flags from the prod `.env`, then: one ingest completes; search local/global/drift/auto each return results; `POST` community-build completes; analytics-materialize completes; `kb_analyze` "что в трендах" returns rows. Compare with a pre-deploy run of the same queries. Run `tests/eval/` on default graph — no regression versus the last recorded eval.
