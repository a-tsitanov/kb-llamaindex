# Lens extraction from kb-llamaindex — plan

Status: approved (2026-10-08). Goal: (1) land the backend work of the Lens track in
kb-llamaindex, (2) move Lens (board service, agent service, web) into its own project that
talks to the KB only over MCP.

## 0. Facts this plan rests on (checked 2026-10-08)

- Branch `a-tsitanov/lens-fixes`: 43 local commits on top of an older main, nothing
  uncommitted (only `web/vite.dev.local.mjs`, a dev-server config, untracked). Local `main`
  has moved on since (offline-cluster merge `1d69774`), so landing it is a merge, not a
  fast-forward.
- The branch mixes two kinds of work:
  - **KB backend** (stays in kb-llamaindex): name resolver and `entity_alias` schema
    (R1–R4), backfill script, kb-tools ranking / reranker fixes, `resolve_names`,
    `relations_between`, one-hop clamps, Dockerfile uv timeout;
  - **Lens** (moves out): board write gate, rows / view / redirect, answer gate, final mode,
    budgets, web redesign.
  - Some commits touch both (e.g. `cab07d7` relation check = kb-tools tool + lens-agent hook,
    `1a968b1` resolve_names + runner). After the merge both halves live in main; the split
    is done by path, not by commit.
- Lens depends on kb-llamaindex code in only three places:
  - `src.config.settings.litellm` (base_url, api_key, timeout_s, max_retries, model_large);
  - `src.storage.pg_pool` (async Postgres pool);
  - `src.utils.names.norm_name` (board keys).
  Everything else is MCP over HTTP (kb-tools, kb-stats, board).
- Lens state lives in the KB Postgres database: tables `lens_workspace`, `lens_ws_member`,
  `lens_input`, `lens_op`, `lens_tool_call`, `lens_spec_cache`, `agent_run`, `agent_event`,
  `agent_call_payload`.
- `src/lens` still carries the old router/planner input path (`agent.py`, `planner.py`,
  `normalizer.py`, `router.py`, `shape.py`, `spec.py`, `mcp_hub.py`, `llm.py`, `paths.py`),
  disabled by `LENS_LEGACY_INPUT=false`.
- Images: `lens` and `lens-agent` are built from the shared KB app image (~4 GB with torch
  and the reranker); `lens-web` has its own small Dockerfile. Third-party imports of Lens:
  fastapi, fastmcp/mcp, pydantic, pydantic-ai, pydantic-settings, psycopg(+pool), loguru,
  openai (legacy path only).
- Running containers `mcp-tools` and `lens-agent` carry code copied in by hand (the image
  build failed on a slow link); images must be rebuilt from main.
- `git filter-repo` is installed (keeps the history of the moved paths).

## 1. Step 1 — land the backend work in kb-llamaindex (local only, no push)

1. Merge `a-tsitanov/lens-fixes` into local `main` (merge commit). Expected conflicts:
   `docker-compose.prod.yml` (lens-agent env, kb-tools MCP entry), possibly
   `src/mcp/tools_server.py` / `Dockerfile` if main touched them.
2. Run the suites on the merged tree: `tests/test_lens*`, `test_retrieval`, `test_mcp`,
   `test_graph/test_name_resolution`, `test_storage`, `test_utils`, `test_scripts`, web
   vitest. Known order-dependent failures (search/stats server, llm_factory → workflow,
   make_env BOT_* vars) are pre-existing and listed, not fixed here.
3. Tag `lens-split-base` on the merge commit — the point both projects start from.
4. Rebuild `mcp-tools` and `worker` images from main when the network allows (replaces the
   hand-copied code). Clean up `docker/litellm_config.local.yaml.*.bak` (gitignored dir).

Acceptance: main contains both halves, suites green except the known flakes, tag exists.

## 2. Step 2 — new project

### 2.1 Shape of the new repo (proposed name: `lens`)

```
lens/
  pyproject.toml          uv, slim deps (no torch, no llama-index)
  Dockerfile              python:3.12-slim, one image for both services
  docker-compose.yml      postgres (own) + lens + lens-agent + lens-web
  .env.example            LENS_*, LITELLM_*, LENS_PG_DSN, MCP source URLs/tokens
  src/lens/               board service (+ board MCP)
  src/lens_agent/         agent service
  src/lens_common/        names.py (norm_name), pg.py (pool), llm settings
  web/                    Vite/TS web (unchanged layout)
  tests/test_lens, tests/test_lens_agent, tests/fixtures/lens_eval
  docs/                   lens v2 spec, design notes, this plan's follow-ups
```

Package paths stay `src/lens` and `src/lens_agent` in the first cut — no import churn; a
rename can come later as its own change.

### 2.2 Phases

