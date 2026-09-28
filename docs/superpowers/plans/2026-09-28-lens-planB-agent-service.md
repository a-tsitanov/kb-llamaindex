# Lens v2 — Plan B: Agent Service (lens-agent) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A generic agent service: it takes a request plus a list of MCP servers, runs a ready-made agent loop (PydanticAI) against the board MCP and the sources, and streams what it does over HTTP + SSE.

**Architecture:** New package `src/lens_agent/` (same repo image, own container later). Per run: connect every enabled MCP server (`MCPServerStreamableHTTP`, `tool_prefix = name`, board gets `X-Workspace`/`X-Run`), drive `Agent.run_stream_events`, map events to our own stream contract. A per-run `process_tool_call` hook (`RunCalls`) owns what the model cannot be trusted with: short `call_id`s, full-result storage + truncation, cache, soft budgets, source injection into board writes. Events are coalesced, persisted (`agent_*` tables) and fanned out live; SSE resumes with `Last-Event-ID`.

**Tech Stack:** Python 3.12, `pydantic-ai-slim[openai,mcp]` 1.28–1.30 (1.30.1 locked), FastAPI, psycopg 3 pool, FastMCP 3.3 (tests), pytest (asyncio_mode=auto), ruff, uv.

**Spec:** `docs/superpowers/specs/2026-09-28-lens-v2-design.md` (r2) — §4 «Agent stream», §6 «Agent service», §10. Roadmap stage 3. **Depends on Plan A** (`docs/superpowers/plans/2026-09-28-lens-planA-board-service.md`) being executed: tests use the real board MCP (`src.lens.board_mcp`) and `tests/test_lens/fakes.lifespan_of`.

## Global Constraints

- `pydantic-ai-slim[openai,mcp]>=1.28,<1.31` (1.31+ needs `openai>=2.29`; repo pins `openai<2`), `opentelemetry-api>=1.28,<1.44` (pydantic-ai ≤1.34 imports `opentelemetry._events`). `uv lock` must only ADD packages (pydantic-ai-slim, pydantic-graph, genai-prices, logfire-api, httpx2, httpcore2, truststore) — no version change of anything already locked.
- Run everything with `uv run --frozen`; after the lock change: `uv sync --frozen --extra dev`.
- Tests: `uv run --frozen pytest tests/test_lens tests/test_lens_agent -q`; lint: `uv run --frozen ruff check src/lens src/lens_agent tests/test_lens tests/test_lens_agent`. Both clean at the end of every task.
- Stream event types exactly: `run_started, thinking, text, tool_call, tool_result, final, error, done`; envelope `{run_id, seq, ts, type, ...}`; `seq` = SSE `id`; every run ends with exactly one `done{status: done|failed|cancelled}`.
- Defaults (env `LENS_AGENT_*`): `MODEL=large`, `RESULT_CHARS=4000`, `SOURCE_CALLS=8`, `BOARD_CALLS=20`, `REQUEST_LIMIT=30`, `RUN_TIMEOUT_S=600`, `TOOL_TIMEOUT_S=120`, `RETENTION_DAYS=30`; `MCP` = JSON list `[{name, url, namespace, token, role: source|board, enabled}]`.
- REST auth `X-API-Key` from `LENS_API_KEYS`; stream token = `src.lens.auth.make_stream_token(run_id, LENS_STREAM_SECRET)` (5 min).
- Only `headers=` is used to configure MCP clients: pydantic-ai 1.30's `http_client=` path is broken against mcp 1.27 (its factory yields a context manager, mcp now expects a client).
- No live model / stack calls in tests (FunctionModel + in-process FastMCP apps). Live checks need the user's «да».
- Commits: local only; never push.

## Review Focus

- The model cites a `call_id` that is not a source call of this run (a board call id, an id from another run, a typo) → the item is rejected back to the model with a reason, nothing unattributed reaches the board. Test: `test_unknown_call_id_is_rejected_back_to_the_model` (Task 4).
- A source MCP server is down at run start → reported `down` in `run_started`, the run continues with the rest; the board being down fails the run with a clear error. Tests: `test_down_source_is_reported_and_run_continues`, `test_missing_board_fails_run` (Task 4).
- The browser reconnects mid-run or after the run → it gets every event after `Last-Event-ID` exactly once, and a finished run's stream closes after replay. Tests: `test_sse_replays_after_last_event_id_then_follows_live_until_done`, `test_sse_of_a_finished_run_ends_after_replay` (Task 3), `test_last_event_id_header_resumes` (Task 5).
- The service restarts while a run is `running` → on start the run is marked `failed` («прервано перезапуском») and the workspace is free again; a crashed-but-not-restarted worker frees it after a stale heartbeat. Tests: `test_startup_marks_orphans_failed` (Task 5), `test_stale_heartbeat_frees_the_workspace` (Task 2).
- A slow client falls behind the live queue → it catches up from the store instead of losing events. Test: `test_slow_consumer_catches_up_from_the_store` (Task 3).

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml`, `uv.lock` (modify) | pydantic-ai window + otel pin |
| `src/lens_agent/__init__.py` | package |
| `src/lens_agent/config.py` | `AgentSettings` (`LENS_AGENT_*`), `McpEntry` |
| `src/lens_agent/store.py` | `agent_run` / `agent_event` / `agent_call_payload`; memory + Postgres stores; `Busy` |
| `src/lens_agent/stream.py` | `RunEmitter` (coalesce, persist, publish), `sse_events` (replay + live) |
| `src/lens_agent/calls.py` | `RunCalls`: the `process_tool_call` hook — ids, budgets, cache, truncation, source injection |
| `src/lens_agent/prompt.py` | instructions + user prompt with resolved mentions |
| `src/lens_agent/runner.py` | per-run MCP connections, agent loop, event mapping, deterministic note, errors/limits/cancel |
| `src/lens_agent/app.py` | HTTP API (§4), startup recovery, daily retention cleanup |
| `tests/test_lens_agent/helpers.py` | in-process world: fake KB MCP, real board MCP, scripted `FunctionModel` |

Diffs are against local `main` after Plan A. New files are given in full.

---

### Task 1: Dependencies

**Files:**
- Modify: `pyproject.toml`, `uv.lock`

**Interfaces:**
- Produces: importable `pydantic_ai` 1.30.x with `pydantic_ai.mcp.MCPServerStreamableHTTP`, `pydantic_ai.models.function.FunctionModel`, `pydantic_ai.models.openai.OpenAIChatModel`, `pydantic_ai.providers.openai.OpenAIProvider`.

- [ ] **Step 1: Add the dependencies**

```diff
diff --git a/pyproject.toml b/pyproject.toml
index af9e4bd..7180d0f 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -80,6 +80,13 @@ dependencies = [
     # default = nebula). Pinned to the 3.8 line to match the cluster (v3.8.x).
     # Was previously only in the dev .venv (ad-hoc), which broke the prod image.
     "nebula3-python>=3.8,<3.9",
+
+    # Lens agent service (src/lens_agent): ready-made agent loop over MCP toolsets.
+    # 1.31+ requires openai>=2.29 (we pin openai<2); 1.28–1.30 resolve with no changes
+    # to openai/fastmcp/mcp/pydantic.
+    "pydantic-ai-slim[openai,mcp]>=1.28,<1.31",
+    # pydantic-ai <=1.34 imports opentelemetry._events, removed in otel-api 1.44.
+    "opentelemetry-api>=1.28,<1.44",
 ]
 
 [project.optional-dependencies]
```

- [ ] **Step 2: Lock and sync**

Run: `uv lock && uv sync --frozen --extra dev`
Expected: `uv lock` prints only `Added …` lines (pydantic-ai-slim v1.30.1, pydantic-graph v1.30.1, genai-prices, logfire-api, httpx2, httpcore2, truststore); no `Updated`.

- [ ] **Step 3: Verify the window**

Run: `uv run --frozen python -c "import pydantic_ai, openai, fastmcp, opentelemetry.version as v; print(pydantic_ai.__version__, openai.__version__, fastmcp.__version__, v.__version__)"`
Expected: `1.30.1 1.109.1 3.3.1 1.42.1`.
Run: `uv run --frozen pytest tests/test_lens -q` — Expected: still green (177 passed, 5 skipped).

- [ ] **Step 4: Commit (local)**

```bash
git add pyproject.toml uv.lock
git commit -m "build(lens-agent): pydantic-ai-slim 1.28–1.30 + otel-api <1.44"
```

---

### Task 2: Settings and run store

**Files:**
- Create: `src/lens_agent/__init__.py`, `src/lens_agent/config.py`, `src/lens_agent/store.py`
- Test: `tests/test_lens_agent/__init__.py` (empty), `tests/test_lens_agent/test_store.py`

**Interfaces:**
- Produces:
  - `McpEntry(name, url, namespace=None, token: SecretStr|None, role: "source"|"board"="source", enabled=True)`, `.ns`
  - `AgentSettings` fields `mcp, model, result_chars, source_calls, board_calls, request_limit, run_timeout_s, tool_timeout_s, connect_timeout_s, retention_days, heartbeat_s`; `.enabled()`, `.board()`, `.llm_base_url()`, `.llm_api_key()`; module instance `agent_settings`
  - `RunRecord`, `AgentEvent` (`.envelope() -> {run_id, seq, ts, type, **data}`), `CallPayload`, `Busy(run_id)`
  - `AgentStore` protocol: `ensure_schema, create_run(ws, text, mentions, model, *, stale_after_s) -> RunRecord (raises Busy), get_run, active_run, list_runs(ws, limit), heartbeat, finish_run(run_id, status, *, error, usage), fail_orphans(reason) -> int, append_event(run_id, type, data) -> AgentEvent, list_events(run_id, after_seq=0), save_payload, get_payload(run_id, call_id), cleanup(older_than_days) -> int`
  - `MemoryAgentStore`, `PgAgentStore(pool)` (one active run per workspace = partial unique index `agent_run_one_active`)

- [ ] **Step 1: Write the failing test** — create empty `tests/test_lens_agent/__init__.py` and `tests/test_lens_agent/test_store.py`:

```python
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.lens_agent.store import Busy, CallPayload, MemoryAgentStore, PgAgentStore

PG_DSN = os.environ.get("LENS_TEST_PG_DSN")


@pytest.fixture(params=["memory", "pg"])
async def store(request):
    if request.param == "memory":
        yield MemoryAgentStore()
        return
    if not PG_DSN:
        pytest.skip("LENS_TEST_PG_DSN not set")
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(PG_DSN, min_size=1, max_size=2, open=False)
    await pool.open()
    s = PgAgentStore(pool)
    await s.ensure_schema()
    yield s
    await pool.close()


