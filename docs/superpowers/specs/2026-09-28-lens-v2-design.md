# Lens v2 — agent + board + simple web (design)

Date: 2026-09-28 · Status: approved (r2 after logic + feasibility review) ·
Supersedes: `2026-09-22-lens-workspace-design.md` (its board/op-log ideas carry over;
its own Planner/Normalizer/Router are parked).
Roadmap: `docs/superpowers/plans/2026-09-28-lens-roadmap.md`.

## 1. Goal

A visual research product: one input field, a board of objects and relations that grows
with each request, and a visible journal of what the agent did. The knowledge base
(kb-llamaindex) is the first source; any MCP server can become another.

### Principles
- **Ready-made agent, not our own orchestration.** An agent runtime receives the request
  and a list of MCP servers and does the task. We write configuration, a prompt and a thin
  HTTP layer.
- **The board is a separate service.** It keeps the investigation (state, history,
  undo) between requests. The agent changes it only through MCP; the web reads it.
- **Everything the agent does is visible** as a live stream (the agent journal).
- **Web is simple now, extensible later:** a real Vite + TypeScript project; the board is
  drawn through a replaceable renderer.
- **What the agent cannot be trusted with, the services enforce** (source attribution,
  limits, keys, the final note) — the model is weak (local 9B).

### Success criterion
On the local stack: type «ростатом» → the journal shows each step live → the board gets
a short set of relevant objects with typed relations and sources → a short answer note
with clickable `[[key]]` citations → «скрой X» and «отмени» work through the same input →
«стоп» interrupts a running request → reloading the page restores the board and the
running/last journal.

### Out of scope (v2)
Multi-user and sharing, watcher/monitoring, external sources beyond kb-*, tables/aggregates
on the board, strict board mode (ids only), memory across requests beyond the board itself.

## 2. Architecture

```
            ┌──────────── web (lens-web, nginx) ──────────┐
            │ input + @mentions   board   journal          │
            └──┬────────────────────▲──────────▲───────────┘
 /agent/runs   │  /board/… (SSE)     │          │ /agent/runs/{id}/events (SSE)
               ▼                     │          │
        ┌──────────────┐             │          │
        │  lens-agent  │─────────────┼──────────┘
        │ PydanticAI   │             │
        └──┬────────┬──┘             │
  sources  │        │ board MCP (token, internal network only)
           ▼        ▼                │
   kb-tools     ┌──────────────┐     │
   kb-stats     │ lens (board) │─────┘
   (kb-search   │ op log, SSE  │
    opt-in)     └──────────────┘
```

Services in compose: `lens` (board, existing container), `lens-agent` (new), `lens-web`
(new, nginx). LLM calls go through the existing LiteLLM (aliases `small`/`large`).
Only `lens-web` is published to the host; `lens` and `lens-agent` stay on the compose
network (the board MCP is not reachable from outside).

## 3. Input protocol (web)