**P1. Extract with history.** Clone kb-llamaindex at `lens-split-base` into a scratch dir;
`git filter-repo` keeping `src/lens`, `src/lens_agent`, `web`, `tests/test_lens`,
`tests/test_lens_agent`, `tests/fixtures/lens_eval`, the Lens specs/plans under `docs/`.
Result: a repo with only Lens files and their history. Acceptance: `git log` shows the Lens
commits; no KB code inside.

**P2. Cut the three dependencies.**
- `src.config.settings.litellm` → `lens_common.settings` (pydantic-settings: `LITELLM_BASE_URL`,
  `LITELLM_API_KEY`, `LITELLM_TIMEOUT_S`, `LITELLM_MAX_RETRIES`, model alias).
- `src.storage.pg_pool` → `lens_common.pg` (psycopg_pool, `LENS_PG_DSN`).
- `src.utils.names.norm_name` → `lens_common.names` copied verbatim, plus a contract test
  with fixed inputs → outputs (board keys must never change; the KB keeps its own copy for
  the resolver; both are pinned by the same fixture list).
Acceptance: `grep -r "from src\.\(config\|storage\|utils\)"` is empty; Lens suites green.

**P3. Drop the legacy input path.** Remove `agent.py`, `planner.py`, `normalizer.py`,
`router.py`, `shape.py`, `spec.py`, `mcp_hub.py`, `llm.py`, `paths.py` and their tests, the
`LENS_LEGACY_*` settings and the `lens_spec_cache` table use. Acceptance: suites green,
`openai` no longer a dependency.

**P4. Project scaffolding.** `pyproject.toml` (uv lock), slim `Dockerfile` (target < 400 MB,
build in minutes, no torch), `docker-compose.yml` with its own Postgres, `.env.example`,
Makefile (`test`, `lint`, `up`), ruff config, README (how to run against a KB).
MCP sources and LiteLLM are plain URLs in config, so the project runs against any KB:
locally by joining the KB compose network (`agent_v2_default`) or by host ports.
Acceptance: `docker compose up` brings the three services; health endpoints green against
the running KB stack.

**P5. Data.** Move the Lens tables from the KB database to the new Postgres:
`pg_dump -t 'lens_*' -t 'agent_*'` → restore (workspaces, op logs, run journals kept).
Alternative: start empty (test workspaces only). Acceptance: existing workspaces open with
their boards and journals.

**P6. Cutover.** Stop `lens`, `lens-agent`, `lens-web` in the KB compose; start the new
project on the same ports (:8010 web). Re-run the 3 loc_test prompts on the same model.
Acceptance: same behaviour as before the move.

**P7. Remove Lens from kb-llamaindex** (only after P6 is verified): delete `src/lens*`,
`web/`, Lens tests and fixtures, the three compose services, `LENS_*` env in compose; drop
the Lens tables from the KB DB after the copy is verified. Keep in kb-llamaindex what the KB
owns: resolver, `entity_alias`, kb-tools tools (`resolve_names`, `relations_between`,
resolution block, rows format). Acceptance: KB suites green, KB images no longer contain
Lens.

### 2.3 The contract between the projects

The only coupling left is the kb-tools MCP surface Lens relies on:
- `resolution` block on name-taking tools; `entities` / `relations` row shapes
  (`entity_name`, `entity_type`, `src_id`, `tgt_id`, `label`, `relevance`, `match`);
- hidden helpers `resolve_names(text)` and `relations_between(a, b)`;
- `centre_found`, `relevance_note`, `rank_timeout`, `depth_note`, `types_inferred` meta.
Document it in kb-llamaindex (`docs/mcp/kb-tools-contract.md`) and pin it in Lens with
recorded payloads (`tests/fixtures/lens_eval` already does this for rows); a contract
change is a versioned change on the KB side.

## 3. Risks

- **norm_name drift**: two copies — mitigated by the shared fixture contract test.
- **Merge conflicts in step 1**: compose and tools_server are the hot spots; resolved by
  hand, then the full suites.
- **Hand-copied container code**: until images are rebuilt from main, a container recreate
  loses the latest Lens/kb-tools code — rebuild first (step 1.4), before the cutover.
- **Secrets**: `LENS_API_KEYS`, `LENS_BOARD_MCP_TOKEN`, `LENS_MCP_TOKEN` move to the new
  project's `.env` (gitignored); the KB keeps `API_KEYS` for its MCP servers.
- **No remote yet**: the new repo stays local until you decide where it lives; nothing is
  pushed anywhere without an explicit "push".

## 4. Decisions (2026-10-08)

1. Project `lens` in `~/projects/lens`.
2. History kept: `git filter-repo` from the `lens-split-base` tag.
3. Existing workspaces, boards and run journals are moved (`lens_*`, `agent_*` tables).
4. The new project has its own Postgres in its own compose; it reaches the KB only through
   MCP and LiteLLM URLs.
