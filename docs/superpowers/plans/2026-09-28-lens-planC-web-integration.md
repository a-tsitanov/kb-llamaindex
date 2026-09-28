# Lens v2 — Plan C: Web and Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A simple web product (one input, a board, a journal of what the agent does) as a real Vite + TypeScript project with a swappable renderer, wired to the board and agent services through one nginx front door, plus the compose services and the first live run.

**Architecture:** `web/` is plain TypeScript (no UI framework). Pure modules carry the logic and are unit-tested with vitest: SSE client with `Last-Event-ID` and a fresh token per reconnect (`api/sse.ts`), board ops application (`state/board.ts`), run events → journal (`state/journal.ts`), input protocol with «стоп» (`state/input.ts`), board → renderer view (`render/viewModel.ts`). The board engine sits behind `BoardRenderer` (`render/types.ts`); `render/vis.ts` is the vis-network adapter. nginx serves the build and proxies `/board/* → lens` and `/agent/* → lens-agent`; only `lens-web` is published.

**Tech Stack:** Node 22, npm, Vite 6, TypeScript 5.9, vitest 3, vis-network 10 / vis-data 8; nginx 1.27; docker compose.

**Spec:** `docs/superpowers/specs/2026-09-28-lens-v2-design.md` (r2) — §3 input protocol, §7 web, §8 compose, §10 testing. Roadmap stages 4–5. **Depends on Plans A and B** being executed.

## Global Constraints

- Node 22 (`web/.nvmrc`, `engines`), exact versions (`--save-exact`), `package-lock.json` committed; `npm audit --omit=dev` must report 0 vulnerabilities.
- Runtime deps exactly: `vis-network@10.1.2 vis-data@8.0.5 vis-util@6.0.2 uuid@14.0.2 keycharm@0.4.0 component-emitter@2.0.0 @egjs/hammerjs@2.0.17`; dev: `typescript@5.9.3 vite@6.4.3 vitest@3.2.7 @types/node@22`. (vis-network 9.x pulls a vulnerable `uuid`.)
- Web checks: `cd web && npx vitest run && npm run build` (build = `tsc --noEmit` + `vite build`). Python checks: `uv run --frozen pytest tests/test_lens tests/test_lens_agent -q` and `uv run --frozen ruff check src/lens src/lens_agent tests/test_lens tests/test_lens_agent scripts/lens_fake_stack.py`.
- The browser talks only to lens-web (same origin): `/board/*` → `lens:8010/lens/v1/*`, `/agent/*` → `lens-agent:8020/*`. The board MCP (`/mcp` on lens) is never proxied.
- SSE locations: `proxy_buffering off`, `proxy_http_version 1.1`, `proxy_set_header Connection ""`, `proxy_read_timeout` ≥ run timeout + 60 s (720 s for `/agent/`).
- «стоп» is handled by the web (cancel) and never sent to the agent; while a run is active only «стоп» is accepted.
- Only `lens-web` publishes a port (`LENS_WEB_PORT`, default 8010 — the address the old debug page used). `lens`/`lens-agent` get HTTP healthchecks.
- Secrets (`LENS_BOARD_MCP_TOKEN`, `LENS_MCP_TOKEN`, keys) only in the local `.env`.
- Live checks against the running stack or models need the user's «да» first; data on .31 is never deleted.
- Commits: local only; never push.

## Review Focus

- A long run outlives the 5-minute stream token, or the connection drops → the web reconnects with a fresh token and `Last-Event-ID`, without duplicated journal lines; a finished run's stream closes instead of hanging. Tests: `reconnects with Last-Event-ID and a fresh URL until finished` (Task 2), `ignores replayed events` (Task 3), `test_reconnect_after_done_closes_immediately` (Task 1).
- Board ops arrive that the web cannot fold locally (merge into an existing key, `undo`, `merge`, a seq gap) → it re-fetches the whole board instead of drawing a wrong state. Test: `asks for a refetch on gaps, merges into existing keys, undo and merge ops` (Task 3).
- The user types while a run is active → only «стоп» acts; other text is refused with a hint, «стоп» with no run does nothing. Test: `decides what an Enter does` (Task 3).
- A note cites an object that was merged away or hidden → the citation resolves through aliases or degrades to plain text, never a dead link. Test: `canon › follows merge aliases` (Task 3); rendering in `ui/notes.ts` (Task 5).
- The journal «подробнее» on a board call → shows the stored call (board calls now store payloads too), never a 404. Test: `test_happy_path_sources_injected_and_note_written` asserts the `c3` payload (Task 1).

## File Structure

| File | Responsibility |
|---|---|
| `src/lens_agent/stream.py`, `src/lens_agent/calls.py` (modify) | fixes found by the web smoke: close finished streams; board payloads + `added` as items |
| `scripts/lens_fake_stack.py` | dev-only fake stack (memory board, scripted agent, fake KB) for web work without an LLM |
| `web/package.json`, `package-lock.json`, `.nvmrc`, `.gitignore`, `tsconfig.json`, `vite.config.ts` | project, pinned deps, dev proxy identical to nginx |
| `web/src/api/sse.ts` | SSE parser + reconnecting fetch stream |
| `web/src/api/http.ts`, `board.ts`, `agent.ts` | REST helpers, board and agent endpoints |
| `web/src/state/board.ts`, `journal.ts`, `input.ts` | pure state logic |
| `web/src/render/types.ts`, `viewModel.ts`, `vis.ts` | renderer contract, view model, vis-network adapter |
| `web/index.html`, `web/src/style.css`, `web/src/ui/*.ts`, `web/src/main.ts` | shell: same look as the debug page |
| `web/Dockerfile`, `web/nginx.conf`, `web/.dockerignore`, `.dockerignore` | lens-web image |
| `docker-compose.prod.yml` (modify) | `lens` healthcheck/no port, `lens-agent`, `lens-web` |

Python diffs are against local `main` after Plan B. Web files are new and given in full.

---

### Task 1: Backend fixes from the web smoke

**Files:**
- Modify: `src/lens_agent/stream.py`, `src/lens_agent/calls.py`
- Test: `tests/test_lens_agent/test_stream.py`, `tests/test_lens_agent/test_runner.py`

**Interfaces:**
- Produces: `sse_events` returns right after replay when the run is no longer `running` (a browser reconnecting after `done` gets an empty, closed stream); board calls store their payload under their `call_id` (`GET /runs/{id}/calls/{call_id}` works for every journal line); `tool_result.summary.items` for board writes = `added`.

- [ ] **Step 1: Write the failing tests**

```diff
diff --git a/tests/test_lens_agent/test_stream.py b/tests/test_lens_agent/test_stream.py
index 1312d08..e4fab71 100644
--- a/tests/test_lens_agent/test_stream.py
+++ b/tests/test_lens_agent/test_stream.py
@@ -98,3 +98,17 @@ async def test_slow_consumer_catches_up_from_the_store():
     await em.emit("done", status="done")
     await asyncio.wait_for(reader, 2)
     assert [e["seq"] for e in parse(reader_frames)] == list(range(1, 12))
+
+
+async def test_reconnect_after_done_closes_immediately():
+    store, bus = MemoryAgentStore(), EventBus()
+    run = await _run(store)
+    em = RunEmitter(store, bus, run.id)
+    await em.emit("final", answer="a")
+    done = await em.emit("done", status="done")
+    await store.finish_run(run.id, "done")
+
+    async def read():
+        return [f async for f in sse_events(store, bus, run.id, last_event_id=done.seq)]
+
+    assert await asyncio.wait_for(read(), 1) == []
```

```diff
diff --git a/tests/test_lens_agent/test_runner.py b/tests/test_lens_agent/test_runner.py
index 9b9320d..6c867e7 100644
--- a/tests/test_lens_agent/test_runner.py
+++ b/tests/test_lens_agent/test_runner.py
@@ -45,6 +45,8 @@ async def test_happy_path_sources_injected_and_note_written():
         assert len(st.relations) == 1
         assert [n.cites for n in st.notes] == [["kb:e2"]]
         assert (await w.store.get_payload(run.id, "c2")).payload["entities"][0]["id"] == "E1"
+        assert (await w.store.get_payload(run.id, "c3")).payload["added"] == 2
+        assert [r["summary"]["items"] for r in of(evs, "tool_result")][2:] == [2, 1]
 
 
 async def test_unknown_call_id_is_rejected_back_to_the_model():
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run --frozen pytest tests/test_lens_agent -q`
Expected: FAIL — `test_reconnect_after_done_closes_immediately` times out (`TimeoutError`), `test_happy_path…` fails on the `c3` payload (`None`).

- [ ] **Step 3: Implement**

```diff
diff --git a/src/lens_agent/stream.py b/src/lens_agent/stream.py
index dd4db4d..ea1660c 100644
--- a/src/lens_agent/stream.py
+++ b/src/lens_agent/stream.py
@@ -91,6 +91,12 @@ async def sse_events(
             last = ev.seq
             if ev.type == TERMINAL:
                 return
+        run = await store.get_run(run_id)
+        if run is None or run.status != "running":
+            # finished (the client already has `done`, or it lands right now): no live tail
+            for ev in await store.list_events(run_id, after_seq=last):
+                yield _frame(ev.envelope())
+            return
         while True:
             try:
                 msg = await asyncio.wait_for(q.get(), timeout=ping_s)
```

```diff
diff --git a/src/lens_agent/calls.py b/src/lens_agent/calls.py
index d6db3d0..e8b43e0 100644
--- a/src/lens_agent/calls.py
+++ b/src/lens_agent/calls.py
@@ -53,6 +53,8 @@ def _summary(result: Any, text: str) -> dict[str, Any]:
     items = None
     if isinstance(result, list):
         items = len(result)
+    elif isinstance(result, dict) and isinstance(result.get("added"), int):
+        items = result["added"]  # board writes: what actually landed
     elif isinstance(result, dict):
         items = next((len(v) for v in result.values() if isinstance(v, list)), None)
     return {"items": items, "bytes": len(text.encode()), "preview": text[:200]}
@@ -183,6 +185,9 @@ class RunCalls:
             result = {**result, "rejected": rejected + list(result.get("rejected", []))}
         else:
             result = await self._call(cid, t0, call_tool, name, args)
+        await self.store.save_payload(CallPayload(run_id=self.run_id, call_id=cid,
+                                                  server="board", tool=name, args=args,
+                                                  payload=result))
         if name == "add_note":
             self.note_written = True
         elif name == "undo":
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run --frozen pytest tests/test_lens tests/test_lens_agent -q && uv run --frozen ruff check src/lens_agent tests/test_lens_agent`
Expected: 207 passed, 10 skipped; ruff clean.