def ws() -> str:
    return f"ws-{uuid.uuid4().hex[:8]}"


async def test_one_active_run_per_workspace(store):
    w = ws()
    run = await store.create_run(w, "q", ["kb:1"], "large", stale_after_s=600)
    assert run.status == "running" and run.mentions == ["kb:1"]
    with pytest.raises(Busy) as e:
        await store.create_run(w, "q2", [], "large", stale_after_s=600)
    assert e.value.run_id == run.id
    assert (await store.active_run(w)).id == run.id
    other = await store.create_run(ws(), "q", [], "large", stale_after_s=600)
    assert other.status == "running"
    await store.finish_run(run.id, "done", usage={"requests": 2})
    again = await store.create_run(w, "q3", [], "large", stale_after_s=600)
    assert [r.id for r in await store.list_runs(w, 10)] == [again.id, run.id]
    assert (await store.get_run(run.id)).usage == {"requests": 2}


async def test_stale_heartbeat_frees_the_workspace(store):
    w = ws()
    run = await store.create_run(w, "q", [], "large", stale_after_s=600)
    if isinstance(store, MemoryAgentStore):
        store.runs[run.id].heartbeat_at = datetime.now(UTC) - timedelta(seconds=5)
    else:
        async with store.pool.connection() as conn:
            await conn.execute("UPDATE agent_run SET heartbeat_at = now() - interval '5 s' "
                               "WHERE id = %s", (run.id,))
    fresh = await store.create_run(w, "q2", [], "large", stale_after_s=1)
    old = await store.get_run(run.id)
    assert fresh.status == "running" and old.status == "failed" and old.error


async def test_fail_orphans_on_restart(store):
    run = await store.create_run(ws(), "q", [], "large", stale_after_s=600)
    assert await store.fail_orphans("прервано перезапуском") >= 1
    r = await store.get_run(run.id)
    assert r.status == "failed" and r.error == "прервано перезапуском" and r.finished_at


async def test_events_are_sequenced_and_filtered(store):
    run = await store.create_run(ws(), "q", [], "large", stale_after_s=600)
    a = await store.append_event(run.id, "run_started", {"model": "large"})
    b = await store.append_event(run.id, "text", {"delta": "при"})
    assert (a.seq, b.seq) == (1, 2)
    assert [e.type for e in await store.list_events(run.id, after_seq=1)] == ["text"]
    env = b.envelope()
    assert env["run_id"] == run.id and env["seq"] == 2 and env["delta"] == "при"


async def test_payload_roundtrip_and_cleanup(store):
    run = await store.create_run(ws(), "q", [], "large", stale_after_s=600)
    rec = CallPayload(run_id=run.id, call_id="c1", server="kb", tool="t", args={"a": 1},
                      payload={"x": [1, 2]})
    await store.save_payload(rec)
    assert (await store.get_payload(run.id, "c1")).payload == {"x": [1, 2]}
    assert await store.get_payload(run.id, "c9") is None
    await store.finish_run(run.id, "done")
    assert await store.cleanup(30) == 0
    if isinstance(store, MemoryAgentStore):
        store.runs[run.id].created_at -= timedelta(days=31)
    else:
        async with store.pool.connection() as conn:
            await conn.execute("UPDATE agent_run SET created_at = now() - interval '31 days' "
                               "WHERE id = %s", (run.id,))
    assert await store.cleanup(30) >= 1
    assert await store.get_run(run.id) is None
    assert await store.get_payload(run.id, "c1") is None
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run --frozen pytest tests/test_lens_agent/test_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens_agent'`.

- [ ] **Step 3: Implement** — `src/lens_agent/__init__.py`:

```python
"""Lens agent service: a ready-made agent loop (PydanticAI) over MCP servers, HTTP+SSE."""
```

`src/lens_agent/config.py`:

```python
"""lens-agent settings (env prefix ``LENS_AGENT_``).

``LENS_AGENT_MCP`` is a JSON list; a new source is one more entry, no code::

    [{"name": "kb-tools", "namespace": "kb", "url": "http://mcp-tools:9002/mcp",
      "token": "<key>", "role": "source"},
     {"name": "board", "url": "http://lens:8010/mcp/mcp", "token": "<LENS_BOARD_MCP_TOKEN>",
      "role": "board"}]

REST keys and the stream secret are shared with the board (``LENS_API_KEYS``,
``LENS_STREAM_SECRET``) — see ``src.lens.config``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.config import settings


class McpEntry(BaseModel):
    name: str
    url: str
    namespace: str | None = None
    token: SecretStr | None = None
    role: Literal["source", "board"] = "source"
    enabled: bool = True

    @field_validator("token", mode="before")
    @classmethod
    def _blank_token_is_none(cls, v: object) -> object:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return v

    @property
    def ns(self) -> str:
        return self.namespace or self.name


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LENS_AGENT_", env_file=".env",
                                      extra="ignore")

    mcp: list[McpEntry] = []
    model: str = "large"  # LiteLLM alias
    result_chars: int = 4000  # source result cut before it reaches the model
    source_calls: int = 8  # soft budget per run
    board_calls: int = 20  # soft budget per run
    request_limit: int = 30  # hard: model requests per run
    run_timeout_s: float = 600.0
    tool_timeout_s: float = 120.0
    connect_timeout_s: float = 10.0
    retention_days: int = 30
    heartbeat_s: float = 15.0

    def enabled(self) -> list[McpEntry]:
        return [e for e in self.mcp if e.enabled]

    def board(self) -> McpEntry | None:
        return next((e for e in self.enabled() if e.role == "board"), None)

    def llm_base_url(self) -> str:
        return settings.litellm.base_url

    def llm_api_key(self) -> str:
        return settings.litellm.api_key.get_secret_value()


agent_settings = AgentSettings()
```

`src/lens_agent/store.py`:

```python
"""lens-agent persistence: runs, their (coalesced) stream events, full tool results.

One active run per workspace: ``create_run`` refuses (``Busy``) while another run of the
workspace is ``running`` with a fresh heartbeat; a stale one is failed and replaced.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from psycopg import errors as pg_errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

RunStatus = Literal["running", "done", "failed", "cancelled"]

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_run (
    id text PRIMARY KEY,
    workspace_id text NOT NULL,
    text text NOT NULL,
    mentions jsonb NOT NULL DEFAULT '[]',
    model text NOT NULL,
    status text NOT NULL,
    error text,
    usage jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    heartbeat_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS agent_run_one_active
    ON agent_run (workspace_id) WHERE status = 'running';
CREATE INDEX IF NOT EXISTS agent_run_ws_created ON agent_run (workspace_id, created_at DESC);
CREATE TABLE IF NOT EXISTS agent_event (
    run_id text NOT NULL REFERENCES agent_run(id) ON DELETE CASCADE,
    seq integer NOT NULL,
    ts timestamptz NOT NULL DEFAULT now(),
    type text NOT NULL,
    data jsonb NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS agent_call_payload (
    run_id text NOT NULL REFERENCES agent_run(id) ON DELETE CASCADE,
    call_id text NOT NULL,
    server text NOT NULL,
    tool text NOT NULL,
    args jsonb NOT NULL,
    payload jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, call_id)
);
"""

_RUN_COLS = ("id, workspace_id, text, mentions, model, status, error, usage, created_at, "
             "finished_at, heartbeat_at")


class Busy(Exception):
    """The workspace already has an active run."""

    def __init__(self, run_id: str):
        super().__init__(run_id)
        self.run_id = run_id


class RunRecord(BaseModel):
    id: str
    workspace_id: str
    text: str
    mentions: list[str] = Field(default_factory=list)
    model: str
    status: RunStatus = "running"
    error: str | None = None
    usage: dict[str, Any] | None = None
    created_at: datetime
    finished_at: datetime | None = None
    heartbeat_at: datetime


class AgentEvent(BaseModel):
    run_id: str
    seq: int
    ts: datetime
    type: str
    data: dict[str, Any] = Field(default_factory=dict)

    def envelope(self) -> dict[str, Any]:
        """The wire shape: ``{run_id, seq, ts, type, ...fields}``."""
        return {"run_id": self.run_id, "seq": self.seq, "ts": self.ts.isoformat(),
                "type": self.type, **self.data}


class CallPayload(BaseModel):
    run_id: str
    call_id: str
    server: str
    tool: str
    args: dict[str, Any]
    payload: Any = None


class AgentStore(Protocol):
    async def ensure_schema(self) -> None: ...
    async def create_run(self, workspace_id: str, text: str, mentions: list[str], model: str,
                         *, stale_after_s: float) -> RunRecord: ...
    async def get_run(self, run_id: str) -> RunRecord | None: ...
    async def active_run(self, workspace_id: str) -> RunRecord | None: ...
    async def list_runs(self, workspace_id: str, limit: int) -> list[RunRecord]: ...
    async def heartbeat(self, run_id: str) -> None: ...
    async def finish_run(self, run_id: str, status: RunStatus, *, error: str | None = None,
                         usage: dict[str, Any] | None = None) -> None: ...
    async def fail_orphans(self, reason: str) -> int: ...
    async def append_event(self, run_id: str, type_: str, data: dict[str, Any]) -> AgentEvent: ...
    async def list_events(self, run_id: str, after_seq: int = 0) -> list[AgentEvent]: ...
    async def save_payload(self, rec: CallPayload) -> None: ...
    async def get_payload(self, run_id: str, call_id: str) -> CallPayload | None: ...
    async def cleanup(self, older_than_days: int) -> int: ...


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _now() -> datetime:
    return datetime.now(UTC)


class MemoryAgentStore:
    def __init__(self) -> None:
        self.runs: dict[str, RunRecord] = {}
        self.events: dict[str, list[AgentEvent]] = {}
        self.payloads: dict[tuple[str, str], CallPayload] = {}

    async def ensure_schema(self) -> None:
        return None

    async def create_run(self, workspace_id, text, mentions, model, *, stale_after_s):
        active = await self.active_run(workspace_id)
        if active is not None:
            if _now() - active.heartbeat_at <= timedelta(seconds=stale_after_s):
                raise Busy(active.id)
            await self.finish_run(active.id, "failed", error="зависший запуск снят")
        now = _now()
        run = RunRecord(id=_new_id(), workspace_id=workspace_id, text=text,
                        mentions=list(mentions), model=model, created_at=now, heartbeat_at=now)
        self.runs[run.id] = run
        self.events[run.id] = []
        return run

    async def get_run(self, run_id):
        return self.runs.get(run_id)

    async def active_run(self, workspace_id):
        return next((r for r in self.runs.values()
                     if r.workspace_id == workspace_id and r.status == "running"), None)

    async def list_runs(self, workspace_id, limit):
        runs = [r for r in self.runs.values() if r.workspace_id == workspace_id]
        return sorted(runs, key=lambda r: r.created_at, reverse=True)[:limit]

    async def heartbeat(self, run_id):
        if run_id in self.runs:
            self.runs[run_id].heartbeat_at = _now()

    async def finish_run(self, run_id, status, *, error=None, usage=None):
        r = self.runs[run_id]
        r.status, r.error, r.usage, r.finished_at = status, error, usage, _now()

    async def fail_orphans(self, reason):
        orphans = [r for r in self.runs.values() if r.status == "running"]
        for r in orphans:
            await self.finish_run(r.id, "failed", error=reason)
        return len(orphans)

    async def append_event(self, run_id, type_, data):
        evs = self.events.setdefault(run_id, [])
        ev = AgentEvent(run_id=run_id, seq=len(evs) + 1, ts=_now(), type=type_, data=data)
        evs.append(ev)
        return ev

    async def list_events(self, run_id, after_seq=0):
        return [e for e in self.events.get(run_id, []) if e.seq > after_seq]

    async def save_payload(self, rec):
        self.payloads[(rec.run_id, rec.call_id)] = rec

    async def get_payload(self, run_id, call_id):
        return self.payloads.get((run_id, call_id))

    async def cleanup(self, older_than_days):
        cutoff = _now() - timedelta(days=older_than_days)
        old = [r.id for r in self.runs.values()
               if r.status != "running" and r.created_at < cutoff]
        for rid in old:
            self.runs.pop(rid)
            self.events.pop(rid, None)
            for k in [k for k in self.payloads if k[0] == rid]:
                self.payloads.pop(k)
        return len(old)


class PgAgentStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool

    async def ensure_schema(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(SCHEMA_SQL)

    async def _one(self, sql: str, params: tuple) -> dict | None:
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(sql, params)
            return await cur.fetchone()

    async def create_run(self, workspace_id, text, mentions, model, *, stale_after_s):
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE agent_run SET status = 'failed', error = 'зависший запуск снят', "
                "finished_at = now() WHERE workspace_id = %s AND status = 'running' "
                "AND heartbeat_at < now() - make_interval(secs => %s)",
                (workspace_id, stale_after_s))
            try:
                # The partial unique index (one 'running' row per workspace) is the lock.
                async with conn.transaction():
                    cur = conn.cursor(row_factory=dict_row)
                    await cur.execute(
                        f"INSERT INTO agent_run (id, workspace_id, text, mentions, model, "
                        f"status) VALUES (%s, %s, %s, %s, %s, 'running') RETURNING {_RUN_COLS}",
                        (_new_id(), workspace_id, text, Jsonb(list(mentions)), model))
                    row = await cur.fetchone()
                return RunRecord.model_validate(row)
            except pg_errors.UniqueViolation:
                pass
        active = await self.active_run(workspace_id)
        raise Busy(active.id if active else "")

    async def get_run(self, run_id):
        row = await self._one(f"SELECT {_RUN_COLS} FROM agent_run WHERE id = %s", (run_id,))
        return RunRecord.model_validate(row) if row else None

    async def active_run(self, workspace_id):
        row = await self._one(f"SELECT {_RUN_COLS} FROM agent_run "
                              "WHERE workspace_id = %s AND status = 'running'", (workspace_id,))
        return RunRecord.model_validate(row) if row else None

    async def list_runs(self, workspace_id, limit):
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(f"SELECT {_RUN_COLS} FROM agent_run WHERE workspace_id = %s "
                              "ORDER BY created_at DESC LIMIT %s", (workspace_id, limit))
            return [RunRecord.model_validate(r) for r in await cur.fetchall()]

    async def heartbeat(self, run_id):
        async with self.pool.connection() as conn:
            await conn.execute("UPDATE agent_run SET heartbeat_at = now() WHERE id = %s",
                               (run_id,))

    async def finish_run(self, run_id, status, *, error=None, usage=None):
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE agent_run SET status = %s, error = %s, usage = %s, finished_at = now() "
                "WHERE id = %s",
                (status, error, Jsonb(usage) if usage is not None else None, run_id))

    async def fail_orphans(self, reason):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE agent_run SET status = 'failed', error = %s, finished_at = now() "
                "WHERE status = 'running'", (reason,))
            return cur.rowcount

    async def append_event(self, run_id, type_, data):
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (run_id,))
            cur = await conn.execute(
                "INSERT INTO agent_event (run_id, seq, type, data) "
                "SELECT %s, coalesce(max(seq), 0) + 1, %s, %s FROM agent_event "
                "WHERE run_id = %s RETURNING seq, ts",
                (run_id, type_, Jsonb(data), run_id))
            seq, ts = await cur.fetchone()
        return AgentEvent(run_id=run_id, seq=seq, ts=ts, type=type_, data=data)

    async def list_events(self, run_id, after_seq=0):
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute("SELECT run_id, seq, ts, type, data FROM agent_event "
                              "WHERE run_id = %s AND seq > %s ORDER BY seq", (run_id, after_seq))
            return [AgentEvent.model_validate(r) for r in await cur.fetchall()]

    async def save_payload(self, rec):
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO agent_call_payload (run_id, call_id, server, tool, args, payload) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (run_id, call_id) DO NOTHING",
                (rec.run_id, rec.call_id, rec.server, rec.tool, Jsonb(rec.args),
                 Jsonb(rec.payload)))

    async def get_payload(self, run_id, call_id):
        row = await self._one("SELECT run_id, call_id, server, tool, args, payload "
                              "FROM agent_call_payload WHERE run_id = %s AND call_id = %s",
                              (run_id, call_id))
        return CallPayload.model_validate(row) if row else None

    async def cleanup(self, older_than_days):
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM agent_run WHERE status <> 'running' "
                "AND created_at < now() - make_interval(days => %s)", (older_than_days,))
            return cur.rowcount
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run --frozen pytest tests/test_lens_agent/test_store.py -q`
Expected: 5 passed (memory), 5 skipped (pg). With a disposable Postgres (`LENS_TEST_PG_DSN=postgresql://…`, only with the user's go-ahead) the pg variants must pass too.
Run: `uv run --frozen ruff check src/lens_agent tests/test_lens_agent` — clean.

- [ ] **Step 5: Commit (local)**

```bash
git add src/lens_agent/__init__.py src/lens_agent/config.py src/lens_agent/store.py tests/test_lens_agent/__init__.py tests/test_lens_agent/test_store.py
git commit -m "feat(lens-agent): settings and run/event/payload store"
```

---

### Task 3: Event stream

**Files:**
- Create: `src/lens_agent/stream.py`
- Test: `tests/test_lens_agent/test_stream.py`

**Interfaces:**
- Consumes: Task 2 `AgentStore`, `AgentEvent`; existing `src.lens.events.EventBus` (keyed by run id here).
- Produces: `RunEmitter(store, bus, run_id, *, flush_s=0.25)` with `await delta(type, text)` (types `thinking`/`text`, coalesced), `await emit(type, **data) -> AgentEvent` (flushes pending delta first), `await flush()`, `await autoflush()` (background loop); bus messages `{"event": envelope}`. `sse_events(store, bus, run_id, last_event_id=0, *, ping_s=15.0)` async iterator of SSE frames `id/event/data`, ends after `done`.

- [ ] **Step 1: Write the failing test** — `tests/test_lens_agent/test_stream.py`:

```python
import asyncio
import json

from src.lens.events import EventBus
from src.lens_agent.store import MemoryAgentStore
from src.lens_agent.stream import RunEmitter, sse_events


async def _run(store):
    return await store.create_run("w", "q", [], "large", stale_after_s=600)


def parse(frames: list[str]) -> list[dict]:
    out = []
    for f in frames:
        if f.startswith(":"):
            continue
        lines = dict(line.split(": ", 1) for line in f.strip().splitlines())
        ev = json.loads(lines["data"])
        assert lines["id"] == str(ev["seq"]) and lines["event"] == ev["type"]
        out.append(ev)
    return out


async def test_deltas_are_coalesced_until_the_next_event():
    store, bus = MemoryAgentStore(), EventBus()
    run = await _run(store)
    em = RunEmitter(store, bus, run.id, flush_s=60)
    for ch in "при" + "вет":
        await em.delta("text", ch)
    await em.delta("thinking", "хм")
    await em.emit("final", answer="привет")
    evs = await store.list_events(run.id)
    assert [(e.type, e.data) for e in evs] == [
        ("text", {"delta": "привет"}), ("thinking", {"delta": "хм"}),
        ("final", {"answer": "привет"})]


async def test_autoflush_sends_a_paused_delta():
    store, bus = MemoryAgentStore(), EventBus()
    run = await _run(store)
    em = RunEmitter(store, bus, run.id, flush_s=0.05)
    task = asyncio.create_task(em.autoflush())
    await em.delta("text", "пауза")
    await asyncio.sleep(0.2)
    task.cancel()
    assert [e.data for e in await store.list_events(run.id)] == [{"delta": "пауза"}]


async def test_sse_replays_after_last_event_id_then_follows_live_until_done():
    store, bus = MemoryAgentStore(), EventBus()
    run = await _run(store)
    em = RunEmitter(store, bus, run.id)
    await em.emit("run_started", model="large")
    await em.emit("tool_call", call_id="c1")
    frames: list[str] = []

    async def read():
        async for f in sse_events(store, bus, run.id, last_event_id=1, ping_s=0.05):
            frames.append(f)

    reader = asyncio.create_task(read())
    await asyncio.sleep(0.1)  # replay done, a ping or two, now live
    await em.emit("tool_result", call_id="c1", ok=True)
    await em.emit("done", status="done")
    await asyncio.wait_for(reader, 1)
    assert [e["type"] for e in parse(frames)] == ["tool_call", "tool_result", "done"]
    assert any(f.startswith(": ping") for f in frames)


async def test_sse_of_a_finished_run_ends_after_replay():
    store, bus = MemoryAgentStore(), EventBus()
    run = await _run(store)
    em = RunEmitter(store, bus, run.id)
    await em.emit("final", answer="a")
    await em.emit("done", status="done")
    frames = [f async for f in sse_events(store, bus, run.id)]
    assert [e["seq"] for e in parse(frames)] == [1, 2]
    assert bus.subscriber_count(run.id) == 0


async def test_slow_consumer_catches_up_from_the_store():
    store, bus = MemoryAgentStore(), EventBus(queue_max=2)
    run = await _run(store)
    em = RunEmitter(store, bus, run.id)
    gen = sse_events(store, bus, run.id, ping_s=0.05)
    reader_frames: list[str] = []

    async def read():
        async for f in gen:
            reader_frames.append(f)
            await asyncio.sleep(0.02)  # slow

    reader = asyncio.create_task(read())
    await asyncio.sleep(0.01)
    for i in range(10):
        await em.emit("tool_call", call_id=f"c{i}")
    await em.emit("done", status="done")
    await asyncio.wait_for(reader, 2)
    assert [e["seq"] for e in parse(reader_frames)] == list(range(1, 12))
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run --frozen pytest tests/test_lens_agent/test_stream.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens_agent.stream'`.

- [ ] **Step 3: Implement** — `src/lens_agent/stream.py`:

```python
"""Run event stream: persist every event, fan it out live, replay on reconnect.

``thinking``/``text`` deltas are coalesced (flushed every ``flush_s`` or before the next
non-delta event), so a run is tens of rows, not thousands. Live subscribers receive the same
persisted events (with ``seq`` = SSE ``id``), so a reconnect with ``Last-Event-ID`` never
duplicates or loses text.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

from src.lens.events import EventBus
from src.lens_agent.store import AgentEvent, AgentStore

DELTA_TYPES = ("thinking", "text")
TERMINAL = "done"


class RunEmitter:
    """Single writer of one run's events (used from the run task only)."""

    def __init__(self, store: AgentStore, bus: EventBus, run_id: str, *, flush_s: float = 0.25):
        self.store, self.bus, self.run_id, self.flush_s = store, bus, run_id, flush_s
        self._buf_type: str | None = None
        self._buf: list[str] = []
        self._buf_since = 0.0
        self._lock = asyncio.Lock()

    async def delta(self, type_: str, text: str) -> None:
        if not text:
            return
        async with self._lock:
            if self._buf_type not in (None, type_):
                await self._flush()
            if self._buf_type is None:
                self._buf_type, self._buf_since = type_, time.monotonic()
            self._buf.append(text)
            if time.monotonic() - self._buf_since >= self.flush_s:
                await self._flush()

    async def emit(self, type_: str, **data: Any) -> AgentEvent:
        async with self._lock:
            await self._flush()
            return await self._write(type_, data)

    async def flush(self) -> None:
        async with self._lock:
            await self._flush()

    async def autoflush(self) -> None:
        """Run alongside the model stream: a pause in deltas still reaches the client."""
        while True:
            await asyncio.sleep(self.flush_s)
            async with self._lock:
                if self._buf_type and time.monotonic() - self._buf_since >= self.flush_s:
                    await self._flush()

    async def _flush(self) -> None:
        if self._buf_type is None:
            return
        type_, text = self._buf_type, "".join(self._buf)
        self._buf_type, self._buf = None, []
        await self._write(type_, {"delta": text})

    async def _write(self, type_: str, data: dict[str, Any]) -> AgentEvent:
        ev = await self.store.append_event(self.run_id, type_, data)
        self.bus.publish(self.run_id, {"event": ev.envelope()})
        return ev


def _frame(env: dict[str, Any]) -> str:
    return (f"id: {env['seq']}\nevent: {env['type']}\n"
            f"data: {json.dumps(env, ensure_ascii=False)}\n\n")


async def sse_events(
    store: AgentStore, bus: EventBus, run_id: str, last_event_id: int = 0,
    *, ping_s: float = 15.0,
) -> AsyncIterator[str]:
    """Replay persisted events after ``last_event_id``, then follow live until ``done``."""
    q = bus.subscribe(run_id)  # subscribe first: nothing written meanwhile is lost
    try:
        last = last_event_id
        for ev in await store.list_events(run_id, after_seq=last):
            yield _frame(ev.envelope())
            last = ev.seq
            if ev.type == TERMINAL:
                return
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=ping_s)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if msg.get("type") == "resync":  # slow consumer: catch up from the store
                q = bus.subscribe(run_id)
                missed = await store.list_events(run_id, after_seq=last)
            else:
                missed = [msg["event"]]
            for item in missed:
                env = item.envelope() if isinstance(item, AgentEvent) else item
                if env["seq"] <= last:
                    continue
                yield _frame(env)
                last = env["seq"]
                if env["type"] == TERMINAL:
                    return
    finally:
        bus.unsubscribe(run_id, q)
```

Ruling recorded here: live subscribers receive the coalesced, persisted events (≤250 ms behind the model) rather than raw deltas, so a reconnect with `Last-Event-ID` can never duplicate text.

- [ ] **Step 4: Run, expect pass**

Run: `uv run --frozen pytest tests/test_lens_agent/test_stream.py -q && uv run --frozen ruff check src/lens_agent tests/test_lens_agent`
Expected: 5 passed, ruff clean.

- [ ] **Step 5: Commit (local)**

```bash
git add src/lens_agent/stream.py tests/test_lens_agent/test_stream.py
git commit -m "feat(lens-agent): coalesced run event stream with SSE replay"
```

---

### Task 4: Tool-call guard and runner

**Files:**
- Create: `src/lens_agent/calls.py`, `src/lens_agent/prompt.py`, `src/lens_agent/runner.py`
- Test: `tests/test_lens_agent/helpers.py`, `tests/test_lens_agent/test_runner.py`

**Interfaces:**
- Consumes: Task 2 config/store, Task 3 `RunEmitter`; Plan A `BoardService`, `board_mcp_app`, board tool names (`get_board, find_on_board, get_object, add_objects, add_relations, add_note, hide, show, merge, undo`), `tests.test_lens.fakes.lifespan_of`.
- Produces:
  - `CallLimits(result_chars, source_calls, board_calls, tool_timeout_s)`; `RunCalls(run_id, store, emitter, limits)` with `.hook(entry)` (a pydantic-ai `ProcessToolCallback`), `.short_id(provider_id)`, `.seen(provider_id)`, `.registry`, `.counts`, `.note_written`, `.undone`. Model-visible source result = `"call_id=cN\n<result cut to result_chars>[\n…усечено, полный результат: call_id=cN]"`.
  - `INSTRUCTIONS`, `user_prompt(text, mentions: [{key,label,type}])`
  - `Runner(store, bus, settings, model_factory: () -> Model, server_factory=None)`: `await submit(ws, text, mentions) -> RunRecord` (raises `Busy`), `cancel(run_id) -> bool`, `await drain()`, `.tasks`; `http_server_factory(settings)`; `RunFailure(where, message)`.
  - Tool names seen by the model: `<entry.name>_<tool>` (e.g. `kb-tools_find_entity_by_name`, `board_add_objects`).

- [ ] **Step 1: Write the test world** — `tests/test_lens_agent/helpers.py`:

```python
"""In-process world for lens-agent tests: a fake KB source MCP, the real board MCP (memory
store), a scripted model. No sockets, no LLM."""

from __future__ import annotations

import asyncio
import functools
import json
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.client.streamable_http import streamablehttp_client
from pydantic_ai.mcp import MCPServerStreamableHTTP
from pydantic_ai.messages import ModelRequest, ModelResponse
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from src.lens.board import BoardService
from src.lens.board_mcp import board_mcp_app
from src.lens.events import EventBus
from src.lens.store import MemoryLensStore
from src.lens_agent.config import AgentSettings, McpEntry
from src.lens_agent.runner import Runner
from src.lens_agent.store import MemoryAgentStore
from tests.test_lens.fakes import lifespan_of

BOARD_TOKEN = "board-token"
KB_TOKEN = "kb-token"
ROSATOM = {"id": "E1", "name": "Росатом", "type": "organization"}
LIKHACHEV = {"id": "E2", "name": "Лихачёв", "type": "person"}


class AsgiMCPServer(MCPServerStreamableHTTP):
    """The production server class, but its HTTP goes to an in-process ASGI app.

    Headers still flow through the same ``headers=`` path as in production. (pydantic-ai
    1.30's ``http_client=`` path is broken against mcp 1.27, so it is not used anywhere.)
    """

    def __init__(self, url: str, *, app, **kw):
        super().__init__(url, **kw)
        self._app = app

    @property
    def _transport_client(self):
        app = self._app

        def factory(headers=None, timeout=None, auth=None):
            transport = (httpx.ASGITransport(app=app) if app is not None
                         else httpx.MockTransport(lambda r: httpx.Response(503)))
            return httpx.AsyncClient(transport=transport, headers=headers, timeout=timeout,
                                     auth=auth)

        return functools.partial(streamablehttp_client, httpx_client_factory=factory)


def kb_source() -> tuple[FastMCP, dict[str, int]]:
    """Fake KB MCP; ``hits`` counts real calls per tool."""
    mcp, hits = FastMCP(name="kb"), {}
    gate = asyncio.Event()

    def hit(name):
        hits[name] = hits.get(name, 0) + 1

    @mcp.tool
    def find_entity(name: str) -> dict:
        hit("find_entity")
        return {"entities": [ROSATOM, LIKHACHEV]}

    @mcp.tool
    def big() -> str:
        hit("big")
        return "x" * 10_000

    @mcp.tool
    def boom() -> str:
        hit("boom")
        raise ToolError("источник упал")

    @mcp.tool
    async def slow() -> str:
        hit("slow")
        await gate.wait()
        return "поздно"

    hits["_gate"] = gate  # type: ignore[assignment]
    return mcp, hits


def scripted(*turns, seen: list | None = None) -> FunctionModel:
    """Each turn is a final text (str) or a list of ``(tool_name, args)`` calls; the turn is
    chosen by how many model responses the history already has (retries count too).
    ``seen`` collects the messages of every request."""

    async def stream(messages, info):
        if seen is not None:
            seen.append(list(messages))
        i = sum(isinstance(m, ModelResponse) for m in messages)
        turn = turns[min(i, len(turns) - 1)]
        if isinstance(turn, Exception):
            raise turn
        if isinstance(turn, str):
            half = len(turn) // 2
            yield turn[:half]
            yield turn[half:]
            return
        yield {j: DeltaToolCall(name=n, json_args=json.dumps(a, ensure_ascii=False),
                                tool_call_id=f"p{i}-{j}") for j, (n, a) in enumerate(turn)}

    return FunctionModel(stream_function=stream)


def tool_returns(messages: list) -> list[str]:
    """Contents of tool-return parts the model received, in order."""
    return [str(p.content) for m in messages if isinstance(m, ModelRequest)
            for p in m.parts if p.part_kind == "tool-return"]


class World:
    def __init__(self, **settings):
        self.lens_store, self.lens_bus = MemoryLensStore(), EventBus()
        self.board = BoardService(self.lens_store, self.lens_bus)
        self.kb, self.hits = kb_source()
        board_app = board_mcp_app(lambda: self.board, BOARD_TOKEN)
        self.app = FastAPI(lifespan=board_app.lifespan)
        self.app.mount("/mcp", board_app)
        self.kb_app = self.kb.http_app(path="/mcp")
        self.store, self.bus = MemoryAgentStore(), EventBus()
        mcp = [McpEntry(name="kb", url="http://kb/mcp", namespace="kb", token=KB_TOKEN),
               McpEntry(name="board", url="http://lens/mcp/mcp", token=BOARD_TOKEN,
                        role="board")]
        self.settings = AgentSettings(mcp=settings.pop("mcp", mcp), **settings)
        self.model: FunctionModel | None = None
        self.runner = Runner(self.store, self.bus, self.settings, lambda: self.model,
                             server_factory=self._server)
        self.ws = None

    def _server(self, entry: McpEntry, headers: dict, hook):
        apps = {"http://kb/mcp": self.kb_app, "http://lens/mcp/mcp": self.app}
        return AsgiMCPServer(entry.url, app=apps.get(entry.url), headers=headers or None,
                             tool_prefix=entry.name, process_tool_call=hook, timeout=5,
                             max_retries=3)

    async def run(self, model: FunctionModel, text: str = "Росатом", mentions=()):
        """Submit a run and wait until it finishes; returns (run, events)."""
        self.model = model
        run = await self.runner.submit(self.ws.id, text, list(mentions))
        await self.wait(run.id)
        return await self.store.get_run(run.id), await self.store.list_events(run.id)

    async def wait(self, run_id: str) -> None:
        task = self.runner.tasks.get(run_id)
        if task is not None:
            await asyncio.wait_for(asyncio.shield(task), 10)


@asynccontextmanager
async def world(**settings):
    w = World(**settings)
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(lifespan_of(w.app))
        await stack.enter_async_context(lifespan_of(w.kb_app))
        w.ws = await w.lens_store.create_workspace("t")
        yield w
        await w.runner.drain()
```

- [ ] **Step 2: Write the failing tests** — `tests/test_lens_agent/test_runner.py`:

```python
import asyncio

from pydantic_ai.exceptions import ModelHTTPError

from src.lens_agent.config import McpEntry
from tests.test_lens_agent.helpers import BOARD_TOKEN, scripted, tool_returns, world


def objs(call_id="c2"):
    return [{"id": "E1", "type": "organization", "label": "Росатом", "call_id": call_id},
            {"id": "E2", "type": "person", "label": "Лихачёв", "call_id": call_id}]


def types(events):
    return [e.type for e in events]


def of(events, type_):
    return [e.data for e in events if e.type == type_]


async def test_happy_path_sources_injected_and_note_written():
    async with world() as w:
        run, evs = await w.run(scripted(
            [("board_get_board", {})],
            [("kb_find_entity", {"name": "Росатом"})],
            [("board_add_objects", {"objects": objs()})],
            [("board_add_relations", {"relations": [
                {"from": "kb:e2", "to": "kb:e1", "kind": "работает_в", "call_id": "c2"}]})],
            "Росатом возглавляет [[kb:e2]]."))
        assert run.status == "done" and run.usage["requests"] == 5
        assert types(evs)[0] == "run_started" and types(evs)[-2:] == ["final", "done"]
        assert of(evs, "run_started")[0]["mcp"] == [{"name": "kb", "status": "up"},
                                                    {"name": "board", "status": "up"}]
        calls = of(evs, "tool_call")
        assert [(c["call_id"], c["server"], c["tool"]) for c in calls] == [
            ("c1", "board", "get_board"), ("c2", "kb", "find_entity"),
            ("c3", "board", "add_objects"), ("c4", "board", "add_relations")]
        assert all(r["ok"] for r in of(evs, "tool_result"))
        assert "".join(d["delta"] for d in of(evs, "text")) == "Росатом возглавляет [[kb:e2]]."
        st = await w.board.state(w.ws.id)
        assert st.objects["kb:e1"].sources[0].model_dump() == {
            "server": "kb", "tool": "find_entity", "call_id": "c2", "run_id": run.id,
            "namespace": "kb"}
        assert len(st.relations) == 1
        assert [n.cites for n in st.notes] == [["kb:e2"]]
        assert (await w.store.get_payload(run.id, "c2")).payload["entities"][0]["id"] == "E1"


async def test_unknown_call_id_is_rejected_back_to_the_model():
    async with world() as w:
        seen = []
        run, _ = await w.run(scripted(
            [("board_add_objects", {"objects": [objs("c99")[0]]})],
            "нет данных", seen=seen))
        assert run.status == "done"
        assert "неизвестный call_id 'c99'" in tool_returns(seen[-1])[0]
        assert (await w.board.state(w.ws.id)).objects == {}


async def test_result_truncated_for_model_but_stored_in_full():
    async with world(result_chars=100) as w:
        seen = []
        run, evs = await w.run(scripted([("kb_big", {})], "ok", seen=seen))
        ret = tool_returns(seen[-1])[0]
        assert ret.startswith("call_id=c1\n") and ret.endswith("полный результат: call_id=c1")
        assert len(ret) < 200 and of(evs, "tool_result")[0]["truncated"] is True
        assert len((await w.store.get_payload(run.id, "c1")).payload) == 10_000


async def test_identical_call_served_from_cache_and_budget_is_soft():
    async with world(source_calls=1) as w:
        seen = []
        run, evs = await w.run(scripted(
            [("kb_find_entity", {"name": "Росатом"})],
            [("kb_find_entity", {"name": "Росатом"})],
            [("kb_big", {})],
            "итог", seen=seen))
        assert run.status == "done" and w.hits["find_entity"] == 1 and "big" not in w.hits
        rets = tool_returns(seen[-1])
        assert rets[1].startswith("(повтор вызова c1")
        assert rets[2].startswith("лимит вызовов источников исчерпан")
        results = of(evs, "tool_result")
        assert results[1]["cached_from"] == "c1" and results[2]["ok"] is False


async def test_tool_error_goes_back_to_model_and_shows_red():
    async with world() as w:
        seen = []
        run, evs = await w.run(scripted([("kb_boom", {})], "не вышло", seen=seen))
        assert run.status == "done"
        (res,) = of(evs, "tool_result")
        assert res["ok"] is False and "источник упал" in res["error"]


async def test_hard_request_limit_fails_the_run_and_keeps_the_board():
    async with world(request_limit=3) as w:
        run, evs = await w.run(scripted(
            [("kb_find_entity", {"name": "Росатом"})],
            [("board_add_objects", {"objects": objs("c1")[:1]})],
            [("board_get_board", {})]))
        assert run.status == "failed"
        assert of(evs, "error")[0]["where"] == "limit" and of(evs, "done") == [
            {"status": "failed"}]
        assert list((await w.board.state(w.ws.id)).objects) == ["kb:e1"]


async def test_model_error_fails_the_run():
    async with world() as w:
        run, evs = await w.run(scripted(ModelHTTPError(502, "large", "bad gateway")))
        assert run.status == "failed" and of(evs, "error")[0]["where"] == "model"


async def test_cancel_during_a_tool_call():
    async with world() as w:
        w.model = scripted([("kb_slow", {})], "не дойдёт")
        run = await w.runner.submit(w.ws.id, "медленно", [])
        for _ in range(100):
            if any(e.type == "tool_call" for e in await w.store.list_events(run.id)):
                break
            await asyncio.sleep(0.02)
        assert w.runner.cancel(run.id)
        await w.wait(run.id)
        evs = await w.store.list_events(run.id)
        assert of(evs, "done") == [{"status": "cancelled"}]
        assert (await w.store.get_run(run.id)).status == "cancelled"


async def test_down_source_is_reported_and_run_continues():
    mcp = [McpEntry(name="kb", url="http://kb/mcp", namespace="kb"),
           McpEntry(name="dead", url="http://dead/mcp"),
           McpEntry(name="board", url="http://lens/mcp/mcp", token=BOARD_TOKEN, role="board")]
    async with world(mcp=mcp) as w:
        run, evs = await w.run(scripted("ок"))
        assert run.status == "done"
        st = {m["name"]: m["status"] for m in of(evs, "run_started")[0]["mcp"]}
        assert st == {"kb": "up", "dead": "down", "board": "up"}


async def test_no_note_after_undo_and_model_note_not_duplicated():
    async with world() as w:
        await w.run(scripted([("kb_find_entity", {"name": "Р"})],
                             [("board_add_objects", {"objects": objs("c1")[:1]})], "первый"))
        assert list((await w.board.state(w.ws.id)).objects) == ["kb:e1"]
        run, _ = await w.run(scripted([("board_undo", {})], "отменил"))
        st = await w.board.state(w.ws.id)
        assert st.objects == {} and all(not n.key.endswith(run.id) for n in st.notes)
        await w.run(scripted([("board_add_note", {"text": "своя заметка"})], "ответ"))
        texts = [n.text for n in (await w.board.state(w.ws.id)).notes]
        assert texts.count("своя заметка") == 1 and "ответ" not in texts


async def test_mentions_resolved_into_the_prompt():
    async with world() as w:
        await w.run(scripted([("kb_find_entity", {"name": "Р"})],
                             [("board_add_objects", {"objects": objs("c1")[:1]})], "ok"))
        seen = []
        await w.run(scripted("ok", seen=seen), text="кто это?", mentions=["kb:e1"])
        prompt = seen[0][0].parts[-1].content
        assert "кто это?" in prompt and "kb:e1 — Росатом (organization)" in prompt


async def test_missing_board_fails_run():
    async with world(mcp=[McpEntry(name="kb", url="http://kb/mcp")]) as w:
        run, evs = await w.run(scripted("ok"))
        assert run.status == "failed" and "доска недоступна" in of(evs, "error")[0]["message"]


async def test_run_timeout_is_a_hard_limit():
    async with world(run_timeout_s=0.3) as w:
        run, evs = await w.run(scripted([("kb_slow", {})], "не дойдёт"))
        assert run.status == "failed"
        assert of(evs, "error")[0]["where"] == "limit" and "время запуска" in of(
            evs, "error")[0]["message"]


async def test_unknown_tool_is_journaled_and_model_retries():
    async with world() as w:
        run, evs = await w.run(scripted([("kb_no_such_tool", {})], "ладно"))
        assert run.status == "done" and of(evs, "error")[0]["where"] == "tool"
```

- [ ] **Step 3: Run, expect failure**

Run: `uv run --frozen pytest tests/test_lens_agent/test_runner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens_agent.runner'`.

- [ ] **Step 4: Implement** — `src/lens_agent/calls.py`:

```python
"""Per-run tool-call guard: the ``process_tool_call`` hook of every MCP server.

What the model cannot be trusted with happens here:
- every call gets a short ``call_id`` (c1, c2 …) that the model sees in source results and
  cites in board writes; the journal (``tool_call``/``tool_result``) uses the same id;
- source results are stored in full and cut to ``result_chars`` for the model;
- an identical repeated source call is answered from the run cache (not counted twice);
- soft budgets per kind (source / board): over budget the call is not made and the model is
  told to finish with what it has;
- board writes: ``call_id`` is checked against this run's source calls and replaced by the
  full ``source {server, tool, call_id, namespace}``; unknown ids are rejected with a reason.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

from pydantic_ai import ModelRetry

from src.lens_agent.config import McpEntry
from src.lens_agent.store import AgentStore, CallPayload
from src.lens_agent.stream import RunEmitter

_BOARD_WRITES = {"add_objects": "objects", "add_relations": "relations"}


@dataclass(frozen=True)
class CallInfo:
    call_id: str  # the call whose stored payload backs this id (cache hits point back)
    server: str
    tool: str
    namespace: str


@dataclass(frozen=True)
class CallLimits:
    result_chars: int = 4000
    source_calls: int = 8
    board_calls: int = 20
    tool_timeout_s: float = 120.0


def _text(result: Any) -> str:
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False,
                                                             default=str)


def _summary(result: Any, text: str) -> dict[str, Any]:
    items = None
    if isinstance(result, list):
        items = len(result)
    elif isinstance(result, dict):
        items = next((len(v) for v in result.values() if isinstance(v, list)), None)
    return {"items": items, "bytes": len(text.encode()), "preview": text[:200]}


class RunCalls:
    def __init__(self, run_id: str, store: AgentStore, emitter: RunEmitter,
                 limits: CallLimits | None = None):
        self.run_id, self.store, self.emitter = run_id, store, emitter
        self.limits = limits or CallLimits()
        self.registry: dict[str, CallInfo] = {}
        self.counts = {"source": 0, "board": 0}
        self.note_written = False
        self.undone = False
        self._ids: dict[str, str] = {}
        self._n = 0
        self._cache: dict[str, tuple[str, str]] = {}

    def short_id(self, provider_id: str | None) -> str:
        if provider_id and provider_id in self._ids:
            return self._ids[provider_id]
        self._n += 1
        cid = f"c{self._n}"
        if provider_id:
            self._ids[provider_id] = cid
        return cid

    def seen(self, provider_id: str | None) -> bool:
        """Did this model tool call reach our hook (and get its own tool_result)?"""
        return bool(provider_id) and provider_id in self._ids

    def hook(self, entry: McpEntry):
        async def process_tool_call(ctx, call_tool, name: str, args: dict[str, Any]):
            cid = self.short_id(ctx.tool_call_id)
            await self.emitter.emit("tool_call", call_id=cid, server=entry.name, tool=name,
                                    args=args)
            if entry.role == "board":
                return await self._board(cid, call_tool, name, args)
            return await self._source(entry, cid, call_tool, name, args)
        return process_tool_call

    async def _result(self, cid: str, *, ok: bool, t0: float, text: str = "",
                      result: Any = None, truncated: bool = False, error: str | None = None,
                      **extra: Any) -> None:
        data: dict[str, Any] = {"call_id": cid, "ok": ok,
                                "duration_ms": int((time.monotonic() - t0) * 1000),
                                "summary": _summary(result, text), "truncated": truncated,
                                **extra}
        if error is not None:
            data["error"] = error
        await self.emitter.emit("tool_result", **data)

    async def _call(self, cid: str, t0: float, call_tool, name: str, args: dict[str, Any]):
        try:
            return await asyncio.wait_for(call_tool(name, args, None),
                                          self.limits.tool_timeout_s)
        except ModelRetry as e:  # tool error: back to the model as text, red in the journal
            await self._result(cid, ok=False, t0=t0, error=str(e))
            raise
        except TimeoutError:
            msg = f"таймаут {self.limits.tool_timeout_s:.0f} с — попробуй иначе или завершай"
            await self._result(cid, ok=False, t0=t0, error=msg)
            raise ModelRetry(msg) from None

    async def _source(self, entry: McpEntry, cid: str, call_tool, name: str,
                      args: dict[str, Any]) -> str:
        t0 = time.monotonic()
        key = json.dumps([entry.name, name, args], sort_keys=True, ensure_ascii=False,
                         default=str)
        if key in self._cache:
            first, model_text = self._cache[key]
            self.registry[cid] = self.registry[first]
            await self._result(cid, ok=True, t0=t0, text=model_text, cached_from=first)
            return f"(повтор вызова {first}, тот же результат)\n{model_text}"
        if self.counts["source"] >= self.limits.source_calls:
            msg = (f"лимит вызовов источников исчерпан ({self.limits.source_calls}) — "
                   "завершай с тем, что есть")
            await self._result(cid, ok=False, t0=t0, error=msg)
            return msg
        self.counts["source"] += 1
        result = await self._call(cid, t0, call_tool, name, args)
        await self.store.save_payload(CallPayload(run_id=self.run_id, call_id=cid,
                                                  server=entry.name, tool=name, args=args,
                                                  payload=result))
        text = _text(result)
        n = self.limits.result_chars
        truncated = len(text) > n
        body = text[:n] + (f"\n…усечено, полный результат: call_id={cid}" if truncated else "")
        model_text = f"call_id={cid}\n{body}"
        self.registry[cid] = CallInfo(cid, entry.name, name, entry.ns)
        self._cache[key] = (cid, model_text)
        await self._result(cid, ok=True, t0=t0, text=text, result=result, truncated=truncated)
        return model_text

    def _attach_sources(self, items: Any) -> tuple[list[dict], list[dict]]:
        ok, rejected = [], []
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                rejected.append({"item": it, "reason": "ожидался объект"})
                continue
            ref = str(it.get("call_id") or "").strip()
            info = self.registry.get(ref)
            if info is None:
                rejected.append({"item": it, "reason": f"неизвестный call_id {ref!r} — укажи "
                                 "call_id из результата инструмента-источника этого запроса"})
                continue
            clean = {k: v for k, v in it.items() if k not in ("call_id", "source")}
            clean["source"] = {"server": info.server, "tool": info.tool,
                               "call_id": info.call_id, "namespace": info.namespace}
            ok.append(clean)
        return ok, rejected

    async def _board(self, cid: str, call_tool, name: str, args: dict[str, Any]) -> Any:
        t0 = time.monotonic()
        if self.counts["board"] >= self.limits.board_calls:
            msg = (f"лимит вызовов доски исчерпан ({self.limits.board_calls}) — "
                   "заверши ответ")
            await self._result(cid, ok=False, t0=t0, error=msg)
            return msg
        self.counts["board"] += 1
        if name in _BOARD_WRITES:
            field = _BOARD_WRITES[name]
            items, rejected = self._attach_sources(args.get(field))
            if items:
                result = await self._call(cid, t0, call_tool, name, {field: items})
            else:
                result = {"added": 0, "rejected": []}
            result = {**result, "rejected": rejected + list(result.get("rejected", []))}
        else:
            result = await self._call(cid, t0, call_tool, name, args)
        if name == "add_note":
            self.note_written = True
        elif name == "undo":
            self.undone = True
        await self._result(cid, ok=True, t0=t0, text=_text(result), result=result)
        return result
```

`src/lens_agent/prompt.py`:

```python
"""Agent instructions and the per-run user prompt."""

from __future__ import annotations

INSTRUCTIONS = """\
Ты — исследователь на доске объектов. Пользователь задаёт вопрос; ты находишь ответ в \
источниках и выкладываешь на доску только то, что на него отвечает.

Порядок работы:
1. Сначала вызови board_get_board — посмотри, что уже на доске. Упомянутые пользователем \
объекты даны в запросе (ключ и название).
2. Команды доски («скрой», «покажи», «отмени», «это одно и то же») выполняй только \
инструментами доски (board_hide, board_show, board_undo, board_merge), без поиска в источниках.
3. Ищи в источниках; соседей бери на 1 шаг; не повторяй одинаковые вызовы.
4. На доску клади только то, что отвечает на вопрос (обычно до 20 объектов): \
board_add_objects с id, type, label, call_id (из строки «call_id=…» результата источника), \
затем board_add_relations между ключами из ответа board_add_objects.
5. Не добавляй фактов, которых нет в результатах инструментов.
6. Закончи коротким ответом (до 5 предложений) на языке пользователя; объекты с доски \
упоминай как [[ключ]]."""


def user_prompt(text: str, mentions: list[dict]) -> str:
    """``mentions``: ``[{key, label, type}]`` resolved from the board (label may be None)."""
    if not mentions:
        return text
    lines = [f"- {m['key']} — {m.get('label') or '?'} ({m.get('type') or '?'})"
             for m in mentions]
    return f"{text}\n\nУпомянутые объекты доски:\n" + "\n".join(lines)
```

`src/lens_agent/runner.py`:

```python
"""Runs: connect MCP servers per run, drive the agent, map its events to our stream.

The web never sees PydanticAI types: text/thinking/final come from ``run_stream_events``,
tool_call/tool_result from the ``RunCalls`` hook. Every run ends with exactly one ``done``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from contextlib import AsyncExitStack
from typing import Any

from pydantic_ai import (
    Agent,
    AgentRunResultEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    UsageLimits,
)
from pydantic_ai.exceptions import (
    ModelAPIError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.mcp import MCPServer, MCPServerStreamableHTTP
from pydantic_ai.messages import (
    RetryPromptPart,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
)
from pydantic_ai.models import Model

from src.lens.events import EventBus
from src.lens_agent.calls import CallLimits, RunCalls
from src.lens_agent.config import AgentSettings, McpEntry
from src.lens_agent.prompt import INSTRUCTIONS, user_prompt
from src.lens_agent.store import AgentStore, RunRecord
from src.lens_agent.stream import RunEmitter

log = logging.getLogger(__name__)

ServerFactory = Callable[[McpEntry, dict[str, str], Any], MCPServer]


class RunFailure(Exception):
    def __init__(self, where: str, message: str):
        super().__init__(message)
        self.where, self.message = where, message


def http_server_factory(settings: AgentSettings) -> ServerFactory:
    def make(entry: McpEntry, headers: dict[str, str], hook: Any) -> MCPServer:
        return MCPServerStreamableHTTP(
            entry.url, headers=headers or None, tool_prefix=entry.name,
            process_tool_call=hook, timeout=settings.connect_timeout_s,
            read_timeout=settings.tool_timeout_s + 30, max_retries=3)
    return make


def _unwrap(e: BaseException) -> BaseException:
    while isinstance(e, BaseExceptionGroup) and len(e.exceptions) == 1:
        e = e.exceptions[0]
    return e


class Runner:
    def __init__(self, store: AgentStore, bus: EventBus, settings: AgentSettings,
                 model_factory: Callable[[], Model], server_factory: ServerFactory | None = None):
        self.store, self.bus, self.settings = store, bus, settings
        self.model_factory = model_factory
        self.server_factory = server_factory or http_server_factory(settings)
        self.tasks: dict[str, asyncio.Task] = {}

    # ── control ─────────────────────────────────────────────────────────
    async def submit(self, workspace_id: str, text: str, mentions: list[str]) -> RunRecord:
        run = await self.store.create_run(workspace_id, text, mentions, self.settings.model,
                                          stale_after_s=2 * self.settings.run_timeout_s)
        task = asyncio.create_task(self._run(run), name=f"lens-run-{run.id}")
        self.tasks[run.id] = task
        task.add_done_callback(lambda _t, rid=run.id: self.tasks.pop(rid, None))
        return run

    def cancel(self, run_id: str) -> bool:
        task = self.tasks.get(run_id)
        if task is None:
            return False
        task.cancel()
        return True

    async def drain(self) -> None:
        tasks = list(self.tasks.values())
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # ── one run ─────────────────────────────────────────────────────────
    def _headers(self, entry: McpEntry, run: RunRecord) -> dict[str, str]:
        h = {"Authorization": f"Bearer {entry.token.get_secret_value()}"} if entry.token else {}
        if entry.role == "board":
            h |= {"X-Workspace": run.workspace_id, "X-Run": run.id}
        return h

    async def _connect(self, stack: AsyncExitStack, run: RunRecord, calls: RunCalls):
        servers: dict[str, MCPServer] = {}
        statuses = []
        for entry in self.settings.enabled():
            server = self.server_factory(entry, self._headers(entry, run), calls.hook(entry))
            try:
                await stack.enter_async_context(server)
            except Exception as e:  # a down source: report it, work with the rest
                statuses.append({"name": entry.name, "status": "down",
                                 "error": f"{type(_unwrap(e)).__name__}: {_unwrap(e)}"[:300]})
                continue
            servers[entry.name] = server
            statuses.append({"name": entry.name, "status": "up"})
        return servers, statuses

    async def _mentions(self, board: MCPServer, keys: list[str]) -> list[dict]:
        out = []
        for key in keys:
            try:
                o = await board.direct_call_tool("get_object", {"key": key})
            except Exception:
                o = None
            o = o if isinstance(o, dict) else {}
            out.append({"key": key, "label": o.get("label"), "type": o.get("type")})
        return out

    async def _heartbeat(self, run_id: str) -> None:
        while True:
            await asyncio.sleep(self.settings.heartbeat_s)
            with contextlib.suppress(Exception):
                await self.store.heartbeat(run_id)

    async def _stream(self, agent: Agent, prompt: str, em: RunEmitter,
                      calls: RunCalls) -> tuple[str, dict[str, int]]:
        limits = UsageLimits(request_limit=self.settings.request_limit)
        async for ev in agent.run_stream_events(prompt, usage_limits=limits):
            if isinstance(ev, PartStartEvent):
                if isinstance(ev.part, TextPart):
                    await em.delta("text", ev.part.content)
                elif isinstance(ev.part, ThinkingPart):
                    await em.delta("thinking", ev.part.content)
            elif isinstance(ev, PartDeltaEvent):
                if isinstance(ev.delta, TextPartDelta):
                    await em.delta("text", ev.delta.content_delta)
                elif isinstance(ev.delta, ThinkingPartDelta):
                    await em.delta("thinking", ev.delta.content_delta or "")
            elif (isinstance(ev, FunctionToolResultEvent)
                  and isinstance(ev.result, RetryPromptPart)
                  and not calls.seen(ev.result.tool_call_id)):
                # rejected before reaching a server (unknown tool, invalid args)
                await em.emit("error", where="tool",
                              message=ev.result.model_response()[:500])
            elif isinstance(ev, AgentRunResultEvent):
                u = ev.result.usage()
                return str(ev.result.output), {"requests": u.requests,
                                               "tokens_in": u.input_tokens,
                                               "tokens_out": u.output_tokens}
        raise RunFailure("internal", "поток агента закончился без результата")

    async def _run(self, run: RunRecord) -> None:
        s = self.settings
        em = RunEmitter(self.store, self.bus, run.id)
        calls = RunCalls(run.id, self.store, em, CallLimits(
            result_chars=s.result_chars, source_calls=s.source_calls,
            board_calls=s.board_calls, tool_timeout_s=s.tool_timeout_s))
        t0 = time.monotonic()
        status, failure, usage = "failed", None, None
        side = [asyncio.create_task(self._heartbeat(run.id)), asyncio.create_task(em.autoflush())]
        try:
            async with AsyncExitStack() as stack:
                servers, statuses = await self._connect(stack, run, calls)
                await em.emit("run_started", input={"text": run.text, "mentions": run.mentions},
                              model=s.model, mcp=statuses)
                board_entry = s.board()
                board = servers.get(board_entry.name) if board_entry else None
                if board is None:
                    raise RunFailure("internal", "доска недоступна (board MCP)")
                prompt = user_prompt(run.text, await self._mentions(board, run.mentions))
                agent = Agent(self.model_factory(), instructions=INSTRUCTIONS,
                              toolsets=list(servers.values()))
                answer, usage = await asyncio.wait_for(self._stream(agent, prompt, em, calls),
                                                       s.run_timeout_s)
                await em.emit("final", answer=answer, usage=usage,
                              duration_ms=int((time.monotonic() - t0) * 1000))
                if answer.strip() and not calls.note_written and not calls.undone:
                    try:  # the note is deterministic: written even if the model forgot
                        await board.direct_call_tool("add_note", {"text": answer})
                    except Exception as e:
                        log.warning("run %s: add_note failed: %s", run.id, e)
                status = "done"
        except asyncio.CancelledError:
            status = "cancelled"
        except TimeoutError:
            failure = RunFailure("limit", f"время запуска исчерпано ({s.run_timeout_s:.0f} с)")
        except BaseException as e:  # every run must end with `done`
            e = _unwrap(e)
            task = asyncio.current_task()
            if isinstance(e, asyncio.CancelledError) or (task and task.cancelling()):
                # closing MCP streams on cancel may raise its own error — still a cancel
                status = "cancelled"
            elif isinstance(e, RunFailure):
                failure = e
            elif isinstance(e, UsageLimitExceeded):
                failure = RunFailure("limit", str(e))
            elif isinstance(e, ModelAPIError | UnexpectedModelBehavior):
                failure = RunFailure("model", str(e))
            else:
                log.exception("run %s failed", run.id)
                failure = RunFailure("internal", f"{type(e).__name__}: {e}")
        finally:
            for t in side:
                t.cancel()
            await asyncio.gather(*side, return_exceptions=True)
        if failure is not None:
            await em.emit("error", where=failure.where, message=failure.message[:1000])
        await em.emit("done", status=status)
        await self.store.finish_run(run.id, status, usage=usage,
                                    error=failure.message if failure else None)
```

Rulings recorded here (spec §4/§6 leave them open):
- `tool_call`/`tool_result` are emitted by the hook, not mapped from `FunctionToolCallEvent`: the hook knows the server, the short id and whether the result was cut. Calls rejected before reaching a server (unknown tool, invalid args) surface as `error{where:"tool"}`.
- The run cache applies to source calls only: board reads change as the run writes.
- Soft limits return a text result (not `ModelRetry`) so they never consume the server's retry budget; MCP servers get `max_retries=3`.

- [ ] **Step 5: Run, expect pass**

Run: `uv run --frozen pytest tests/test_lens tests/test_lens_agent -q && uv run --frozen ruff check src/lens src/lens_agent tests/test_lens tests/test_lens_agent`
Expected: 14 passed in test_runner; everything green; ruff clean. (DeprecationWarnings from opentelemetry and `streamablehttp_client` come from pydantic-ai internals — expected.)

- [ ] **Step 6: Commit (local)**

```bash
git add src/lens_agent/calls.py src/lens_agent/prompt.py src/lens_agent/runner.py tests/test_lens_agent/helpers.py tests/test_lens_agent/test_runner.py
git commit -m "feat(lens-agent): runner with call guard, budgets, source injection, deterministic note"
```

---

### Task 5: HTTP API

**Files:**
- Create: `src/lens_agent/app.py`
- Test: `tests/test_lens_agent/test_app.py`

**Interfaces:**
- Consumes: Tasks 2–4; `src.lens.auth.{require_key, make_stream_token, check_stream_token}`, `src.lens.config.lens_settings`.
- Produces (paths as served by the container; the web reaches them under `/agent/*` via nginx in Plan C):
  - `GET /health` (public) → `{status, model, mcp: {name: role}}`
  - `POST /runs {workspace_id, text, mentions}` → 201 `{run_id, stream_token}`; 409 `{"detail": {"message": "busy", "run_id"}}`; 422 on blank text
  - `GET /runs?workspace_id=&limit=` → `{active: run|null, runs: [run]}`
  - `GET /runs/{id}`; `POST /runs/{id}/cancel` → 202 / 409; `POST /runs/{id}/stream_token`
  - `GET /runs/{id}/calls/{call_id}` → stored payload
  - `GET /runs/{id}/events?token=` (+ `Last-Event-ID` header or `last_event_id` query) → SSE
  - `create_app(deps: AgentDeps | None)`, `AgentDeps(store, bus, runner, settings)`; module `app` for `uvicorn src.lens_agent.app:app --port 8020`

- [ ] **Step 1: Write the failing test** — `tests/test_lens_agent/test_app.py`:

```python
import asyncio
import json

import httpx
import pytest

from src.lens.config import lens_settings
from src.lens_agent.app import AgentDeps, create_app
from tests.test_lens.fakes import lifespan_of
from tests.test_lens_agent.helpers import scripted, world

KEY = "agent-test-key"


@pytest.fixture
async def env(monkeypatch):
    monkeypatch.setattr(lens_settings, "api_keys", KEY)
    async with world() as w:
        app = create_app(AgentDeps(store=w.store, bus=w.bus, runner=w.runner,
                                   settings=w.settings))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://t", headers={"X-API-Key": KEY}) as c:
            yield w, c, app


async def test_run_lifecycle_over_http(env):
    w, c, _ = env
    w.model = scripted("готово")
    r = await c.post("/runs", json={"workspace_id": w.ws.id, "text": "Росатом"})
    assert r.status_code == 201
    run_id, token = r.json()["run_id"], r.json()["stream_token"]
    await w.wait(run_id)
    async with c.stream("GET", f"/runs/{run_id}/events", params={"token": token},
                        headers={"X-API-Key": ""}) as s:
        body = "".join([chunk async for chunk in s.aiter_text()])
    types = [json.loads(line[6:])["type"] for line in body.splitlines()
             if line.startswith("data: ")]
    assert types[0] == "run_started" and types[-2:] == ["final", "done"]
    runs = (await c.get("/runs", params={"workspace_id": w.ws.id})).json()
    assert runs["active"] is None and runs["runs"][0]["status"] == "done"
    assert (await c.get(f"/runs/{run_id}")).json()["text"] == "Росатом"
    assert (await c.post(f"/runs/{run_id}/cancel")).status_code == 409


async def test_last_event_id_header_resumes(env):
    w, c, _ = env
    w.model = scripted("готово")
    r = (await c.post("/runs", json={"workspace_id": w.ws.id, "text": "q"})).json()
    await w.wait(r["run_id"])
    async with c.stream("GET", f"/runs/{r['run_id']}/events",
                        params={"token": r["stream_token"]},
                        headers={"Last-Event-ID": "2"}) as s:
        body = "".join([chunk async for chunk in s.aiter_text()])
    ids = [int(line[4:]) for line in body.splitlines() if line.startswith("id: ")]
    assert ids and ids[0] == 3


async def test_busy_workspace_and_cancel(env):
    w, c, _ = env
    w.model = scripted([("kb_slow", {})], "не дойдёт")
    first = (await c.post("/runs", json={"workspace_id": w.ws.id, "text": "q"})).json()
    r = await c.post("/runs", json={"workspace_id": w.ws.id, "text": "ещё"})
    assert r.status_code == 409 and r.json()["detail"]["run_id"] == first["run_id"]
    active = (await c.get("/runs", params={"workspace_id": w.ws.id})).json()["active"]
    assert active["id"] == first["run_id"]
    await asyncio.sleep(0.1)
    assert (await c.post(f"/runs/{first['run_id']}/cancel")).status_code == 202
    await w.wait(first["run_id"])
    assert (await c.get(f"/runs/{first['run_id']}")).json()["status"] == "cancelled"


async def test_auth_token_and_payloads(env):
    w, c, _ = env
    assert (await c.post("/runs", json={"workspace_id": "x", "text": "q"},
                         headers={"X-API-Key": ""})).status_code == 401
    assert (await c.post("/runs", json={"workspace_id": "x", "text": "  "})).status_code == 422
    w.model = scripted([("kb_find_entity", {"name": "Р"})], "ok")
    r = (await c.post("/runs", json={"workspace_id": w.ws.id, "text": "q"})).json()
    await w.wait(r["run_id"])
    assert (await c.get(f"/runs/{r['run_id']}/events",
                        params={"token": "1.bad"})).status_code == 403
    other = (await c.post(f"/runs/{r['run_id']}/stream_token")).json()["stream_token"]
    assert other
    call = (await c.get(f"/runs/{r['run_id']}/calls/c1")).json()
    assert call["tool"] == "find_entity" and call["payload"]["entities"]
    assert (await c.get(f"/runs/{r['run_id']}/calls/c9")).status_code == 404
    assert (await c.get("/health", headers={"X-API-Key": ""})).json() == {
        "status": "up", "model": "large", "mcp": {"kb": "source", "board": "board"}}


async def test_startup_marks_orphans_failed(env):
    w, _, app = env
    orphan = await w.store.create_run(w.ws.id, "q", [], "large", stale_after_s=600)
    async with lifespan_of(app):
        assert (await w.store.get_run(orphan.id)).status == "failed"
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run --frozen pytest tests/test_lens_agent/test_app.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens_agent.app'`.

- [ ] **Step 3: Implement** — `src/lens_agent/app.py`:

```python
"""lens-agent HTTP API.  Run: ``uvicorn src.lens_agent.app:app --host 0.0.0.0 --port 8020``.

REST takes ``X-API-Key`` (``LENS_API_KEYS``, shared with the board); the event stream takes
``?token=`` from ``POST /runs`` (HMAC bound to the run, secret ``LENS_STREAM_SECRET``).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from src.lens.auth import check_stream_token, make_stream_token, require_key
from src.lens.config import lens_settings
from src.lens.events import EventBus
from src.lens_agent.config import AgentSettings, agent_settings
from src.lens_agent.runner import Runner
from src.lens_agent.store import AgentStore, Busy, RunRecord
from src.lens_agent.stream import sse_events

log = logging.getLogger(__name__)


@dataclass
class AgentDeps:
    store: AgentStore
    bus: EventBus
    runner: Runner
    settings: AgentSettings


class NewRun(BaseModel):
    workspace_id: str = Field(min_length=1)
    text: str
    mentions: list[str] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be blank")
        return v


def _deps(request: Request) -> AgentDeps:
    return request.app.state.deps


def _run_json(r: RunRecord) -> dict[str, Any]:
    return r.model_dump(mode="json")


async def _run_or_404(deps: AgentDeps, run_id: str) -> RunRecord:
    run = await deps.store.get_run(run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    return run


def _routes() -> tuple[APIRouter, APIRouter]:
    public = APIRouter()
    api = APIRouter(dependencies=[Depends(require_key)])

    @public.get("/health")
    async def health(deps: AgentDeps = Depends(_deps)):
        return {"status": "up", "model": deps.settings.model,
                "mcp": {e.name: e.role for e in deps.settings.enabled()}}

    @api.post("/runs", status_code=status.HTTP_201_CREATED)
    async def create_run(body: NewRun, deps: AgentDeps = Depends(_deps)):
        try:
            run = await deps.runner.submit(body.workspace_id, body.text, body.mentions)
        except Busy as e:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                {"message": "busy", "run_id": e.run_id}) from e
        return {"run_id": run.id,
                "stream_token": make_stream_token(run.id, lens_settings.stream_secret_value())}

    @api.get("/runs")
    async def list_runs(workspace_id: str, limit: int = Query(10, ge=1, le=100),
                        deps: AgentDeps = Depends(_deps)):
        active = await deps.store.active_run(workspace_id)
        runs = await deps.store.list_runs(workspace_id, limit)
        return {"active": _run_json(active) if active else None,
                "runs": [_run_json(r) for r in runs]}

    @api.get("/runs/{run_id}")
    async def get_run(run_id: str, deps: AgentDeps = Depends(_deps)):
        return _run_json(await _run_or_404(deps, run_id))

    @api.post("/runs/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
    async def cancel_run(run_id: str, deps: AgentDeps = Depends(_deps)):
        run = await _run_or_404(deps, run_id)
        if run.status != "running" or not deps.runner.cancel(run_id):
            raise HTTPException(status.HTTP_409_CONFLICT, f"run is {run.status}")
        return {"run_id": run_id}

    @api.post("/runs/{run_id}/stream_token")
    async def stream_token(run_id: str, deps: AgentDeps = Depends(_deps)):
        await _run_or_404(deps, run_id)
        return {"stream_token": make_stream_token(run_id, lens_settings.stream_secret_value())}

    @api.get("/runs/{run_id}/calls/{call_id}")
    async def get_call(run_id: str, call_id: str, deps: AgentDeps = Depends(_deps)):
        rec = await deps.store.get_payload(run_id, call_id)
        if rec is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "call not found")
        return rec.model_dump(mode="json")

    @public.get("/runs/{run_id}/events")
    async def events(run_id: str, token: str = "", last_event_id: int = Query(0, ge=0),
                     last_event_id_header: str | None = Header(None, alias="Last-Event-ID"),
                     deps: AgentDeps = Depends(_deps)):
        if not check_stream_token(token, run_id, lens_settings.stream_secret_value()):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid or expired stream token")
        await _run_or_404(deps, run_id)
        after = last_event_id
        if last_event_id_header and last_event_id_header.isdigit():
            after = max(after, int(last_event_id_header))
        return StreamingResponse(sse_events(deps.store, deps.bus, run_id, after),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    return public, api


async def _build_deps(settings: AgentSettings) -> AgentDeps:
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    from src.lens_agent.store import PgAgentStore
    from src.storage.pg_pool import get_pg_pool

    store = PgAgentStore(await get_pg_pool())
    await store.ensure_schema()
    provider = OpenAIProvider(base_url=settings.llm_base_url(), api_key=settings.llm_api_key())
    bus = EventBus()
    runner = Runner(store, bus, settings, lambda: OpenAIChatModel(settings.model,
                                                                   provider=provider))
    return AgentDeps(store=store, bus=bus, runner=runner, settings=settings)


async def _daily_cleanup(deps: AgentDeps) -> None:
    while True:
        with contextlib.suppress(Exception):
            n = await deps.store.cleanup(deps.settings.retention_days)
            if n:
                log.info("lens-agent cleanup: %d old runs removed", n)
        await asyncio.sleep(24 * 3600)


def create_app(deps: AgentDeps | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from src.storage.pg_pool import close_pg_pool

        app.state.deps = deps or await _build_deps(agent_settings)
        n = await app.state.deps.store.fail_orphans("прервано перезапуском")
        if n:
            log.warning("lens-agent: %d runs left running were marked failed", n)
        cleanup = asyncio.create_task(_daily_cleanup(app.state.deps))
        try:
            yield
        finally:
            cleanup.cancel()
            await app.state.deps.runner.drain()
            if deps is None:
                await close_pg_pool()

    app = FastAPI(title="Lens agent", lifespan=lifespan)
    if deps is not None:
        app.state.deps = deps
    for router in _routes():
        app.include_router(router)
    return app


app = create_app()
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run --frozen pytest tests/test_lens tests/test_lens_agent -q && uv run --frozen ruff check src/lens src/lens_agent tests/test_lens tests/test_lens_agent`
Expected: 206 passed, 10 skipped; ruff clean.

- [ ] **Step 5: Update the code graph and commit (local)**

```bash
graphify update .
git add src/lens_agent/app.py tests/test_lens_agent/test_app.py graphify-out
git commit -m "feat(lens-agent): HTTP API — runs, SSE events, cancel, payloads, recovery"
```

---

## After this plan

- Postgres store check (needs the user's «да»): run `tests/test_lens_agent/test_store.py` with `LENS_TEST_PG_DSN` pointing at a disposable database.
- Plan C wires the container (`lens-agent` service, healthcheck, `LENS_AGENT_MCP` in `.env`, nginx `/agent/*`), the web, and the first live run.
