# Lens v2 — agent + board + simple web (design)

Date: 2026-09-28 · Status: design approved in chat, spec awaiting review ·
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

### Success criterion
On the local stack: type «ростатом» → the journal shows each step live → the board gets
a short set of relevant objects with typed relations and sources → a short answer note
with clickable `[[key]]` citations → «скрой X» and «отмени» work through the same input →
«стоп» interrupts a running request.

### Out of scope (v2)
Multi-user and sharing, watcher/monitoring, external sources beyond kb-*, tables/aggregates
on the board, strict board mode (ids only), memory across requests beyond the board itself.

## 2. Architecture

```
            ┌──────────── web (lens-web) ─────────────┐
            │ input + @mentions   board   journal     │
            └──┬───────────────────▲──────────▲───────┘
   POST /runs  │   board changes    │          │ agent stream
               │   (SSE, lens)      │          │ (SSE, lens-agent)
               ▼                    │          │
        ┌──────────────┐            │          │
        │  lens-agent  │────────────┼──────────┘
        │ PydanticAI   │            │
        └──┬────────┬──┘            │
  sources  │        │ board MCP     │
           ▼        ▼               │
   kb-search    ┌──────────────┐    │
   kb-tools     │ lens (board) │────┘
   kb-stats     │ op log, SSE  │
                └──────────────┘
```

Services in compose: `lens` (board, existing container), `lens-agent` (new), `lens-web`
(new, nginx). LLM calls go through the existing LiteLLM (aliases `small`/`large`).

## 3. Agent stream (lens-agent → web)

Transport:
1. `POST /runs {workspace_id, text, mentions}` → `{run_id}`; `409 busy` if the workspace
   already has a running run.
2. `GET /runs/{run_id}/events` → SSE. Every event is persisted; reconnect with
   `Last-Event-ID` replays what was missed. `: ping` every 15 s when idle.
3. `POST /runs/{run_id}/cancel` → the run ends with `done{status:"cancelled"}`.

Envelope of every event: `{run_id, seq, ts, type, ...}`; `seq` = SSE `id`.

| type | fields |
|---|---|
| `run_started` | `input {text, mentions}`, `model`, `mcp: [{name, status}]` |
| `thinking` | `delta` |
| `text` | `delta` |
| `tool_call` | `call_id`, `server`, `tool`, `args` |
| `tool_result` | `call_id`, `ok`, `duration_ms`, `summary {items, bytes, preview}`, `error?` |
| `final` | `answer`, `usage {requests, tokens_in, tokens_out}`, `duration_ms` |
| `error` | `where: model/tool/limit/internal`, `message` |
| `done` | `status: done/failed/cancelled` |

Not in the stream: full tool results (stored; `GET /runs/{id}/calls/{call_id}`) and board
changes (the web gets them from the board stream — one source of truth; the journal shows
board calls as ordinary `tool_call`s).

Mapping from PydanticAI (`run_stream_events`): `PartDeltaEvent`+`TextPartDelta` → `text`;
`ThinkingPartDelta` → `thinking`; `FunctionToolCallEvent` → `tool_call`;
`FunctionToolResultEvent` → `tool_result`; `AgentRunResultEvent` → `final`. The web never
sees library types, so the runtime can be replaced.

## 4. Board MCP (lens)

The agent service attaches the board MCP per run with headers `X-Workspace` and `X-Run`;
the agent cannot pick the workspace, and every change is tagged with the run.

| tool | args | returns |
|---|---|---|
| `get_board` | `limit=50`, `include_hidden=false` | objects `{key, type, label}`, relations, hidden, this run's mentions |
| `find_on_board` | `query` | matching `{key, label}` (word/stem match, as the old router) |
| `get_object` | `key` | type, label, description, attrs, sources |
| `add_objects` | `objects: [{id, type, label, description?, attrs?, source}]` | `{added, merged, keys, rejected: [{item, reason}]}` |
| `add_relations` | `relations: [{from, to, kind, source}]` (from/to = keys) | `{added, rejected}` |
| `add_note` | `text` with `[[key]]`, `cites` | `{key}`; unknown cites dropped |
| `hide` / `show` | `keys` | changed count |
| `merge` | `keep`, `drop` | surviving key |
| `undo` | `run="last"` | operations reverted |

Object: `{"id", "type", "label", "description"?, "attrs"?, "source": {"server", "tool", "call_id"}}`.
- Key = `namespace:id`; namespace from the source's MCP config (all `kb-*` → `kb`). Same
  key from different runs = same object (merged, not duplicated).
- Type from the vocabulary (person, organization, event, location, document, topic, ip,
  domain, certificate, service, asn, other); unknown → `other`.
- `source` is required; objects without it are rejected with a reason.