- [ ] **Step 5: Commit (local)**

```bash
git add src/lens_agent/stream.py src/lens_agent/calls.py tests/test_lens_agent/test_stream.py tests/test_lens_agent/test_runner.py
git commit -m "fix(lens-agent): close finished run streams; store board call payloads"
```

---

### Task 2: Web project and SSE client

**Files:**
- Create: `web/package.json`, `web/package-lock.json` (generated), `web/.nvmrc`, `web/.gitignore`, `web/tsconfig.json`, `web/vite.config.ts`, `web/src/api/sse.ts`
- Test: `web/src/api/sse.test.ts`

**Interfaces:**
- Produces: `SSEParser.feed(chunk) -> SSEMessage[]` (`{id?, event, data}`); `openStream({url, onMessage, finished?, onError?, lastEventId?, retryMs?, signal?, fetchImpl?})` — calls `url()` on every (re)connect, sends `Last-Event-ID`, stops when `finished()` or aborted.

- [ ] **Step 1: Create the project** — `web/package.json`:

```json
{
  "name": "lens-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "engines": {
    "node": ">=22 <23"
  },
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "test": "vitest run",
    "typecheck": "tsc --noEmit"
  },
  "devDependencies": {
    "@types/node": "22.20.4",
    "typescript": "5.9.3",
    "vite": "6.4.3",
    "vitest": "3.2.7"
  },
  "dependencies": {
    "@egjs/hammerjs": "2.0.17",
    "component-emitter": "2.0.0",
    "keycharm": "0.4.0",
    "uuid": "14.0.2",
    "vis-data": "8.0.5",
    "vis-network": "10.1.2",
    "vis-util": "6.0.2"
  }
}
```

then install the pinned versions (this writes `package-lock.json`):

```bash
cd web
echo "22" > .nvmrc
printf 'node_modules\ndist\n' > .gitignore
npm install --save-exact vis-network@10.1.2 vis-data@8.0.5 vis-util@6.0.2 uuid@14.0.2 keycharm@0.4.0 component-emitter@2.0.0 @egjs/hammerjs@2.0.17
npm install --save-dev --save-exact typescript@5.9.3 vite@6.4.3 vitest@3.2.7 @types/node@22
npm audit --omit=dev   # expected: found 0 vulnerabilities
```

`web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "types": ["vite/client", "node"]
  },
  "include": ["src", "vite.config.ts"]
}
```

`web/vite.config.ts`:

```ts
/// <reference types="vitest/config" />
import { defineConfig } from "vite";

// Same routes as nginx in the container: /board/* → lens (/lens/v1/*), /agent/* → lens-agent.
const board = process.env.LENS_BOARD_URL ?? "http://localhost:8010";
const agent = process.env.LENS_AGENT_URL ?? "http://localhost:8020";

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/board": { target: board, changeOrigin: true, rewrite: (p) => p.replace(/^\/board/, "/lens/v1") },
      "/agent": { target: agent, changeOrigin: true, rewrite: (p) => p.replace(/^\/agent/, "") },
    },
  },
  build: { chunkSizeWarningLimit: 800 }, // vis-network alone is ~500 kB
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
```

- [ ] **Step 2: Write the failing test** — `web/src/api/sse.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { openStream, SSEParser, type SSEMessage } from "./sse";

describe("SSEParser", () => {
  it("parses id/event/multi-line data across chunk borders and skips pings", () => {
    const p = new SSEParser();
    expect(p.feed(": ping\n\nid: 3\nevent: text\ndata: {\"a\":")).toEqual([]);
    expect(p.feed("1}\ndata: x\r\n\r\nevent: ready\ndata: {}\n\n")).toEqual([
      { id: "3", event: "text", data: "{\"a\":1}\nx" },
      { event: "ready", data: "{}" },
    ]);
  });
});

function body(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch));
      c.close();
    },
  });
}

describe("openStream", () => {
  it("reconnects with Last-Event-ID and a fresh URL until finished", async () => {
    const calls: { url: string; lastId?: string }[] = [];
    const replies = [
      ["id: 1\nevent: run_started\ndata: {}\n\n", "id: 2\nevent: text\ndata: {}\n\n"],
      ["id: 3\nevent: done\ndata: {}\n\n"],
    ];
    const fetchImpl = (async (url: string, init: RequestInit) => {
      calls.push({ url, lastId: (init.headers as Record<string, string>)["Last-Event-ID"] });
      return new Response(body(replies[calls.length - 1]), { status: 200 });
    }) as unknown as typeof fetch;
    let n = 0;
    const got: SSEMessage[] = [];
    await openStream({
      url: async () => `/events?token=t${++n}`,
      onMessage: (m) => got.push(m),
      finished: () => got.some((m) => m.event === "done"),
      retryMs: 1,
      fetchImpl,
    });
    expect(got.map((m) => m.id)).toEqual(["1", "2", "3"]);
    expect(calls).toEqual([
      { url: "/events?token=t1", lastId: undefined },
      { url: "/events?token=t2", lastId: "2" },
    ]);
  });

  it("reports errors, retries, and stops on abort", async () => {
    const ctl = new AbortController();
    const errors: unknown[] = [];
    let tries = 0;
    const fetchImpl = (async () => {
      if (++tries === 2) ctl.abort();
      return new Response("nope", { status: 403 });
    }) as unknown as typeof fetch;
    await openStream({
      url: async () => "/x",
      onMessage: () => {},
      onError: (e) => errors.push(e),
      retryMs: 1,
      signal: ctl.signal,
      fetchImpl,
    });
    expect(tries).toBe(2);
    expect(String(errors[0])).toContain("403");
  });
});
```

Run: `cd web && npx vitest run` — Expected: FAIL (`Failed to resolve import "./sse"`).

- [ ] **Step 3: Implement** — `web/src/api/sse.ts`:

```ts
// Shared SSE client over fetch (not EventSource): every (re)connect asks for a fresh URL
// (stream tokens live 5 min) and sends Last-Event-ID itself.

export interface SSEMessage {
  id?: string;
  event: string;
  data: string;
}

/** Incremental text/event-stream parser: feed chunks, get complete messages. */
export class SSEParser {
  private buf = "";

  feed(chunk: string): SSEMessage[] {
    this.buf += chunk.replace(/\r\n?/g, "\n");
    const out: SSEMessage[] = [];
    let cut: number;
    while ((cut = this.buf.indexOf("\n\n")) >= 0) {
      const block = this.buf.slice(0, cut);
      this.buf = this.buf.slice(cut + 2);
      const msg: SSEMessage = { event: "message", data: "" };
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (!line || line.startsWith(":")) continue;
        const i = line.indexOf(":");
        const field = i < 0 ? line : line.slice(0, i);
        const value = i < 0 ? "" : line.slice(i + 1).replace(/^ /, "");
        if (field === "data") data.push(value);
        else if (field === "event") msg.event = value;
        else if (field === "id") msg.id = value;
      }
      if (!data.length) continue; // comment-only block (ping)
      msg.data = data.join("\n");
      out.push(msg);
    }
    return out;
  }
}

export interface StreamOptions {
  /** Builds the URL for each (re)connect — fetch a fresh token here. */
  url: () => Promise<string>;
  onMessage: (msg: SSEMessage) => void;
  /** Return true when the stream is complete (e.g. after `done`): no reconnect. */
  finished?: () => boolean;
  onError?: (err: unknown) => void;
  lastEventId?: string;
  retryMs?: number;
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener("abort", () => { clearTimeout(t); resolve(); }, { once: true });
  });

/** Reads until `finished()` or abort; reconnects with Last-Event-ID after drops. */
export async function openStream(opts: StreamOptions): Promise<void> {
  const doFetch = opts.fetchImpl ?? fetch;
  let lastId = opts.lastEventId;
  while (!opts.signal?.aborted) {
    try {
      const headers: Record<string, string> = { Accept: "text/event-stream" };
      if (lastId) headers["Last-Event-ID"] = lastId;
      const res = await doFetch(await opts.url(), { headers, signal: opts.signal });
      if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
      const parser = new SSEParser();
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        for (const msg of parser.feed(value)) {
          if (msg.id) lastId = msg.id;
          opts.onMessage(msg);
        }
      }
    } catch (err) {
      if (opts.signal?.aborted) return;
      opts.onError?.(err);
    }
    if (opts.finished?.()) return;
    await sleep(opts.retryMs ?? 1000, opts.signal);
  }
}
```

- [ ] **Step 4: Run, expect pass**

Run: `cd web && npx vitest run` — Expected: 3 passed.

- [ ] **Step 5: Commit (local)**

```bash
git add web/package.json web/package-lock.json web/.nvmrc web/.gitignore web/tsconfig.json web/vite.config.ts web/src/api/sse.ts web/src/api/sse.test.ts
git commit -m "feat(lens-web): Vite+TS project and reconnecting SSE client"
```

---

### Task 3: Board, journal and input state

**Files:**
- Create: `web/src/state/board.ts`, `web/src/state/journal.ts`, `web/src/state/input.ts`
- Test: `web/src/state/board.test.ts`, `web/src/state/journal.test.ts`, `web/src/state/input.test.ts`

**Interfaces:**
- Produces:
  - `BoardState {objects, relations, notes, aliases, inputs, last_seq}`, `BoardObject`, `Relation`, `Note`, `Source`, `Op`; `applyOps(st, ops) -> BoardState | null` (null = re-fetch); `canon(st, key)`
  - `AgentEvent`, `RunJournal {runId, input, mentions, lines, status, answer?, lastSeq}`, `JournalLine {kind: sources|call|result|text|thinking|final|error, text, callId?, ok?, truncated?}`; `newJournal(runId, input?, mentions?)`, `reduce(j, ev)`, `shortArgs(args, max?)`
  - `isStop(text)`, `decide(text, running) -> "send"|"stop"|"busy"|"ignore"`, `toggleMention(mentions, key)`