- Text + `mentions` (board keys chosen by clicking objects) → `POST /agent/runs`.
- **«стоп»** (whole input, same word list as today's `is_stop`) is handled by the web: it
  calls `POST /agent/runs/{id}/cancel` for the running run; it is never sent to the agent.
- While a run is active the input is disabled except for «стоп». After `done` it re-enables.
- Board commands («скрой X», «отмени», «это одно и то же») are ordinary requests to the
  agent.
- Dragging an object pins it directly on the board service (no agent).
- On load/reload the web asks `GET /agent/runs?workspace_id=…` → the active run (resume its
  stream from the start) or the last runs (replay their journals).

## 4. Agent stream (lens-agent → web)

Transport:
1. `POST /runs {workspace_id, text, mentions}` → `{run_id, stream_token}`; `409 busy` if
   the workspace already has an active run.
2. `GET /runs/{run_id}/events?token=…` → SSE. Every event is persisted; reconnect with
   `Last-Event-ID` replays what was missed. `: ping` every 15 s when idle.
3. `POST /runs/{run_id}/cancel` → the run ends with `done{status:"cancelled"}`.
4. `GET /runs?workspace_id=…&limit=N` → active run (if any) + last N runs (id, input,
   status, times).

Envelope of every event: `{run_id, seq, ts, type, ...}`; `seq` = SSE `id`.

| type | fields |
|---|---|
| `run_started` | `input {text, mentions}`, `model`, `mcp: [{name, status}]` |
| `thinking` | `delta` |
| `text` | `delta` |
| `tool_call` | `call_id`, `server`, `tool`, `args` |
| `tool_result` | `call_id`, `ok`, `duration_ms`, `summary {items, bytes, preview}`, `truncated`, `error?` |
| `final` | `answer`, `usage {requests, tokens_in, tokens_out}`, `duration_ms` |
| `error` | `where: model/tool/limit/internal`, `message` |
| `done` | `status: done/failed/cancelled` |

- `thinking`/`text` deltas are coalesced before persisting (flush every ~250 ms or on the
  next non-text event), so a run is tens of rows, not thousands; the live stream is not
  delayed.
- Not in the stream: full tool results (stored; `GET /runs/{id}/calls/{call_id}`) and board
  changes (the web gets them from the board stream — one source of truth; the journal shows
  board calls as ordinary `tool_call`s).

Mapping from PydanticAI `run_stream_events`: `PartDeltaEvent`+`TextPartDelta` → `text`;
`ThinkingPartDelta` → `thinking`; `FunctionToolCallEvent.part{tool_name,args,tool_call_id}`
→ `tool_call` (`server` from the per-server `tool_prefix`); `FunctionToolResultEvent` →
`tool_result` (`ok=false` when the result is a `RetryPromptPart`); `AgentRunResultEvent` →
`final`. The web never sees library types, so the runtime can be replaced.

## 5. Board service (lens) and board MCP

### Board MCP
Mounted inside the existing Lens FastAPI app at `/mcp` (FastMCP `http_app`, verified to
coexist with the existing routes and to read request headers via `get_http_headers()`).
Requires a bearer token (`LENS_BOARD_MCP_TOKEN`) and the headers `X-Workspace`, `X-Run`
set by lens-agent per run; the agent cannot pick the workspace.

| tool | args | returns |
|---|---|---|
| `get_board` | `limit=50`, `include_hidden=false` | objects `{key, type, label}` (most recently touched first, pinned and this run's objects always included), relations among them, hidden keys |
| `find_on_board` | `query` | matching `{key, label}` (normalized word/stem match, as the old router) |
| `get_object` | `key` | type, label, description, attrs, sources |
| `add_objects` | `objects: [{id, type, label, description?, attrs?, call_id}]` | `{added, merged: [{id, merged_into}], keys, rejected: [{item, reason}]}` |
| `add_relations` | `relations: [{from, to, kind, call_id}]` (from/to = keys) | `{added, rejected}` |
| `add_note` | `text` with `[[key]]` | `{key}` |
| `hide` / `show` | `keys` | changed count |
| `merge` | `keep`, `drop` | surviving key |
| `undo` | — | operations reverted (the last run **other than the current one**) |

### Keys, types, sources
- **Key** = `namespace:normalized_id`; normalization: casefold, `ё→е`, collapsed whitespace,
  stripped quotes. Before adding, the board also checks `find_on_board` for an exact
  normalized-label match of the same type and reports `merged_into` instead of creating a
  near-duplicate. Same key = same object (merged, not duplicated).
- **Type** from the vocabulary (person, organization, event, location, document, topic, ip,
  domain, certificate, service, asn, other); unknown → `other`. A merge never silently
  changes type: if types differ, the object keeps its type and the new type is recorded as
  an attribute conflict (`attrs.types_seen`).
- **Description** keeps the latest non-empty value; previous values stay in the op log.
- **Relation kind** from a small vocabulary (участник, связан, владеет, входит_в, работает_в,
  место, упоминает, related) plus free text mapped to `related` with the original in `attrs`.
- **Source** is NOT written by the model. The model passes only `call_id` of the tool call
  that produced the item; **lens-agent intercepts every board-tool call**
  (`process_tool_call`), verifies `call_id` against the run's own call registry and injects
  `source {server, tool, call_id, run_id, namespace}` before forwarding to the board. An
  unknown `call_id` is rejected back to the model with a reason. The namespace comes from
  the source's MCP config.

### Board rules
- A relation needs both ends on the board (add objects first).
- At most 50 objects per `add_objects` call and 200 per run; over the limit the reply tells
  the agent to pick the most relevant.
- `add_note`: every `[[key]]` is canonicalized through merge aliases and a fuzzy label match;
  unresolved markers become plain text (no broken links). One note per run: a later
  `add_note` in the same run replaces it.
- `undo` reverts the last completed run other than the current `X-Run`; a run that performed
  `undo` gets no note on the board.
- Every change is an op in the investigation log tagged with `run_id` — history, undo and the
  board SSE work as today. Agent: no pin/mode/delete (only hide — nothing is lost).

### Data model changes
- `ObjectEl` gains `description: str | None` and `sources: [{server, tool, call_id, run_id,
  namespace}]` (replaces `refs` for new ops); relations gain `sources`.
- `Op` rows carry `run_id` (the existing `input_id` column is reused for it).
- Fold stays backward compatible: old ops without `description/sources` fold as before.
- `state_to_dict` also returns merge aliases so the web can resolve old citations.

### Legacy path
The old `POST /workspaces/{id}/input` (Router/Planner/Normalizer) and its MCP hub are
disabled by default (`LENS_LEGACY_INPUT=false`); the board service no longer starts the MCP
hub. The code stays in the repo. Existing `lens_*` data (the «Демо» and «Росатом»
workspaces) remains readable.

## 6. Agent service (lens-agent)

- Python, FastAPI, **PydanticAI `pydantic-ai-slim[openai,mcp]>=1.28,<1.31`** (2.x needs
  `openai>=2.29`, incompatible with our `openai<2`; this window resolves with zero changes to
  openai/fastmcp/mcp/pydantic). **Pin `opentelemetry-api>=1.28,<1.44`**: pydantic-ai ≤1.34
  imports a module removed in otel-api 1.44. Own container, same repo image.
- Model: `LENS_AGENT_MODEL` (default `large`) via `LiteLLMProvider`/OpenAI-compatible
  provider pointing at LiteLLM.
- API (§4) + `GET /runs/{id}`, `GET /runs/{id}/calls/{call_id}`, `GET /health` (model + MCP
  statuses).
- **MCP config** (`LENS_AGENT_MCP` JSON in `.env`): `[{name, url, namespace, token, role:
  source|board, enabled}]`. A new source = one more entry, no code. Default sources:
  `kb-tools`, `kb-stats`; `kb-search` is `enabled=false` by default (it runs its own
  LLM synthesis against the same model and blows the time budget); when enabled, called
  without synthesis. Each server gets `tool_prefix = name`.
- **Per-run connections:** all MCP servers are connected at run start and closed at run end
  — no long-lived sessions (a restarted MCP server cannot leave a dead session). A server
  that is down is reported `down` in `run_started`; the agent works with the rest.
- **Result truncation:** `process_tool_call` cuts every source result to
  `LENS_AGENT_RESULT_CHARS` (default 4000) before it reaches the model, with a trailer
  «…усечено, полный результат: call_id=…»; the full result is stored. LM Studio context
  length is set explicitly (documented in the local LiteLLM config notes, ≥16k).
- **Prompt** (essence): 1) `get_board` first; @mentions (keys + labels) are given in the
  prompt; 2) board commands only via board tools, no KB calls; 3) search the KB, neighbours
  1 hop, no repeated identical calls; 4) put on the board only what answers the question,
  with `call_id`, type and relations, ~20 objects max; 5) no facts that tools did not return;
  6) finish with a short answer (≤5 sentences, `[[key]]` for objects on the board) in the
  user's language.
