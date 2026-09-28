# Lens — roadmap (r3, 2026-09-28)

Spec: `docs/superpowers/specs/2026-09-28-lens-v2-design.md` (r2, approved).
Supersedes the agent/normalizer direction of `2026-09-22-lens-plan1-agent-core.md` (that code stays in `src/lens/`, parked).

## Architecture
- **Web** — looks like the current debug page, but a Vite + TypeScript project so npm packages can be added later. The board is drawn through a renderer interface (vis-network now → Cytoscape.js / tldraw / React Flow later). Modules: API + SSE client, input with `@mentions`, status, agent journal.
- **Agent service** — ready-made agent runtime (PydanticAI). `POST /runs` {workspace_id, text, mentions} → SSE stream of everything the agent does (text, tool calls + args, results, final answer, errors; board changes come from the board stream). Gets a list of MCP servers from config: `kb-search`, `kb-tools`, `kb-stats` + the board MCP. Models via LiteLLM. Board commands («скрой X», «отмени») also go through the agent.
- **Board service** — the existing Lens backend (op log, undo, history, SSE, provenance) exposed as an MCP server for the agent (`get_board`, `add_objects`, `add_relations`, `add_note`, `hide`/`show`, `merge`, `undo`…) plus HTTP/SSE for the web (pins go directly, not through the agent). Agent and web meet only here.
- Board writes v1: agent passes values + source reference; strict v2: agent passes ids only and the board fetches details (needs real ids in kb-tools).

## Stages
0. **Order & safety** — live checks only after the user's go-ahead; delete test workspaces; merge `feat/lens-normalizer-fixes`; decide on the local `docker/litellm_config.prod.yaml`.
1. **Spec & design** — rewrite the spec for this architecture; agent stream event format; board MCP tool set; web structure; implementation plan for stages 2–5.
2. **Board service** — MCP board server mounted in the Lens app (token + X-Workspace/X-Run), key normalization + merged_into, sources/description on objects, relation vocabulary, note canonicalization, undo excluding current run, limits; legacy /input disabled; HTTP/SSE kept.
3. **Agent service** — PydanticAI 1.28–1.30 (otel-api <1.44), MCP from config (per-run connections), SSE events, system prompt, per-kind budgets + soft/hard limits, result truncation, service-injected sources, deterministic note, cancel, run list/resume, persisted runs, tests with fake model/MCP.
4. **Web** — Vite + TS, same look, renderer interface + vis-network adapter, agent journal panel, compose service.
5. **Integration** — agent + board + web in compose; one approved live run «Росатом».
6. **Result quality** — object card (description, provenance, document quotes, actions); relevance and search-width limits; strict board mode with real ids in kb-tools.
7. **Models** — LM Studio with two models (small / large), Docker ~12 GB, latency; Yandex key fix or reissue as external fallback.
8. **KB data quality** (parallel) — why "Rosatom" links to junk in the graph (ingest vs ER); cleanup.
9. **Later** — richer renderer via the adapter, watcher («следи за X», «что нового»), external sources (FOFA), multi-user.

Order: 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7; 8 in parallel. Code starts only after the spec and plan are approved.