- [ ] **Step 1: Write the failing tests** — `web/src/state/board.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { applyOps, canon, type BoardState, type Op } from "./board";

const obj = (key: string) => ({ key, type: "person", label: key, attrs: {} });
const base = (): BoardState => ({
  objects: [{ ...obj("kb:a"), inputs: ["r1"], hidden: false, pin: null }],
  relations: [],
  notes: [],
  aliases: { "kb:old": "kb:a" },
  inputs: ["r1"],
  last_seq: 1,
});
const op = (seq: number, kind: string, payload: Record<string, unknown>, input_id: string | null = "r2"): Op =>
  ({ seq, kind, payload, input_id });

describe("applyOps", () => {
  it("applies new objects, relations, notes, hide and pin in seq order", () => {
    const st = applyOps(base(), [
      op(3, "add_relations", { relations: [{ from_key: "kb:b", to_key: "kb:a", kind: "связан" }] }),
      op(2, "add_objects", { objects: [obj("kb:b")] }),
      op(4, "add_note", { note: { key: "note:r2", text: "см. [[kb:b]]", cites: ["kb:b"] } }),
      op(5, "hide", { keys: ["kb:a"] }),
      op(6, "pin", { key: "kb:b", x: 1, y: 2 }, null),
    ])!;
    expect(st.last_seq).toBe(6);
    expect(st.objects.map((o) => [o.key, o.hidden, o.inputs])).toEqual([
      ["kb:a", true, ["r1"]], ["kb:b", false, ["r2"]]]);
    expect(st.objects[1].pin).toEqual({ x: 1, y: 2 });
    expect(st.relations[0].key).toBe("kb:b|связан|kb:a");
    expect(st.notes).toHaveLength(1);
    expect(st.inputs).toEqual(["r1", "r2"]);
  });

  it("replaces a note with the same key and skips already-seen ops", () => {
    const once = applyOps(base(), [op(2, "add_note", { note: { key: "note:r2", text: "a", cites: [] } })])!;
    const twice = applyOps(once, [
      op(2, "add_note", { note: { key: "note:r2", text: "dup", cites: [] } }),
      op(3, "add_note", { note: { key: "note:r2", text: "b", cites: [] } }),
    ])!;
    expect(twice.notes.map((n) => n.text)).toEqual(["b"]);
  });

  it("asks for a refetch on gaps, merges into existing keys, undo and merge ops", () => {
    expect(applyOps(base(), [op(3, "hide", { keys: [] })])).toBeNull();
    expect(applyOps(base(), [op(2, "add_objects", { objects: [obj("kb:a")] })])).toBeNull();
    expect(applyOps(base(), [op(2, "add_objects", { objects: [obj("kb:old")] })])).toBeNull();
    expect(applyOps(base(), [op(2, "undo", { input_id: "r1" })])).toBeNull();
    expect(applyOps(base(), [op(2, "merge", { keep: "kb:a", drop: "kb:b" })])).toBeNull();
  });

  it("does not mutate the input state", () => {
    const st = base();
    applyOps(st, [op(2, "hide", { keys: ["kb:a"] })]);
    expect(st.objects[0].hidden).toBe(false);
  });
});

describe("canon", () => {
  it("follows merge aliases", () => {
    expect(canon(base(), "kb:old")).toBe("kb:a");
    expect(canon(base(), "kb:x")).toBe("kb:x");
  });
});
```

`web/src/state/journal.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { newJournal, reduce, shortArgs, type AgentEvent } from "./journal";

let seq = 0;
const ev = (type: AgentEvent["type"], f: Record<string, unknown> = {}): AgentEvent =>
  ({ run_id: "r1", seq: ++seq, ts: "", type, ...f });

describe("journal reducer", () => {
  it("turns a run into journal lines", () => {
    seq = 0;
    const events = [
      ev("run_started", { input: { text: "Росатом", mentions: [] }, mcp: [
        { name: "kb", status: "up" }, { name: "dead", status: "down" }] }),
      ev("thinking", { delta: "хм" }), ev("thinking", { delta: "м" }),
      ev("tool_call", { call_id: "c1", server: "kb", tool: "find", args: { name: "Росатом" } }),
      ev("tool_result", { call_id: "c1", ok: true, summary: { items: 2, bytes: 2048 }, truncated: true }),
      ev("tool_call", { call_id: "c2", server: "kb", tool: "boom", args: {} }),
      ev("tool_result", { call_id: "c2", ok: false, error: "источник упал", summary: {} }),
      ev("text", { delta: "При" }), ev("text", { delta: "вет" }),
      ev("final", { answer: "Привет" }), ev("done", { status: "done" }),
    ];
    const j = events.reduce(reduce, newJournal("r1"));
    expect(j.status).toBe("done");
    expect(j.input).toBe("Росатом");
    expect(j.answer).toBe("Привет");
    expect(j.lines.map((l) => [l.kind, l.text])).toEqual([
      ["sources", "kb ✓ · dead ✗"],
      ["thinking", "хмм"],
      ["call", "→ kb.find(name=\"Росатом\")"],
      ["result", "← 2 эл., 2.0 КБ · усечено"],
      ["call", "→ kb.boom()"],
      ["result", "← источник упал"],
      ["final", "Привет"],
    ]);
    expect(j.lines[5].ok).toBe(false);
  });

  it("ignores replayed events", () => {
    seq = 0;
    const a = ev("text", { delta: "a" });
    const j = [a, a, ev("text", { delta: "b" })].reduce(reduce, newJournal("r1"));
    expect(j.lines).toEqual([{ kind: "text", text: "ab" }]);
  });

  it("shows errors and failed status", () => {
    seq = 0;
    const j = [ev("error", { where: "limit", message: "время вышло" }), ev("done", { status: "failed" })]
      .reduce(reduce, newJournal("r1"));
    expect(j.lines).toEqual([{ kind: "error", text: "limit: время вышло" }]);
    expect(j.status).toBe("failed");
  });
});

describe("shortArgs", () => {
  it("summarises arrays and cuts long values", () => {
    expect(shortArgs({ objects: [1, 2, 3], limit: 5 })).toBe("objects=[3], limit=5");
    expect(shortArgs({ q: "x".repeat(200) }, 20)).toHaveLength(20);
  });
});
```

`web/src/state/input.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { decide, isStop, toggleMention } from "./input";

describe("input protocol", () => {
  it("recognises stop words like the board router", () => {
    for (const t of ["стоп", "Стоп!", " остановись ", "прекрати.", "stop"]) expect(isStop(t)).toBe(true);
    for (const t of ["стоп-кран", "остановка Росатома", "не стоп"]) expect(isStop(t)).toBe(false);
  });

  it("decides what an Enter does", () => {
    expect(decide("Росатом", false)).toBe("send");
    expect(decide("Росатом", true)).toBe("busy");
    expect(decide("стоп", true)).toBe("stop");
    expect(decide("стоп", false)).toBe("ignore");
    expect(decide("   ", false)).toBe("ignore");
  });

  it("toggles mentions", () => {
    expect(toggleMention([], "kb:a")).toEqual(["kb:a"]);
    expect(toggleMention(["kb:a", "kb:b"], "kb:a")).toEqual(["kb:b"]);
  });
});
```

Run: `cd web && npx vitest run` — Expected: the three new files FAIL (unresolved imports).

- [ ] **Step 2: Implement** — `web/src/state/board.ts`:

```ts
// Board state as the board service returns it, plus cheap local application of ops.
// Anything that needs the server's fold rules (merge into an existing key, undo, merge,
// a seq gap) returns null: the caller re-fetches the whole board.

export interface Source {
  server: string;
  tool: string;
  call_id: string;
  run_id: string | null;
  namespace: string;
}

export interface BoardObject {
  key: string;
  type: string;
  label: string;
  description?: string | null;
  attrs: Record<string, unknown>;
  sources?: Source[];
  inputs: string[];
  hidden: boolean;
  pin: { x: number; y: number } | null;
}

export interface Relation {
  key: string;
  from_key: string;
  to_key: string;
  kind: string;
  attrs?: Record<string, unknown>;
}

export interface Note {
  key: string;
  text: string;
  cites: string[];
}

export interface BoardState {
  objects: BoardObject[];
  relations: Relation[];
  notes: Note[];
  aliases: Record<string, string>;
  inputs: string[];
  last_seq: number;
}

export interface Op {
  seq: number;
  kind: string;
  payload: Record<string, any>;
  input_id: string | null;
}

const relKey = (r: { from_key: string; kind: string; to_key: string }) =>
  `${r.from_key}|${r.kind}|${r.to_key}`;

/** New state with `ops` applied, or null when a full re-fetch is needed. */
export function applyOps(st: BoardState, ops: Op[]): BoardState | null {
  const next: BoardState = {
    ...st,
    objects: st.objects.map((o) => ({ ...o })),
    relations: [...st.relations],
    notes: [...st.notes],
    inputs: [...st.inputs],
  };
  const byKey = new Map(next.objects.map((o) => [o.key, o]));
  for (const op of [...ops].sort((a, b) => a.seq - b.seq)) {
    if (op.seq <= next.last_seq) continue;
    if (op.seq !== next.last_seq + 1) return null; // gap
    const p = op.payload;
    switch (op.kind) {
      case "pin": {
        const o = byKey.get(p.key);
        if (o) o.pin = { x: p.x, y: p.y };
        break;
      }
      case "hide":
      case "show":
        for (const k of p.keys as string[]) {
          const o = byKey.get(k);
          if (o) o.hidden = op.kind === "hide";
        }
        break;
      case "add_note": {
        const i = next.notes.findIndex((n) => n.key === p.note.key);
        if (i >= 0) next.notes[i] = p.note;
        else next.notes.push(p.note);
        break;
      }
      case "add_objects":
        for (const raw of p.objects as BoardObject[]) {
          if (byKey.has(raw.key) || raw.key in next.aliases) return null; // server merges
          const o: BoardObject = { ...raw, inputs: op.input_id ? [op.input_id] : [],
                                   hidden: false, pin: null };
          next.objects.push(o);
          byKey.set(o.key, o);
        }
        break;
      case "add_relations":
        for (const r of p.relations as Relation[]) {
          const key = relKey(r);
          if (next.relations.some((x) => x.key === key)) return null;
          next.relations.push({ ...r, key });
        }
        break;
      default:
        return null; // undo, merge, views, mode…: server fold only
    }
    if (op.input_id && !next.inputs.includes(op.input_id)) next.inputs.push(op.input_id);
    next.last_seq = op.seq;
  }
  return next;
}

/** A citation key → the object key it now lives under (after merges). */
export function canon(st: BoardState, key: string): string {
  let k = key;
  for (let i = 0; i < 10 && st.aliases[k]; i++) k = st.aliases[k];
  return k;
}
```

`web/src/state/journal.ts`:

