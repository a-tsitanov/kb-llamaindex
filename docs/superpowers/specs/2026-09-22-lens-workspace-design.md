# Lens — object-centric research workspace (design)

Date: 2026-09-22 · Status: design approved; revision 2 after adversarial review (see §9) · Working name: Lens

## 1. Goal

A web workspace for searching and exploring information with focus on **objects**
(persons, organizations, events, places, documents, technical objects: IP, domain,
certificate…). One input field, one dynamic canvas that grows with each query.

Today it runs on top of kb-llamaindex; later kb-llamaindex is just one of the
pluggable sources. **Every source is an MCP server.**

### Users and scenarios
- **A. Investigation** — long-lived workspaces, dozens of queries, hundreds of
  objects; provenance of every fact is mandatory.
- **C. Monitoring** — built into investigations: "watch X" → on return, see what
  appeared since last visit.
- Multi-user (own workspaces + share) is **designed into the schema, not implemented**.

### Success criterion (MVP)
On real data complete: "встречи Путина в Китае" → expand a participant →
"@A @B как связаны" → save workspace → next day see what is new.

## 2. UX principles

- **Minimal interface.** Only the canvas and an input field at the bottom. No side
  panels, drawers, or menus.
- **All interaction through the input.** Search, pivots, and workspace commands
  ("скрой Си", "IP таблицей, только 22 и 3389", "следи за Росатомом", "что нового",
  "отмени", "открой Росатом/Китай") are typed.
- The only mouse actions: **click object = insert `@object` into the input**, drag
  to reposition (pins it).
- Selected `@objects` are context for the next query ("@Росатом @cert 9f3a как связаны").
- Results (tables, answers, details) appear **on the canvas next to related objects**.
- Each object appears **once**; objects from different queries merge by key, so
  query overlaps become visible.
- Technical bulk data (e.g. 212 IPs) is shown as a collapsed **aggregate** node;
  "…таблицей" expands it to a table node; rows can be pulled onto the canvas.
- Pivots (IP → domains → cert → hosts) are ordinary queries.
- Status line under input: connected MCP servers + current tool call.
- Monitoring surface: a small "с прошлого визита: +N" pill at the top and green
  dots on new objects.

Mockups: `.superpowers/brainstorm/*/content/workspace-min.html` (approved direction),
`architecture.html`.

## 3. Architecture

```
Browser (React)  ⇄  POST /workspaces/{id}/input, SSE /workspaces/{id}/stream
      ⇅
Agent service (Python, FastAPI, MCP Python SDK)
  Router · Planner · Normalizer · Validator · Workspace · Watcher
      ⇅                                   ⇅
Postgres (workspaces, ops, tool_calls,    MCP servers over streamable HTTP/SSE:
spec_cache, watches)                      kb-search, kb-tools, fofa, whois, …
      LLM via existing LiteLLM proxy
```

The agent runs **server-side**: MCP secrets stay on the server, watches run with
the tab closed, and future permissions are enforced server-side.

### Components
- **Router** — rule-based: workspace command (matched against the WHOLE input, words
  matched by stem) | everything else → Planner. Commands compile directly to ops
  without MCP/LLM. Questions about the current canvas go to the Planner, which gets a
  canvas summary (most recent objects first, with keys) and may answer without tools.
  "стоп" cancels the running input.
- **Planner** — tool-use loop over the merged tool catalog of all configured MCP
  servers. Each call's status is streamed immediately.
- **Normalizer** (approach "A with view-spec") — the LLM interprets heterogeneous
  MCP output and emits a **view-spec that references paths in the raw payload**;
  it never rewrites values. Cached by `(server, tool, shape_hash + model + prompt
  version)`; cache hits skip the LLM. Empty results skip the LLM entirely. Any LLM
  failure degrades to a `raw` node — normalization never fails the input.
- **Validator** — every path must exist and every type must come from the
  vocabulary. On failure: one repair attempt, then render a `raw` JSON node
  (honest fallback).
- **Workspace** — applies ops, appends to the op log, streams patches.
- **Watcher** — re-runs saved tool calls on schedule, diffs normalized object keys,
  records new keys.

### Per-input loop
1. Input text + mentions (with source keys) + compact canvas summary.
2. Router: command → ops → done. Search/question → Planner.
3. Planner calls tools step by step; each response is stored whole in `tool_call`.
4. Normalizer: spec from cache, else LLM gets schema + sample → view-spec.
5. Validator checks the spec.
6. Merge: same `namespace:id` key → same object. A **namespace** is the id space of a
   source (all KB MCP servers share `kb`), so one entity from two KB servers is one
   object. Relations may attach new objects to objects already on the canvas and to
   @mentions (spec paths `$root…` / `$args…` reach outside the current item).
   Cross-namespace matches (same type + normalized label) become `same_as?` candidate
   relations (dashed), confirmed by input ("да, это одно"). MVP proposes them
   deterministically; LLM-proposed candidates are a later improvement.
7. Ops `add_objects / add_relations / add_view / add_note` → log → SSE patches.
8. Short answer `note` next to objects; the LLM marks each mentioned object as
   `[[namespace:id]]`; markers naming non-existent elements are dropped; the note also
   lists the tool calls behind it.