- **The note is deterministic:** when the run ends with a final answer (and did not undo),
  lens-agent itself writes it to the board via `add_note` if the model did not. The answer
  also goes out as `final`.
- **Budgets and limits** (env, defaults tuned later by measurement):
  - separate counters: source calls ≤8, board calls ≤20; identical repeated call (same tool +
    args) is answered from the run cache without hitting the server and not counted twice;
  - soft limit: when a budget is reached, further calls of that kind return «лимит
    исчерпан — завершай с тем, что есть» (the model can still answer);
  - hard limit: `UsageLimits(request_limit=30)` and run timeout `LENS_AGENT_RUN_TIMEOUT_S`
    (default 600 for a local 9B), tool timeout 120 s; on a hard limit the run ends `failed`
    with `error{where:"limit"}` — whatever is already on the board stays.
- **Errors:** a tool error goes back to the model as text (it adapts) and shows red in the
  journal; a model error ends the run `failed`; «стоп» cancels (`cancelled`). Cancellation
  of `run_stream_events` stops tool calls; the background task logs `BrokenResourceError` —
  expected, suppressed in our logging.
- **Concurrency:** one active run per workspace, stored in the DB (`agent_run.status =
  running` + heartbeat); on service start, runs left `running` are marked `failed`
  («прервано перезапуском»); a stale heartbeat (>2× run timeout) frees the workspace.
- **Auth:** `X-API-Key` (`LENS_API_KEYS`, same keys as the board) for REST; the SSE stream uses
  the `stream_token` returned by `POST /runs` (HMAC, bound to the run, 5 min, shared secret
  `LENS_STREAM_SECRET` with the board). The browser keeps the key in page settings (as now);
  nginx forwards it unchanged.