```ts
// Agent run events → journal lines (one block per run). Pure; replays are idempotent.

export interface AgentEvent {
  run_id: string;
  seq: number;
  ts: string;
  type: "run_started" | "thinking" | "text" | "tool_call" | "tool_result" | "final" | "error" | "done";
  [field: string]: any;
}

export type RunStatus = "running" | "done" | "failed" | "cancelled";

export interface JournalLine {
  kind: "sources" | "call" | "result" | "text" | "thinking" | "final" | "error";
  text: string;
  callId?: string;
  ok?: boolean;
  truncated?: boolean;
}

export interface RunJournal {
  runId: string;
  input: string;
  mentions: string[];
  lines: JournalLine[];
  status: RunStatus;
  answer?: string;
  lastSeq: number;
}

export const newJournal = (runId: string, input = "", mentions: string[] = []): RunJournal =>
  ({ runId, input, mentions, lines: [], status: "running", lastSeq: 0 });

/** Short one-line view of tool args: arrays become [n], long strings are cut. */
export function shortArgs(args: Record<string, unknown> | undefined, max = 80): string {
  const parts = Object.entries(args ?? {}).map(([k, v]) => {
    const val = Array.isArray(v) ? `[${v.length}]` : JSON.stringify(v);
    return `${k}=${val}`;
  });
  const s = parts.join(", ");
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

function resultText(ev: AgentEvent): string {
  if (!ev.ok) return ev.error ?? "ошибка";
  if (ev.cached_from) return `повтор ${ev.cached_from}`;
  const items = ev.summary?.items;
  const size = ev.summary?.bytes ?? 0;
  const kb = size >= 1024 ? `${(size / 1024).toFixed(1)} КБ` : `${size} Б`;
  return `${items != null ? `${items} эл., ` : ""}${kb}${ev.truncated ? " · усечено" : ""}`;
}

export function reduce(j: RunJournal, ev: AgentEvent): RunJournal {
  if (ev.seq <= j.lastSeq) return j;
  const lines = [...j.lines];
  const next: RunJournal = { ...j, lines, lastSeq: ev.seq };
  const appendDelta = (kind: "text" | "thinking") => {
    const last = lines[lines.length - 1];
    if (last?.kind === kind) lines[lines.length - 1] = { ...last, text: last.text + ev.delta };
    else lines.push({ kind, text: ev.delta });
  };
  switch (ev.type) {
    case "run_started":
      next.input = ev.input?.text ?? next.input;
      next.mentions = ev.input?.mentions ?? next.mentions;
      lines.push({ kind: "sources", text: (ev.mcp ?? []).map(
        (m: { name: string; status: string }) => `${m.name} ${m.status === "up" ? "✓" : "✗"}`).join(" · ") });
      break;
    case "text":
    case "thinking":
      appendDelta(ev.type);
      break;
    case "tool_call":
      lines.push({ kind: "call", callId: ev.call_id,
                   text: `→ ${ev.server}.${ev.tool}(${shortArgs(ev.args)})` });
      break;
    case "tool_result":
      lines.push({ kind: "result", callId: ev.call_id, ok: ev.ok, truncated: ev.truncated,
                   text: `← ${resultText(ev)}` });
      break;
    case "final": {
      next.answer = ev.answer;
      const last = lines[lines.length - 1];
      if (last?.kind === "text" && last.text.trim() === String(ev.answer).trim()) lines.pop();
      lines.push({ kind: "final", text: ev.answer });
      break;
    }
    case "error":
      lines.push({ kind: "error", text: `${ev.where}: ${ev.message}` });
      break;
    case "done":
      next.status = ev.status;
      break;
  }
  return next;
}
```

`web/src/state/input.ts` (stop words = `src/lens/router.py` `_STOP`):

```ts
// Input protocol (spec §3): «стоп» is handled here and never sent to the agent; while a run
// is active everything else is refused; mentions are board keys picked by clicking objects.

const STOP = /^(стоп|останови(сь)?|прекрати|stop)\s*[.!]?$/i;

export const isStop = (text: string) => STOP.test(text.trim());

export type Decision = "send" | "stop" | "busy" | "ignore";

export function decide(text: string, running: boolean): Decision {
  if (!text.trim()) return "ignore";
  if (isStop(text)) return running ? "stop" : "ignore";
  return running ? "busy" : "send";
}

export function toggleMention(mentions: string[], key: string): string[] {
  return mentions.includes(key) ? mentions.filter((k) => k !== key) : [...mentions, key];
}
```

- [ ] **Step 3: Run, expect pass**

Run: `cd web && npx vitest run` — Expected: 15 passed.

- [ ] **Step 4: Commit (local)**

```bash
git add web/src/state
git commit -m "feat(lens-web): board ops, run journal and input protocol state"
```

---

### Task 4: Renderer contract, view model, vis-network adapter

**Files:**
- Create: `web/src/render/types.ts`, `web/src/render/viewModel.ts`, `web/src/render/vis.ts`
- Test: `web/src/render/viewModel.test.ts`

**Interfaces:**
- Consumes: Task 3 `BoardState`.
- Produces: `BoardRenderer {mount, render(view), focus(key), on("select"|"dragEnd"|"open", cb), destroy}`, `BoardView {nodes: NodeView[], edges: EdgeView[]}`; `toView(st, mentions, latestRun?)`, `toneOf(type)`, `ICON`; `VisRenderer implements BoardRenderer`.

- [ ] **Step 1: Write the failing test** — `web/src/render/viewModel.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { BoardState } from "../state/board";
import { toView } from "./viewModel";

const st: BoardState = {
  objects: [
    { key: "kb:e1", type: "event", label: "Встреча", attrs: { date: "2024-05-16" }, inputs: ["r1"],
      hidden: false, pin: null, description: "саммит",
      sources: [{ server: "kb", tool: "find", call_id: "c2", run_id: "r1", namespace: "kb" }] },
    { key: "kb:p1", type: "person", label: "Персона", attrs: {}, inputs: ["r2"], hidden: false,
      pin: { x: 1, y: 2 } },
    { key: "kb:h", type: "ip", label: "10.0.0.1", attrs: {}, inputs: ["r1"], hidden: true, pin: null },
  ],
  relations: [
    { key: "kb:p1|участник|kb:e1", from_key: "kb:p1", to_key: "kb:e1", kind: "участник" },
    { key: "kb:h|связан|kb:e1", from_key: "kb:h", to_key: "kb:e1", kind: "связан" },
  ],
  notes: [], aliases: {}, inputs: ["r1", "r2"], last_seq: 5,
};

describe("toView", () => {
  it("maps visible objects and relations between them", () => {
    const v = toView(st, ["kb:p1"], "r2");
    expect(v.nodes.map((n) => [n.key, n.tone, n.selected, n.fresh])).toEqual([
      ["kb:e1", "event", false, false], ["kb:p1", "entity", true, true]]);
    expect(v.nodes[0].label).toBe("📅 Встреча\n2024-05-16");
    expect(v.nodes[0].title).toBe("kb:e1\nevent\nсаммит\nkb.find c2");
    expect(v.nodes[1].pin).toEqual({ x: 1, y: 2 });
    expect(v.edges).toEqual([{ key: "kb:p1|участник|kb:e1", from: "kb:p1", to: "kb:e1", label: "участник" }]);
  });
});
```

Run: `cd web && npx vitest run` — Expected: FAIL (unresolved `./viewModel`).

- [ ] **Step 2: Implement** — `web/src/render/types.ts`:

```ts
// Renderer contract (spec §7): the shell talks to any board engine through this only.
// vis-network now; cytoscape / tldraw / React Flow adapters swap in one line of main.ts.

export interface Point {
  x: number;
  y: number;
}

export type Tone = "entity" | "event" | "tech";

export interface NodeView {
  key: string;
  label: string;
  type: string;
  tone: Tone;
  selected: boolean; // mentioned in the input
  fresh: boolean; // touched by the latest run
  pin: Point | null;
  title: string; // hover text
}

export interface EdgeView {
  key: string;
  from: string;
  to: string;
  label: string;
}

export interface BoardView {
  nodes: NodeView[];
  edges: EdgeView[];
}

export type RendererEvent = "select" | "dragEnd" | "open";

export interface BoardRenderer {
  mount(el: HTMLElement): void;
  render(view: BoardView): void;
  focus(key: string): void;
  on(ev: RendererEvent, cb: (key: string, pos?: Point) => void): void;
  destroy(): void;
}
```

`web/src/render/viewModel.ts`:

```ts
// Board state → renderer-neutral view.
import type { BoardState } from "../state/board";
import type { BoardView, Tone } from "./types";

const TECH = new Set(["ip", "domain", "certificate", "service", "asn"]);
export const ICON: Record<string, string> = {
  person: "👤", organization: "🏢", event: "📅", location: "📍", document: "📄", topic: "🏷",
  ip: "🖥", domain: "🌐", certificate: "🔒", service: "🔌", asn: "🛰", other: "•",
};

export const toneOf = (type: string): Tone =>
  TECH.has(type) ? "tech" : type === "event" ? "event" : "entity";

export function toView(st: BoardState, mentions: string[], latestRun?: string): BoardView {
  const visible = st.objects.filter((o) => !o.hidden);
  const keys = new Set(visible.map((o) => o.key));
  return {
    nodes: visible.map((o) => {
      const date = o.type === "event" && typeof o.attrs?.date === "string" ? `\n${o.attrs.date}` : "";
      const src = (o.sources ?? []).map((s) => `${s.server}.${s.tool} ${s.call_id}`);
      return {
        key: o.key,
        label: `${ICON[o.type] ?? "•"} ${o.label}${date}`,
        type: o.type,
        tone: toneOf(o.type),
        selected: mentions.includes(o.key),
        fresh: !!latestRun && o.inputs.includes(latestRun),
        pin: o.pin,
        title: [o.key, o.type, o.description ?? "", ...src].filter(Boolean).join("\n"),
      };
    }),
    edges: st.relations
      .filter((r) => keys.has(r.from_key) && keys.has(r.to_key))
      .map((r) => ({ key: r.key, from: r.from_key, to: r.to_key, label: r.kind })),
  };
}
```

`web/src/render/vis.ts`:

```ts
// vis-network adapter for BoardRenderer (look of the old debug page).
import { DataSet } from "vis-data/peer";
import { Network, type Edge, type Node } from "vis-network/peer";
import type { BoardRenderer, BoardView, Point, RendererEvent } from "./types";

const TONE = { entity: "#6b8afd", event: "#e0a030", tech: "#2a9d8f" } as const;
const SELECTED = "#f25f9c";
const FRESH = "#3ccf6e";

export class VisRenderer implements BoardRenderer {
  private nodes = new DataSet<Node>();
  private edges = new DataSet<Edge>();
  private net?: Network;
  private handlers: Record<RendererEvent, ((key: string, pos?: Point) => void)[]> =
    { select: [], dragEnd: [], open: [] };

  mount(el: HTMLElement): void {
    this.net = new Network(el, { nodes: this.nodes, edges: this.edges }, {
      physics: { solver: "forceAtlas2Based", forceAtlas2Based: { gravitationalConstant: -60, springLength: 140 },
                 stabilization: { iterations: 150 } },
      interaction: { hover: true },
      nodes: { font: { color: "#d7dce4", size: 13, face: "Helvetica Neue, Arial, sans-serif" },
               borderWidth: 1.5, shape: "box", margin: { top: 8, right: 8, bottom: 8, left: 8 },
               shapeProperties: { borderRadius: 8 } },
      edges: { color: { color: "#3a4250", highlight: "#8a93a3" },
               font: { color: "#8a93a3", size: 10, strokeWidth: 0 }, smooth: { enabled: true, type: "continuous", roundness: 0.5 },
               arrows: { to: { enabled: true, scaleFactor: 0.4 } } },
    });
    this.net.on("click", (p) => { if (p.nodes.length) this.emit("select", String(p.nodes[0])); });
    this.net.on("doubleClick", (p) => { if (p.nodes.length) this.emit("open", String(p.nodes[0])); });
    this.net.on("dragEnd", (p) => {
      if (!p.nodes.length || !this.net) return;
      const key = String(p.nodes[0]);
      const pos = this.net.getPositions([key])[key];
      this.emit("dragEnd", key, { x: Math.round(pos.x), y: Math.round(pos.y) });
    });
  }

  render(view: BoardView): void {
    const want: Node[] = view.nodes.map((n) => {
      const border = n.selected ? SELECTED : n.fresh ? FRESH : TONE[n.tone];
      const node: Node = {
        id: n.key, label: n.label, title: n.title,
        color: { background: "#161b23", border, highlight: { background: "#1f2633", border: SELECTED } },
        borderWidth: n.selected ? 3 : 1.5,
      };
      if (n.pin) Object.assign(node, { x: n.pin.x, y: n.pin.y, fixed: true });
      return node;
    });
    const wantE: Edge[] = view.edges.map((e) => ({ id: e.key, from: e.from, to: e.to, label: e.label }));
    sync(this.nodes, want);
    sync(this.edges, wantE);
  }

  focus(key: string): void {
    this.net?.focus(key, { scale: 1.2, animation: true });
    this.net?.selectNodes([key]);
  }

  on(ev: RendererEvent, cb: (key: string, pos?: Point) => void): void {
    this.handlers[ev].push(cb);
  }

  destroy(): void {
    this.net?.destroy();
    this.net = undefined;
  }

  private emit(ev: RendererEvent, key: string, pos?: Point) {
    for (const cb of this.handlers[ev]) cb(key, pos);
  }
}

function sync<T extends { id?: string | number }>(ds: DataSet<T>, want: T[]) {
  const keep = new Set(want.map((w) => w.id));
  ds.update(want as any);
  ds.remove(ds.getIds().filter((id) => !keep.has(id)));
}
```

- [ ] **Step 3: Run, expect pass**

Run: `cd web && npx vitest run && npx tsc --noEmit` — Expected: 16 passed; tsc clean.

- [ ] **Step 4: Commit (local)**

```bash
git add web/src/render
git commit -m "feat(lens-web): BoardRenderer contract, view model and vis-network adapter"
```

---

### Task 5: Shell UI and dev fake stack

**Files:**
- Create: `web/index.html`, `web/src/style.css`, `web/src/api/http.ts`, `web/src/api/board.ts`, `web/src/api/agent.ts`, `web/src/ui/dom.ts`, `web/src/ui/journal.ts`, `web/src/ui/notes.ts`, `web/src/main.ts`, `scripts/lens_fake_stack.py`

**Interfaces:**
- Consumes: Tasks 2–4; board REST `/board/workspaces…` (Plan A), agent REST/SSE `/agent/runs…` (Plan B).
- Produces: the page. Settings (API key) in `localStorage["lensWeb"]`. Renderer swap point: the `renderer` constant in `main.ts`.

- [ ] **Step 1: API modules** — `web/src/api/http.ts`:

```ts
// REST helper: same-origin paths (/board/*, /agent/*), key from page settings.

export interface Settings {
  key: string;
}

const STORAGE = "lensWeb";

export function loadSettings(): Settings {
  try {
    return { key: "", ...JSON.parse(localStorage.getItem(STORAGE) || "{}") };
  } catch {
    return { key: "" };
  }
}

export function saveSettings(s: Settings): void {
  try {
    localStorage.setItem(STORAGE, JSON.stringify(s));
  } catch {
    /* private mode: keep in memory only */
  }
}

export class HttpError extends Error {
  constructor(public status: number, public body: string) {
    super(`${status} ${body}`);
  }
}

export async function api<T>(settings: Settings, path: string,
                             opt: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(path, {
    method: opt.method ?? "GET",
    headers: { "X-API-Key": settings.key, "Content-Type": "application/json" },
    body: opt.body === undefined ? undefined : JSON.stringify(opt.body),
  });
  if (!res.ok) throw new HttpError(res.status, await res.text());
  return res.json() as Promise<T>;
}
```

`web/src/api/board.ts`:

```ts
// Board service (lens) REST + stream, reached at /board/* (nginx → /lens/v1/*).
import type { BoardState, Op } from "../state/board";
import { api, type Settings } from "./http";
import { openStream } from "./sse";

export interface Workspace {
  id: string;
  title: string;
}

export const listWorkspaces = (s: Settings) => api<Workspace[]>(s, "/board/workspaces");
export const createWorkspace = (s: Settings, title: string) =>
  api<Workspace>(s, "/board/workspaces", { method: "POST", body: { title } });
export const getBoard = (s: Settings, ws: string) =>
  api<{ workspace: Workspace; state: BoardState }>(s, `/board/workspaces/${ws}`);
export const pin = (s: Settings, ws: string, key: string, x: number, y: number) =>
  api<{ seq: number }>(s, `/board/workspaces/${ws}/pin`, { method: "POST", body: { key, x, y } });

export type BoardEvent = { type: "ready" } | { type: "ops"; ops: Op[] } | { type: "resync" };

/** Follows the board stream; reconnects (fresh token) forever until aborted. */
export function followBoard(s: Settings, ws: string, onEvent: (e: BoardEvent) => void,
                            signal: AbortSignal): Promise<void> {
  return openStream({
    url: async () => {
      const { token } = await api<{ token: string }>(s, `/board/workspaces/${ws}/stream_token`,
                                                     { method: "POST" });
      return `/board/workspaces/${ws}/stream?token=${encodeURIComponent(token)}`;
    },
    onMessage: (m) => onEvent(JSON.parse(m.data) as BoardEvent),
    signal,
  });
}
```

`web/src/api/agent.ts`:

```ts
// Agent service (lens-agent) REST + run event stream, reached at /agent/*.
import type { AgentEvent } from "../state/journal";
import { api, type Settings } from "./http";
import { openStream } from "./sse";

export interface RunInfo {
  id: string;
  workspace_id: string;
  text: string;
  mentions: string[];
  status: "running" | "done" | "failed" | "cancelled";
  created_at: string;
}

export const startRun = (s: Settings, workspace_id: string, text: string, mentions: string[]) =>
  api<{ run_id: string; stream_token: string }>(s, "/agent/runs",
                                                 { method: "POST", body: { workspace_id, text, mentions } });
export const cancelRun = (s: Settings, runId: string) =>
  api<{ run_id: string }>(s, `/agent/runs/${runId}/cancel`, { method: "POST" });
export const listRuns = (s: Settings, ws: string, limit = 5) =>
  api<{ active: RunInfo | null; runs: RunInfo[] }>(s, `/agent/runs?workspace_id=${ws}&limit=${limit}`);
export const getCall = (s: Settings, runId: string, callId: string) =>
  api<{ server: string; tool: string; args: unknown; payload: unknown }>(
    s, `/agent/runs/${runId}/calls/${callId}`);

/** Streams one run from the start (or `after`) until `done`. */
export function followRun(s: Settings, runId: string, onEvent: (e: AgentEvent) => void,
                          signal: AbortSignal, firstToken?: string): Promise<void> {
  let token = firstToken;
  let finished = false;
  return openStream({
    url: async () => {
      if (!token) {
        token = (await api<{ stream_token: string }>(s, `/agent/runs/${runId}/stream_token`,
                                                     { method: "POST" })).stream_token;
      }
      const url = `/agent/runs/${runId}/events?token=${encodeURIComponent(token)}`;
      token = undefined; // next reconnect gets a fresh one
      return url;
    },
    onMessage: (m) => {
      const ev = JSON.parse(m.data) as AgentEvent;
      if (ev.type === "done") finished = true;
      onEvent(ev);
    },
    finished: () => finished,
    signal,
  });
}
```

- [ ] **Step 2: Page and styles** — `web/index.html`:

```html
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Lens</title>
</head>
<body>
  <div id="net"></div>

  <div class="top">
    <span class="pill" id="wsPill">нет расследования</span>
    <select id="wsSel" title="Расследование"></select>
    <button id="newWs" title="Новое расследование">＋</button>
    <button id="cfgBtn" title="Настройки">⚙</button>
  </div>

  <div class="journal" id="journal"></div>
  <div class="notes" id="notes"></div>
  <div class="toast" id="toast"></div>

  <div class="bottom">
    <div class="hint">клик по объекту = @объект · Enter — отправить · «скрой X», «отмени», «это одно и то же» · «стоп» — остановить</div>
    <div class="box" id="box"><input id="q" placeholder="встречи Путина в Китае" autocomplete="off"></div>
    <div class="status"><span id="srv">—</span><span id="st">готово</span></div>
  </div>

  <div class="modal" id="cfg" hidden><div class="card">
    <b>Подключение</b>
    <label>X-API-Key (LENS_API_KEYS)<input id="cKey" type="password"></label>
    <div class="row"><button id="cSave">Сохранить</button></div>
  </div></div>

  <div class="modal" id="detail" hidden><div class="card wide">
    <div class="row between"><b id="dTitle"></b><button id="dClose">✕</button></div>
    <pre id="dBody"></pre>
  </div></div>

  <script type="module" src="/src/main.ts"></script>
</body>
</html>
```

`web/src/style.css`:

```css
:root{--bg:#0f1115;--panel:#141820;--line:#262c36;--txt:#d7dce4;--mut:#7d8696;--sel:#f25f9c;--ok:#3ccf6e;--err:#e5484d;--call:#8fb3ff}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--txt);font:13px/1.4 -apple-system,Segoe UI,Roboto,sans-serif;overflow:hidden}
#net{position:absolute;inset:0;background-image:radial-gradient(#1a1f28 1px,transparent 1px);background-size:20px 20px}
.top{position:absolute;left:50%;transform:translateX(-50%);top:14px;display:flex;gap:8px;align-items:center;z-index:5}
.pill{border:1px solid var(--line);border-radius:14px;padding:4px 12px;background:var(--panel);color:var(--mut);font-size:12px}
.pill b{color:var(--txt)}
select,button,input{font:inherit;color:var(--txt);background:#1a1f29;border:1px solid var(--line);border-radius:8px;padding:4px 8px}
button{cursor:pointer}button:hover{border-color:#3a4353}
.bottom{position:absolute;left:50%;transform:translateX(-50%);bottom:22px;width:min(780px,94vw);z-index:5}
.hint{color:var(--mut);font-size:11px;margin:0 0 6px 4px}
.box{display:flex;flex-wrap:wrap;align-items:center;gap:6px;border:1px solid #333b48;border-radius:14px;padding:10px 12px;background:var(--panel);box-shadow:0 10px 30px #000a}
.box.running{border-color:#5a4a20}
.chip{border:1px solid var(--sel);color:var(--sel);border-radius:10px;padding:1px 7px;font-size:12px;cursor:pointer;white-space:nowrap}
.chip:hover{text-decoration:line-through}
#q{flex:1;min-width:200px;background:none;border:0;font-size:15px;outline:none;padding:2px}
.status{margin:6px 4px 0;font-size:11px;color:var(--mut);display:flex;justify-content:space-between;gap:10px}
.up{color:var(--ok)}.down{color:var(--err)}
.toast{position:absolute;left:50%;transform:translateX(-50%);bottom:120px;max-width:640px;background:#1b2130;border:1px solid var(--line);border-radius:10px;padding:8px 12px;z-index:6;display:none}
.toast.err{border-color:var(--err)}
.notes{position:absolute;right:16px;top:60px;width:340px;max-height:45vh;overflow:auto;z-index:4;display:flex;flex-direction:column;gap:8px}
.note{border-left:2px solid var(--mut);padding:6px 10px;background:#0f1115e6;color:#c3cad6;border-radius:0 8px 8px 0}
.cite{color:var(--sel);cursor:pointer}
.journal{position:absolute;left:16px;top:60px;bottom:150px;width:360px;overflow:auto;z-index:4;display:flex;flex-direction:column;gap:10px}
.run{background:#12151bcc;border:1px solid var(--line);border-radius:10px;padding:8px 10px;font-size:12px}
.run .h{display:flex;justify-content:space-between;gap:8px;margin-bottom:4px}
.run .h b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.badge{font-size:11px;color:var(--mut)}.badge.running{color:#e0a030}.badge.failed{color:var(--err)}.badge.done{color:var(--ok)}
.line{white-space:pre-wrap;word-break:break-word;margin:2px 0}
.line.sources{color:var(--mut);font-size:11px}
.line.call{color:var(--call);font-family:ui-monospace,monospace;font-size:11px}
.line.result{color:var(--mut);font-family:ui-monospace,monospace;font-size:11px}
.line.result.bad,.line.error{color:var(--err)}
.line.final{border-top:1px solid var(--line);padding-top:4px;margin-top:4px}
.line .more{color:var(--call);cursor:pointer;margin-left:6px;text-decoration:underline}
details.line summary{color:var(--mut);cursor:pointer;font-size:11px}
.modal{position:absolute;inset:0;background:#000b;z-index:10;display:flex;align-items:center;justify-content:center}
.modal[hidden]{display:none}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;width:420px;display:flex;flex-direction:column;gap:10px}
.card.wide{width:min(900px,92vw);max-height:80vh}
.card pre{overflow:auto;margin:0;font:11px ui-monospace,monospace;color:#c3cad6}
.card label{font-size:12px;color:var(--mut)}.card input{width:100%}
.row{display:flex;gap:8px;justify-content:flex-end;align-items:center}.row.between{justify-content:space-between}
```

- [ ] **Step 3: UI pieces** — `web/src/ui/dom.ts`:

```ts
export const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

export const esc = (s: unknown) =>
  String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" })[c]!);

let toastTimer: ReturnType<typeof setTimeout> | undefined;
export function toast(text: string, err = false): void {
  const el = $("toast");
  el.textContent = text;
  el.className = "toast" + (err ? " err" : "");
  el.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.style.display = "none"), err ? 9000 : 5000);
}
```

`web/src/ui/journal.ts`:

```ts
// Journal panel: one block per run — calls, results («подробнее» = full payload), text,
// collapsed thinking, final answer, errors in red.
import type { RunJournal } from "../state/journal";
import { esc } from "./dom";

const STATUS: Record<string, string> = { running: "идёт", done: "готово", failed: "ошибка", cancelled: "остановлено" };

export function renderJournal(el: HTMLElement, runs: RunJournal[],
                              onDetails: (runId: string, callId: string) => void): void {
  el.innerHTML = runs.map((j) => `
    <div class="run" data-run="${esc(j.runId)}">
      <div class="h"><b title="${esc(j.input)}">${esc(j.input || "…")}</b>
        <span class="badge ${j.status}">${STATUS[j.status] ?? j.status}</span></div>
      ${j.lines.map((l) => l.kind === "thinking"
        ? `<details class="line"><summary>размышления</summary>${esc(l.text)}</details>`
        : `<div class="line ${l.kind}${l.ok === false ? " bad" : ""}">${esc(l.text)}${
            l.kind === "result" && l.ok !== false && l.callId
              ? `<span class="more" data-call="${esc(l.callId)}">подробнее</span>` : ""}</div>`).join("")}
    </div>`).join("");
  el.querySelectorAll<HTMLElement>(".more").forEach((m) => {
    m.onclick = () => onDetails(m.closest<HTMLElement>(".run")!.dataset.run!, m.dataset.call!);
  });
  el.scrollTop = el.scrollHeight;
}
```

`web/src/ui/notes.ts`:

```ts
// Notes (answers on the board): [[key]] becomes a clickable citation of a live object.
import { canon, type BoardState } from "../state/board";
import { esc } from "./dom";

export function renderNotes(el: HTMLElement, st: BoardState, onCite: (key: string) => void): void {
  const labels = new Map(st.objects.filter((o) => !o.hidden).map((o) => [o.key, o.label]));
  el.innerHTML = st.notes.slice(-4).reverse().map((n) => {
    const html = esc(n.text).replace(/\[\[([^\]]+)\]\]/g, (_, raw: string) => {
      const k = canon(st, raw);
      const label = labels.get(k);
      return label ? `<span class="cite" data-k="${esc(k)}">${esc(label)}</span>` : esc(raw.split(":").pop());
    });
    return `<div class="note">${html}</div>`;
  }).join("");
  el.querySelectorAll<HTMLElement>(".cite").forEach((c) => (c.onclick = () => onCite(c.dataset.k!)));
}
```

- [ ] **Step 4: Wiring** — `web/src/main.ts`:

```ts
import "./style.css";
import { cancelRun, followRun, getCall, listRuns, startRun } from "./api/agent";
import { createWorkspace, followBoard, getBoard, listWorkspaces, pin, type BoardEvent } from "./api/board";
import { HttpError, loadSettings, saveSettings } from "./api/http";
import { VisRenderer } from "./render/vis";
import type { BoardRenderer } from "./render/types";
import { toView } from "./render/viewModel";
import { applyOps, type BoardState } from "./state/board";
import { decide, toggleMention } from "./state/input";
import { newJournal, reduce, type RunJournal } from "./state/journal";
import { $, esc, toast } from "./ui/dom";
import { renderJournal } from "./ui/journal";
import { renderNotes } from "./ui/notes";

const settings = loadSettings();
const renderer: BoardRenderer = new VisRenderer(); // swap the board engine here
renderer.mount($("net"));

let ws: string | null = null;
let board: BoardState | null = null;
let title = "";
let mentions: string[] = [];
let journals: RunJournal[] = [];
let activeRun: string | null = null;
let boardAbort: AbortController | null = null;
let runsAbort: AbortController | null = null;
let refetchTimer: ReturnType<typeof setTimeout> | undefined;

const showErr = (e: unknown) => toast(e instanceof Error ? e.message : String(e), true);
const labelOf = (k: string) => board?.objects.find((o) => o.key === k)?.label ?? k;

// ── board ────────────────────────────────────────────────────────────
function draw(): void {
  if (!board) return;
  const latest = journals[journals.length - 1]?.runId;
  renderer.render(toView(board, mentions, latest));
  const shown = board.objects.filter((o) => !o.hidden).length;
  $("wsPill").innerHTML = `<b>${esc(title)}</b> · объектов ${shown}`;
  renderNotes($("notes"), board, (k) => renderer.focus(k));
}

async function refetch(): Promise<void> {
  if (!ws) return;
  const r = await getBoard(settings, ws);
  board = r.state;
  title = r.workspace.title;
  draw();
}

function scheduleRefetch(): void {
  clearTimeout(refetchTimer);
  refetchTimer = setTimeout(() => refetch().catch(showErr), 150);
}

function onBoardEvent(e: BoardEvent): void {
  if (e.type === "ops" && board) {
    const next = applyOps(board, e.ops);
    if (next) {
      board = next;
      draw();
      return;
    }
  }
  scheduleRefetch(); // ready, resync, or ops that need the server's fold
}

// ── runs / journal ───────────────────────────────────────────────────
function drawJournal(): void {
  renderJournal($("journal"), journals, async (runId, callId) => {
    try {
      const c = await getCall(settings, runId, callId);
      $("dTitle").textContent = `${c.server}.${c.tool} · ${callId}`;
      $("dBody").textContent = JSON.stringify({ args: c.args, result: c.payload }, null, 2);
      $("detail").hidden = false;
    } catch (e) {
      showErr(e);
    }
  });
}

function setRunning(runId: string | null): void {
  activeRun = runId;
  $("box").classList.toggle("running", !!runId);
  $<HTMLInputElement>("q").placeholder = runId ? "идёт запрос… «стоп» — остановить" : "встречи Путина в Китае";
  $("st").textContent = runId ? "агент работает…" : "готово";
}

function follow(runId: string, text: string, runMentions: string[], live: boolean, token?: string): void {
  journals.push(newJournal(runId, text, runMentions));
  journals = journals.slice(-5);
  if (live) setRunning(runId);
  drawJournal();
  followRun(settings, runId, (ev) => {
    const i = journals.findIndex((j) => j.runId === runId);
    if (i < 0) return;
    journals[i] = reduce(journals[i], ev);
    drawJournal();
    if (ev.type === "done" && activeRun === runId) {
      setRunning(null);
      $("st").textContent = { done: "готово", failed: "ошибка", cancelled: "остановлено" }[ev.status as string] ?? "";
      draw();
    }
  }, runsAbort!.signal, token).catch(showErr);
}

// ── workspace ────────────────────────────────────────────────────────
async function openWorkspace(id: string): Promise<void> {
  boardAbort?.abort();
  runsAbort?.abort();
  ws = id || null;
  board = null;
  mentions = [];
  journals = [];
  setRunning(null);
  drawChips();
  drawJournal();
  renderer.render({ nodes: [], edges: [] });
  $("notes").innerHTML = "";
  if (!ws) {
    $("wsPill").textContent = "нет расследования";
    return;
  }
  boardAbort = new AbortController();
  runsAbort = new AbortController();
  followBoard(settings, ws, onBoardEvent, boardAbort.signal).catch(showErr);
  const { active, runs } = await listRuns(settings, ws, 5);
  for (const r of runs.filter((r) => r.id !== active?.id).reverse()) follow(r.id, r.text, r.mentions, false);
  if (active) follow(active.id, active.text, active.mentions, true);
}

async function loadWorkspaces(select?: string): Promise<void> {
  const list = await listWorkspaces(settings);
  $("wsSel").innerHTML = `<option value="">— расследование —</option>` +
    list.map((w) => `<option value="${esc(w.id)}">${esc(w.title)}</option>`).join("");
  if (select) $<HTMLSelectElement>("wsSel").value = select;
}

// ── input ────────────────────────────────────────────────────────────
function drawChips(): void {
  document.querySelectorAll("#box .chip").forEach((e) => e.remove());
  for (const k of mentions) {
    const c = document.createElement("span");
    c.className = "chip";
    c.textContent = "@" + labelOf(k);
    c.title = `${k} (клик — убрать)`;
    c.onclick = () => { mentions = toggleMention(mentions, k); drawChips(); draw(); };
    $("box").insertBefore(c, $("q"));
  }
}

async function submit(text: string): Promise<void> {
  const d = decide(text, !!activeRun);
  if (d === "ignore") return;
  if (d === "busy") return toast("Идёт запрос. «стоп» — остановить его.");
  if (d === "stop") {
    await cancelRun(settings, activeRun!);
    $<HTMLInputElement>("q").value = "";
    return;
  }
  if (!ws) return toast("Сначала создай или выбери расследование (＋ сверху).");
  try {
    const r = await startRun(settings, ws, text, mentions);
    const sent = mentions;
    $<HTMLInputElement>("q").value = "";
    mentions = [];
    drawChips();
    follow(r.run_id, text, sent, true, r.stream_token);
  } catch (e) {
    if (e instanceof HttpError && e.status === 409) {
      toast("В этом расследовании уже идёт запрос.");
      const { active } = await listRuns(settings, ws, 1);
      if (active && !journals.some((j) => j.runId === active.id)) {
        follow(active.id, active.text, active.mentions, true);
      }
    } else showErr(e);
  }
}

$<HTMLInputElement>("q").addEventListener("keydown", (e) => {
  const q = e.target as HTMLInputElement;
  if (e.key === "Backspace" && !q.value && mentions.length) {
    mentions = mentions.slice(0, -1);
    drawChips();
    draw();
    return;
  }
  if (e.key === "Enter") submit(q.value.trim()).catch(showErr);
});

renderer.on("select", (k) => { mentions = toggleMention(mentions, k); drawChips(); draw(); $("q").focus(); });
renderer.on("dragEnd", (k, pos) => { if (ws && pos) pin(settings, ws, k, pos.x, pos.y).catch(showErr); });
renderer.on("open", (k) => {
  const o = board?.objects.find((x) => x.key === k);
  if (o) toast(`${o.label} · ${o.type}${o.description ? ` — ${o.description}` : ""}`);
});

// ── chrome ───────────────────────────────────────────────────────────
async function health(): Promise<void> {
  const probe = async (path: string) => (await fetch(path).then((r) => r.ok).catch(() => false));
  const [b, a] = await Promise.all([probe("/board/health"), probe("/agent/health")]);
  $("srv").innerHTML = `доска <span class="${b ? "up" : "down"}">●</span> · агент <span class="${a ? "up" : "down"}">●</span>`;
}

$<HTMLSelectElement>("wsSel").onchange = (e) => openWorkspace((e.target as HTMLSelectElement).value).catch(showErr);
$("newWs").onclick = async () => {
  const t = prompt("Название расследования", "Новое расследование");
  if (!t) return;
  try {
    const w = await createWorkspace(settings, t);
    await loadWorkspaces(w.id);
    await openWorkspace(w.id);
  } catch (e) {
    showErr(e);
  }
};
$("cfgBtn").onclick = () => { $<HTMLInputElement>("cKey").value = settings.key; $("cfg").hidden = false; };
$("cSave").onclick = () => {
  settings.key = $<HTMLInputElement>("cKey").value.trim();
  saveSettings(settings);
  $("cfg").hidden = true;
  boot().catch(showErr);
};
$("dClose").onclick = () => { $("detail").hidden = true; };

async function boot(): Promise<void> {
  await health();
  if (!settings.key) {
    $("cfg").hidden = false;
    return;
  }
  await loadWorkspaces();
}

boot().catch(showErr);
setInterval(() => health().catch(() => {}), 15000);
```

- [ ] **Step 5: Build**

Run: `cd web && npx vitest run && npm run build`
Expected: 16 passed; build succeeds (`dist/` ~550 kB JS, no chunk warning).

- [ ] **Step 6: Dev fake stack** — `scripts/lens_fake_stack.py`:

```python
"""Dev-only fake Lens stack: board (memory) + lens-agent (scripted model, no LLM) + fake KB.

For web work without the real stack:
    uv run python scripts/lens_fake_stack.py      # :18010 board, :18011 kb, :18020 agent
    cd web && LENS_BOARD_URL=http://127.0.0.1:18010 LENS_AGENT_URL=http://127.0.0.1:18020 npm run dev
API key in the page settings: dev.  Every request replays the same scripted run.
"""
import asyncio

import uvicorn
from pydantic import SecretStr

from src.lens.app import LensDeps
from src.lens.app import create_app as lens_app
from src.lens.config import lens_settings
from src.lens.events import EventBus
from src.lens.store import MemoryLensStore
from src.lens_agent.app import AgentDeps
from src.lens_agent.app import create_app as agent_app
from src.lens_agent.config import AgentSettings, McpEntry
from src.lens_agent.runner import Runner
from src.lens_agent.store import MemoryAgentStore
from tests.test_lens_agent.helpers import kb_source, scripted

lens_settings.api_keys = "dev"
lens_settings.stream_secret = SecretStr("s3cret")
lens_settings.board_mcp_token = SecretStr("btok")


def model():
    return scripted(
        [("board_get_board", {})],
        [("kb_find_entity", {"name": "Росатом"})],
        [("board_add_objects", {"objects": [
            {"id": "E1", "type": "organization", "label": "Росатом", "call_id": "c2",
             "description": "госкорпорация"},
            {"id": "E2", "type": "person", "label": "Лихачёв", "call_id": "c2"}]})],
        [("board_add_relations", {"relations": [
            {"from": "kb:e2", "to": "kb:e1", "kind": "работает_в", "call_id": "c2"}]})],
        "Росатом возглавляет [[kb:e2]]; на доске два объекта.")


async def main():
    board = lens_app(LensDeps(store=MemoryLensStore(), bus=EventBus()))
    kb, _ = kb_source()
    kb_http = kb.http_app(path="/mcp")
    settings = AgentSettings(mcp=[
        McpEntry(name="kb", url="http://127.0.0.1:18011/mcp", namespace="kb"),
        McpEntry(name="board", url="http://127.0.0.1:18010/mcp/mcp", token="btok", role="board")])
    store, bus = MemoryAgentStore(), EventBus()
    agent = agent_app(AgentDeps(store=store, bus=bus, settings=settings,
                                runner=Runner(store, bus, settings, model)))
    servers = [uvicorn.Server(uvicorn.Config(a, host="127.0.0.1", port=p, log_level="warning"))
               for a, p in ((board, 18010), (kb_http, 18011), (agent, 18020))]
    await asyncio.gather(*(s.serve() for s in servers))


asyncio.run(main())
```

Run: `uv run --frozen ruff check scripts/lens_fake_stack.py` — clean.

- [ ] **Step 7: Smoke in a browser (local only, no LLM, no running stack)**

```bash
uv run python scripts/lens_fake_stack.py &
cd web && LENS_BOARD_URL=http://127.0.0.1:18010 LENS_AGENT_URL=http://127.0.0.1:18020 npx vite --port 5174 &
curl -s -X POST http://localhost:5174/board/workspaces -H 'X-API-Key: dev' -H 'Content-Type: application/json' -d '{"title":"Смоук"}'
```

Open `http://localhost:5174`, key `dev`, pick «Смоук», send «Росатом». Expected: journal `kb ✓ · board ✓`, four calls with `2 эл.`/`1 эл.` on board writes, «подробнее» opens every call; two nodes (Росатом, Лихачёв) joined by `работает_в`; note «Росатом возглавляет Лихачёв…» with the name clickable; the counter says `объектов 2`; the answer appears once. Stop both processes afterwards.

- [ ] **Step 8: Commit (local)**

```bash
git add web/index.html web/src/style.css web/src/api web/src/ui web/src/main.ts scripts/lens_fake_stack.py
git commit -m "feat(lens-web): shell — input with @mentions and «стоп», journal, notes; dev fake stack"
```

---

### Task 6: Container and compose

**Files:**
- Create: `web/Dockerfile`, `web/nginx.conf`, `web/.dockerignore`
- Modify: `.dockerignore`, `docker-compose.prod.yml`

**Interfaces:**
- Produces: services `lens` (healthcheck `/lens/v1/health`, no published port, `LENS_BOARD_MCP_TOKEN` required), `lens-agent` (port 8020 internal, healthcheck `/health`, `LENS_AGENT_MCP` with kb-tools, kb-stats, kb-search `enabled=${LENS_AGENT_KB_SEARCH:-false}`, board), `lens-web` (`${LENS_WEB_PORT:-8010}:80`).

