"""lens-agent persistence: runs, their (coalesced) stream events, full tool results.

One active run per workspace: ``create_run`` refuses (``Busy``) while another run of the
workspace is ``running`` with a fresh heartbeat; a stale one is failed and replaced.
A run failed here (stale takeover, ``fail_orphans`` on restart) still gets its terminal
``error{where:"internal"}`` + ``done{status:"failed"}`` events, like any other run.
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

STALE_REASON = "зависший запуск снят"


def strip_nul(value: Any) -> Any:
    """``value`` with NUL characters removed from every string (and key): Postgres jsonb
    rejects ``\\u0000``, and a tool result may carry it. Both stores apply it, for parity."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {strip_nul(k): strip_nul(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [strip_nul(v) for v in value]
    return value


def _terminal_events(reason: str) -> list[tuple[str, dict[str, Any]]]:
    """The events closing a run failed outside its runner."""
    return [("error", {"where": "internal", "message": reason}), ("done", {"status": "failed"})]


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
            await self._fail(active.id, STALE_REASON)
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

    async def _fail(self, run_id: str, reason: str) -> None:
        await self.finish_run(run_id, "failed", error=reason)
        for type_, data in _terminal_events(reason):
            await self.append_event(run_id, type_, data)

    async def fail_orphans(self, reason):
        orphans = [r for r in self.runs.values() if r.status == "running"]
        for r in orphans:
            await self._fail(r.id, reason)
        return len(orphans)

    async def append_event(self, run_id, type_, data):
        data = strip_nul(data)
        evs = self.events.setdefault(run_id, [])
        ev = AgentEvent(run_id=run_id, seq=len(evs) + 1, ts=_now(), type=type_, data=data)
        evs.append(ev)
        return ev

    async def list_events(self, run_id, after_seq=0):
        return [e for e in self.events.get(run_id, []) if e.seq > after_seq]

    async def save_payload(self, rec):
        self.payloads[(rec.run_id, rec.call_id)] = rec.model_copy(
            update={"args": strip_nul(rec.args), "payload": strip_nul(rec.payload)})

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

    @staticmethod
    async def _append_on(conn, run_id: str, type_: str, data: dict[str, Any]):
        """Append one event inside the caller's transaction; returns ``(seq, ts)``."""
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (run_id,))
        cur = await conn.execute(
            "INSERT INTO agent_event (run_id, seq, type, data) "
            "SELECT %s, coalesce(max(seq), 0) + 1, %s, %s FROM agent_event "
            "WHERE run_id = %s RETURNING seq, ts",
            (run_id, type_, Jsonb(data), run_id))
        return await cur.fetchone()

    async def _fail_where(self, conn, where_sql: str, params: tuple, reason: str) -> int:
        """Fail the matching running runs and close each with its terminal events, in one
        transaction."""
        async with conn.transaction():
            cur = await conn.execute(
                "UPDATE agent_run SET status = 'failed', error = %s, finished_at = now() "
                f"WHERE status = 'running' AND {where_sql} RETURNING id", (reason, *params))
            ids = [row[0] for row in await cur.fetchall()]
            for run_id in ids:
                for type_, data in _terminal_events(reason):
                    await self._append_on(conn, run_id, type_, data)
        return len(ids)

    async def create_run(self, workspace_id, text, mentions, model, *, stale_after_s):
        async with self.pool.connection() as conn:
            await self._fail_where(
                conn, "workspace_id = %s AND heartbeat_at < now() - make_interval(secs => %s)",
                (workspace_id, stale_after_s), STALE_REASON)
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
            return await self._fail_where(conn, "true", (), reason)

    async def append_event(self, run_id, type_, data):
        data = strip_nul(data)
        async with self.pool.connection() as conn, conn.transaction():
            seq, ts = await self._append_on(conn, run_id, type_, data)
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
                (rec.run_id, rec.call_id, rec.server, rec.tool, Jsonb(strip_nul(rec.args)),
                 Jsonb(strip_nul(rec.payload))))

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