### View-spec example
Rules are generic (reusable across calls of the same shape) — paths only, no values:
```json
{"objects":[{"name":"event","each":"$.events[*]","id":"$.id","label":"$.title",
             "type":"event","attrs":{"date":"$.date"}},
            {"name":"person","each":"$.events[*].participants[*]","id":"$.qid",
             "label":"$.name","type":"person"}],
 "relations":[{"each":"$.events[*]","from_id":"$.id","to_each":"$.participants[*]",
               "to_id":"$.qid","kind":"участник"},
              {"each":"$.neighbours[*]","from_id":"$args.entity_id","to_id":"$.id",
               "kind":"связан"}]}
```
A rule producing more than 25 unique objects becomes one **aggregate** ("IP · 212")
whose rows are read from the stored payload by path.

## 4. Data model

```
workspace      id, title, owner_id, created_at            -- owner_id reserved
ws_member      workspace_id, user_id, role                -- reserved, unused in MVP
input          id, workspace_id, text, mentions[], status, created_at
op             id, workspace_id, seq, kind, payload jsonb, input_id, created_at
workspace_snapshot  workspace_id, seq, state jsonb        -- load acceleration
tool_call      id, input_id, server, namespace, tool, args jsonb, payload jsonb, shape_hash,
               status, latency_ms, created_at
spec_cache     server, tool, shape_hash, spec jsonb, hits, model, created_at
watch          id, workspace_id, server, tool, args, cron, last_run, last_keys[]
watch_hit      watch_id, run_at, new_keys[], seen_at
```

Canvas state = fold of `op` by `seq` (+ latest snapshot).
Op kinds: `add_objects, add_relations, add_view, add_note, hide, show, pin,
set_mode, merge, watch, unwatch, undo`.

`shape_hash` = hash of response structure (keys + types, no values).

Canvas elements (inside `op.payload`):
```
object     key="namespace:id", type, label, attrs{}, refs[]
relation   from_key, to_key, kind, confidence, refs[]    -- kind "same_as?" = candidate
aggregate  key, label, count, rows_ref, columns[], refs[]
table      key, source_key, rows_ref, columns[], filter{col|"*": [values]}
note       text, cites[] (object keys), calls[] (tool call ids)
raw        call_id
```
`ref = {call_id, path}`. Large row sets are never copied into the log; the renderer
resolves `rows_ref` against `tool_call.payload`.

Monitoring "+N" = `watch_hit.new_keys` with `seen_at IS NULL`.

## 5. MVP scope

In:
1. Input with `@object` via click, ↑ history.
2. Router, Planner, Normalizer + spec cache, Validator + raw fallback.
3. MCP servers: `kb-search`, `kb-tools`; FOFA as the second, heterogeneous source
   if an MCP exists or takes ≤1 day, otherwise immediately after MVP.
4. Canvas elements: object, relation, aggregate, table, note, raw. Modes: canvas, table.
5. Commands: hide/show, pin, as table, undo, watch, what's new, open workspace.
6. Watcher with simple schedule; "+N" pill; new-object dots.
7. Workspace save/list, opened via input.
8. Normalizer benchmark: 30 real MCP responses with golden specs; metrics:
   valid-path rate, correct-type rate.

Out (reserved in schema): multi-user and sharing; timeline/map/graph modes;
automatic cross-source entity resolution (only `same_as?` candidates); export;
MCP server management UI (config file in MVP).

## 6. Risks

- **Local model quality** for tool-use + structured output (gemma4:12b may be weak).
  Model configurable per role (Router cheap; Planner/Normalizer strong); choose via
  the benchmark before committing.
- **Latency** of 3–4 tool calls with LLM steps (10–30 s) → stream everything
  incrementally.
- **Cross-source identity** — candidates only, never auto-merge.
- **Auto-layout quality** with hundreds of nodes — aggregates keep node count
  low; pins preserve user placement.

## 7. Testing

- Unit: Router classification on a fixed command set (incl. command words inside
  real queries and Russian declensions); Validator path checks;
  op-log fold; shape_hash stability; watch diff.
- Normalizer benchmark (see MVP #8) as a gated eval in `tests/eval/`.
- Integration: agent loop against recorded MCP responses (no live LLM in CI;
  recorded LLM outputs).
- E2E manual: the success-criterion scenario on the live stack.

## 8. API, auth, streaming

- Lens has its own keys (`LENS_API_KEYS`), never the main KB `API_KEYS`.
- The SSE stream authenticates with a signed, workspace-bound, 5-minute token
  (`POST /workspaces/{id}/stream_token`) — no long-lived key in URLs.
- SSE client protocol: wait for `ready` → load state (`last_seq`) → apply `ops` by
  seq → fill gaps via `GET /workspaces/{id}/ops?after_seq` → on `resync` reconnect.
- MCP servers reconnect lazily (not up at boot, restarted mid-session); each tool
  call has a timeout; a dead server never blocks the others.
- Dragging (pin) never waits for a running search.

## 9. Revision log

- **r2 (2026-09-22, adversarial review):** namespaces instead of server names in
  keys; `$root`/`$args` spec scopes + relations to canvas objects/@mentions; dedup
  before aggregation; full LLM sample when it fits; empty-result and LLM-failure
  handling in the Normalizer; cache key includes model + prompt version; whole-input
  command matching with stems, `стоп`, `открой`, table filter; MCP reconnect/timeout;
  pin outside the input lock; SSE `ready`/`resync` + `ops?after_seq`; own API keys +
  stream tokens; deterministic `same_as?`; per-object `[[key]]` citations.

## 10. Open questions

- Frontend canvas library (React Flow vs. custom) and layout engine (elkjs vs. force).
- Where the service lives long-term (this repo vs. separate repo) once it becomes
  multi-source.
- FOFA MCP: existing server or write one.