- [ ] **Step 1: Image** — `web/Dockerfile`:

```dockerfile
# lens-web: static build served by nginx, which also proxies the two backends.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
```

`web/nginx.conf`:

```nginx
# Same-origin front door: the browser only ever talks to lens-web.
#   /board/*  → lens        (/lens/v1/*)   board REST + board SSE
#   /agent/*  → lens-agent  (/*)           runs REST + run SSE
# The board MCP (/mcp on lens) is deliberately NOT proxied.
server {
    listen 80;
    root /usr/share/nginx/html;

    location / {
        try_files $uri /index.html;
    }

    location /board/ {
        proxy_pass http://lens:8010/lens/v1/;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 3600s;  # idle board stream pings every 15 s
    }

    location /agent/ {
        proxy_pass http://lens-agent:8020/;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 720s;  # ≥ LENS_AGENT_RUN_TIMEOUT_S (600) + 60
    }
}
```

`web/.dockerignore`: `node_modules` and `dist` (one per line). Root `.dockerignore`: append a line `web` (the app image does not need it).

- [ ] **Step 2: Compose**

```diff
diff --git a/docker-compose.prod.yml b/docker-compose.prod.yml
index 3249edf..aa0c8f1 100644
--- a/docker-compose.prod.yml
+++ b/docker-compose.prod.yml
@@ -225,11 +225,11 @@ services:
       postgres: {condition: service_healthy}
     restart: unless-stopped
 
-  # Lens — object-centric research workspace (agent + API). Talks to the KB only
-  # through its MCP servers, exactly like any future external source. All KB servers
-  # share the "kb" namespace so one entity gets one canvas key. MCP auth = a key from
-  # API_KEYS (build_sse_auth); Lens's own clients use LENS_API_KEYS. Lens reconnects
-  # lazily, so service_started is enough for the MCP dependencies.
+  # Lens v2 (docs/superpowers/specs/2026-09-28-lens-v2-design.md): three services, only
+  # lens-web is published.  lens = board service (op log, board SSE, board MCP at /mcp/mcp);
+  # lens-agent = PydanticAI agent over the MCP list below; lens-web = static UI + nginx
+  # proxy (/board/* → lens, /agent/* → lens-agent).  KB MCP auth = a key from API_KEYS
+  # (LENS_MCP_TOKEN); the board MCP has its own token (LENS_BOARD_MCP_TOKEN).
   lens:
     <<: [*app-build]
     command: ["uvicorn", "src.lens.app:app", "--host", "0.0.0.0", "--port", "8010"]
@@ -238,12 +238,9 @@ services:
       LENS_API_KEYS: ${LENS_API_KEYS:?set LENS_API_KEYS}
       LENS_STREAM_SECRET: ${LENS_STREAM_SECRET:-}
       LENS_CORS_ORIGINS: ${LENS_CORS_ORIGINS:-http://localhost:5173}
-      # v2: lens-agent writes the board through /mcp/mcp with this bearer token (empty =
-      # board MCP refuses every call). The old /input path is off unless LENS_LEGACY_INPUT.
-      LENS_BOARD_MCP_TOKEN: ${LENS_BOARD_MCP_TOKEN:-}
+      LENS_BOARD_MCP_TOKEN: ${LENS_BOARD_MCP_TOKEN:?set LENS_BOARD_MCP_TOKEN}
+      # Old Router/Planner/Normalizer path (off): only these vars below are for it.
       LENS_LEGACY_INPUT: ${LENS_LEGACY_INPUT:-false}
-      # Role models (empty = LITELLM_MODEL_LARGE) and a Lens-only LLM timeout: a CPU-only
-      # local model needs minutes per planner/normalizer step, other services keep theirs.
       LENS_MODEL_PLANNER: ${LENS_MODEL_PLANNER:-}
       LENS_MODEL_NORMALIZER: ${LENS_MODEL_NORMALIZER:-}
       LENS_SAMPLE_CHARS: ${LENS_SAMPLE_CHARS:-6000}
@@ -252,15 +249,56 @@ services:
         [{"name":"kb-search","namespace":"kb","url":"http://mcp-search:9001/mcp","token":"${LENS_MCP_TOKEN:?set LENS_MCP_TOKEN to a key from API_KEYS}"},
          {"name":"kb-tools","namespace":"kb","url":"http://mcp-tools:9002/mcp","token":"${LENS_MCP_TOKEN:?set LENS_MCP_TOKEN to a key from API_KEYS}"},
          {"name":"kb-stats","namespace":"kb","url":"http://mcp-stats:9003/mcp","token":"${LENS_MCP_TOKEN:?set LENS_MCP_TOKEN to a key from API_KEYS}"}]
-    ports:
-      - "${LENS_PORT:-8010}:8010"
+    healthcheck:
+      test: ["CMD", "curl", "-sf", "http://localhost:8010/lens/v1/health"]
+      interval: 10s
+      timeout: 5s
+      retries: 6
     depends_on:
       postgres: {condition: service_healthy}
-      mcp-search: {condition: service_started}
+    restart: unless-stopped
+
+  # A new source = one more entry in LENS_AGENT_MCP (role "source"); kb-search is off by
+  # default (it runs its own LLM synthesis and blows the time budget of a local model).
+  lens-agent:
+    <<: [*app-build]
+    command: ["uvicorn", "src.lens_agent.app:app", "--host", "0.0.0.0", "--port", "8020"]
+    environment:
+      <<: *app-env
+      LENS_API_KEYS: ${LENS_API_KEYS:?set LENS_API_KEYS}
+      LENS_STREAM_SECRET: ${LENS_STREAM_SECRET:-}
+      LENS_AGENT_MODEL: ${LENS_AGENT_MODEL:-large}
+      LENS_AGENT_RUN_TIMEOUT_S: ${LENS_AGENT_RUN_TIMEOUT_S:-600}
+      LENS_AGENT_SOURCE_CALLS: ${LENS_AGENT_SOURCE_CALLS:-8}
+      LENS_AGENT_BOARD_CALLS: ${LENS_AGENT_BOARD_CALLS:-20}
+      LENS_AGENT_RESULT_CHARS: ${LENS_AGENT_RESULT_CHARS:-4000}
+      LENS_AGENT_MCP: >-
+        [{"name":"kb-tools","namespace":"kb","url":"http://mcp-tools:9002/mcp","token":"${LENS_MCP_TOKEN:?set LENS_MCP_TOKEN to a key from API_KEYS}","role":"source"},
+         {"name":"kb-stats","namespace":"kb","url":"http://mcp-stats:9003/mcp","token":"${LENS_MCP_TOKEN:?set LENS_MCP_TOKEN to a key from API_KEYS}","role":"source"},
+         {"name":"kb-search","namespace":"kb","url":"http://mcp-search:9001/mcp","token":"${LENS_MCP_TOKEN:?set LENS_MCP_TOKEN to a key from API_KEYS}","role":"source","enabled":${LENS_AGENT_KB_SEARCH:-false}},
+         {"name":"board","url":"http://lens:8010/mcp/mcp","token":"${LENS_BOARD_MCP_TOKEN:?set LENS_BOARD_MCP_TOKEN}","role":"board"}]
+    healthcheck:
+      test: ["CMD", "curl", "-sf", "http://localhost:8020/health"]
+      interval: 10s
+      timeout: 5s
+      retries: 6
+    depends_on:
+      postgres: {condition: service_healthy}
+      lens: {condition: service_healthy}
       mcp-tools: {condition: service_started}
       mcp-stats: {condition: service_started}
     restart: unless-stopped
 
+  lens-web:
+    build:
+      context: ./web
+    ports:
+      - "${LENS_WEB_PORT:-8010}:80"
+    depends_on:
+      lens: {condition: service_healthy}
+      lens-agent: {condition: service_healthy}
+    restart: unless-stopped
+
   # ───────────────────────── backing services ────────────────────────
 
   # ── Graph DB: NebulaGraph cluster (sole graph backend post-cutover) ──
```

- [ ] **Step 3: Verify**

```bash
LITELLM_BASE_URL=x LENS_API_KEYS=x LENS_MCP_TOKEN=tok LENS_BOARD_MCP_TOKEN=btok API_CORS_ORIGINS=x \
  docker compose -f docker-compose.prod.yml config --format json | python3 -c "
import json,sys; c=json.load(sys.stdin)['services']
print([(e['name'], e.get('enabled', True)) for e in json.loads(c['lens-agent']['environment']['LENS_AGENT_MCP'])])
print(c['lens-web']['ports'][0]['published'], c['lens'].get('ports'))"
docker build -q -t lens-web:check ./web && docker run --rm --add-host lens:127.0.0.1 --add-host lens-agent:127.0.0.1 lens-web:check nginx -t && docker rmi lens-web:check
```

Expected: `[('kb-tools', True), ('kb-stats', True), ('kb-search', False), ('board', True)]`, `8010 None`; nginx `syntax is ok`. (If Docker Hub times out on `node:22-alpine`/`nginx:1.27-alpine`, retry the pull — it is intermittent on this network.)

- [ ] **Step 4: Commit (local)**

```bash
graphify update .
git add web/Dockerfile web/nginx.conf web/.dockerignore .dockerignore docker-compose.prod.yml graphify-out
git commit -m "feat(lens): compose — lens-agent and lens-web; only lens-web published"
```

---

### Task 7: First live run (needs the user's «да» before each step)

**Files:** local `.env` only (gitignored).

- [ ] **Step 1: Secrets** — add to the local `.env` (never commit): `LENS_BOARD_MCP_TOKEN=$(openssl rand -hex 24)`; confirm `LENS_MCP_TOKEN`, `LENS_API_KEYS`, `LENS_STREAM_SECRET` are set; LM Studio context ≥16k for the loaded model.
- [ ] **Step 2: Build and start** (ask first): `docker compose -f docker-compose.prod.yml -f docker-compose.litellm.yml up -d --build lens lens-agent lens-web` with `COMPOSE_PROJECT_NAME=agent_v2`. Expected: all three healthy; `curl -s localhost:8010/agent/health` → `{"status":"up",…}`.
- [ ] **Step 3: The run** (ask first): open `http://localhost:8010`, workspace «Росатом», request «ростатом». Record: duration, source/board call counts, objects added, note text, any `error` events. This is the success criterion of spec §1; findings feed stage 6 (quality) and stage 7 (models).