Board-enforced rules: a relation needs both ends on the board or in the same call; at
most 50 objects per call and 200 per run (error text tells the agent to pick the most
relevant). No pin/mode/delete for the agent (the web pins directly; only hide, nothing is
lost). Every change is an op in the investigation log — history, undo and the board SSE
work as today.

Reused from the current `src/lens`: op log, fold (merge/undo/hide), stores, board SSE,
word/stem matching. New: the MCP server, `source` on objects, per-run tagging, limits.
Router/Planner/Normalizer stay in the repo, off the main path.

## 5. Agent service (lens-agent)

- Python, FastAPI, PydanticAI v2; own container.
- API: `POST /runs`, `GET /runs/{id}/events`, `POST /runs/{id}/cancel`, `GET /runs/{id}`,
  `GET /runs/{id}/calls/{call_id}`, `GET /health` (model + MCP statuses). Auth: `X-API-Key`
  (`LENS_API_KEYS`); the stream takes a short-lived signed token (as the board does now).
- MCP servers from `.env` JSON: `[{name, url, namespace, token, role: source|board}]`.
  A new source = one more entry, no code. Connected at run start, closed at run end — no
  long-lived sessions (a restarted MCP server cannot leave a dead session). A server that
  is down is reported `down` in `run_started`; the agent works with the rest.
- Model: `LENS_AGENT_MODEL` (default `large`) through LiteLLM (OpenAI-compatible).
- Prompt (essence): 1) `get_board` first; 2) board commands (hide/show/undo/merge) only via
  board tools; 3) search the KB, neighbours 1 hop, no repeated identical calls; 4) put on the
  board only what answers the question, with source, type and relations, ~20 objects max;
  5) no facts that tools did not return; 6) finish with `add_note` (≤5 sentences, `[[key]]`)
  and the same answer as text, in the user's language.
- Limits (env): ≤8 source calls and ≤20 tool calls per run, ≤30 model requests, run timeout
  5 min, tool timeout 2 min. On a limit the agent is told to finish; the stream gets
  `error{where:"limit"}`.
- Errors: a tool error goes back to the model as text (it adapts) and shows red in the
  journal; a model error ends the run `failed`; «стоп» cancels (`cancelled`). Board changes
  already made stay (undo reverts them).
- One run per workspace at a time (`409 busy`).
- Persistence (Postgres, prefix `agent_`): `agent_run` (input, model, status, times, usage,
  error), `agent_event` (all stream events in order — replay/resume), `agent_call_payload`
  (full tool results).
- Each run is independent: context = current board + the new request.

## 6. Web (lens-web)

- `web/`: Vite + TypeScript + npm, lockfile committed, Node pinned. Shell in plain TS (no UI
  framework); React-based renderers mount inside their own element.
- Modules: `api/` (board REST+SSE, agent runs+SSE, shared SSE client with Last-Event-ID),
  `state/` (board state from ops by seq; current run journal), `render/` (`BoardRenderer`
  interface, `viewModel`, `vis.ts` adapter), `ui/` (input with @mentions and «стоп»,
  journal, notes, status, workspace picker), `main.ts`.
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
- Journal panel: one block per run; `→` tool call with short args, `←` result summary with
  «подробнее» (full payload), streamed text, final answer; thinking collapsed; errors red.
- Served by `lens-web` (nginx): static build + proxy `/board/* → lens`, `/agent/* →
  lens-agent` (one origin: no CORS issues, SSE works). `npm run dev` = Vite with the same
  proxy.
- Tests: vitest for DOM-free parts (SSE parsing/resume, applying board ops, @mentions,
  events → journal lines).
- Replaces the scratchpad debug page with the same look.

## 7. Risks

- **PydanticAI v2 vs pinned deps** (`openai`, `pydantic`, `fastmcp`) — check first; fall back
  to a compatible version or isolate in its container.
- **Weak local model** (9B) — tool discipline and relevance; mitigated by prompt, board
  limits and rejections with reasons; model choice in the models stage.
- **Agent writes values on the board** (v1) — mitigated by required `source` and the
  journal; strict mode (ids only) is a later stage.
- **KB data noise** (junk links in the graph) — separate track.

## 8. Testing

- Board service: unit tests for MCP tools (rules, limits, rejections, run tagging, undo of a
  run) over the memory store; existing fold/store tests stay.
- Agent service: PydanticAI test model with scripted tool calls + in-memory FastMCP sources +
  memory board; stream contract, limits, cancel, Last-Event-ID replay, errors.
- Web: vitest as above.
- Live: one agreed run «ростатом» end to end after integration (live checks only with the
  user's go-ahead).

## 9. Open questions

- Exact PydanticAI version after the compatibility check.
- Whether `thinking` from local models is worth showing (depends on the model).