- **Persistence** (Postgres, prefix `agent_`, idempotent `CREATE IF NOT EXISTS` like the
  board): `agent_run` (input, mentions, model, status, heartbeat, times, usage, error),
  `agent_event` (coalesced stream events), `agent_call_payload` (full tool results). Retention:
  events and payloads older than `LENS_AGENT_RETENTION_DAYS` (default 30) are deleted by a
  daily cleanup in the service.
- Each run is independent: context = current board + mentions + the new request.

## 7. Web (lens-web)

- `web/`: Vite + TypeScript + npm, lockfile committed, Node pinned. Shell in plain TS (no UI
  framework); React-based renderers mount inside their own element.
- Modules: `api/` (board REST+SSE, agent runs+SSE, shared SSE client with Last-Event-ID),
  `state/` (board state; current and past run journals), `render/` (`BoardRenderer`
  interface, `viewModel`, `vis.ts` adapter), `ui/` (input with @mentions and «стоп»,
  journal, notes, status, workspace picker), `main.ts`.
- Board state: initial `GET` + apply `add_*`/`hide`/`show`/`pin` ops by seq; on `undo` or
  `merge` ops (or a seq gap / `resync`) the web re-fetches the whole board instead of
  re-implementing fold in TS.
- Renderer interface:
  ```ts
  interface BoardRenderer {
    mount(el: HTMLElement): void;
    render(view: BoardView): void;
    focus(key: string): void;
    on(ev: "select" | "dragEnd" | "open", cb: (key: string, pos?: Point) => void): void;
    destroy(): void;
  }
  ```
  Now vis-network; later cytoscape/tldraw/React Flow adapters swap in one line of `main.ts`.
- Journal panel: one block per run; `→` tool call with short args, `←` result summary (and
  «усечено» mark) with «подробнее» (full payload), streamed text, final answer; thinking
  collapsed; errors red.
- Served by `lens-web` (nginx): static build + proxy `/board/* → lens`, `/agent/* →
  lens-agent`. SSE locations: `proxy_buffering off`, `proxy_http_version 1.1`,
  `proxy_set_header Connection ""`, `proxy_read_timeout` ≥ run timeout + 60 s; the apps send
  `X-Accel-Buffering: no`. `npm run dev` = Vite with the same proxy.
- Tests: vitest for DOM-free parts (SSE parsing/resume, applying board ops, @mentions,
  events → journal lines, input protocol incl. «стоп»).
- Replaces the scratchpad debug page with the same look.

## 8. Compose

- `lens` and `lens-agent` get HTTP healthchecks (`/lens/v1/health`, `/health`);
  `lens-agent` depends on `lens: service_healthy`, `lens-web` on both.
- Only `lens-web` publishes a port. MCP config and tokens come from `.env` (secrets are
  visible in `docker inspect` — acceptable on the dev machine; noted).

## 9. Risks

- **Weak local model** (9B): tool discipline and relevance — mitigated by per-kind budgets,
  soft limits, rejections with reasons, deterministic note, result truncation; model choice
  in the models stage.
- **Time budget** on a local 9B: defaults (600 s run) to be tuned by measurement.
- **Agent writes labels/descriptions on the board** (v1): values still come from the model;
  mitigated by service-injected sources and the journal; strict mode (ids only) is a later
  stage.
- **Dependency window**: pydantic-ai stays on 1.28–1.30 until the repo moves to `openai>=2`.
- **KB data noise** (junk links in the graph) — separate track.

## 10. Testing

- Board service: unit tests for MCP tools (header/token checks, key normalization and
  `merged_into`, type conflicts, relation vocabulary, limits and rejections, note
  canonicalization, run tagging, undo excluding the current run), plus the FastMCP mount with
  headers (lifespan run explicitly in tests); existing fold/store tests stay.
- Agent service: PydanticAI `FunctionModel`/`TestModel` with scripted tool calls + in-memory
  FastMCP sources + memory board; stream contract, coalescing, truncation, source injection
  and unknown `call_id`, budgets (soft/hard), deterministic note, cancel, restart recovery,
  `Last-Event-ID` replay, errors.
- Web: vitest as above.
- Live: one agreed run «ростатом» end to end after integration (live checks only with the
  user's go-ahead).

## 11. Open questions

- Whether `thinking` from local models is worth showing (depends on the model).
- Default budgets/timeouts after the first measurements.
