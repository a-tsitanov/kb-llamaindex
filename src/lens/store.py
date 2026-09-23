"""Lens persistence: workspaces, inputs, op log, tool calls, spec cache."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from src.lens.model import Op, OpKind, ToolCallRecord, Workspace
from src.lens.spec import ViewSpec

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS lens_workspace (
    id text PRIMARY KEY,
    title text NOT NULL,
    owner_id text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS lens_ws_member (
    workspace_id text NOT NULL REFERENCES lens_workspace(id) ON DELETE CASCADE,
    user_id text NOT NULL,
    role text NOT NULL,
    PRIMARY KEY (workspace_id, user_id)
);
CREATE TABLE IF NOT EXISTS lens_input (
    id text PRIMARY KEY,
    workspace_id text NOT NULL REFERENCES lens_workspace(id) ON DELETE CASCADE,
    text text NOT NULL,
    mentions jsonb NOT NULL DEFAULT '[]',
    status text NOT NULL DEFAULT 'pending',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS lens_op (
    workspace_id text NOT NULL REFERENCES lens_workspace(id) ON DELETE CASCADE,
    seq bigint NOT NULL,
    kind text NOT NULL,
    payload jsonb NOT NULL,
    input_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, seq)
);
CREATE TABLE IF NOT EXISTS lens_tool_call (
    id text PRIMARY KEY,
    input_id text,
    server text NOT NULL,
    namespace text,
    tool text NOT NULL,
    args jsonb NOT NULL,
    payload jsonb,
    shape_hash text NOT NULL,
    is_error boolean NOT NULL DEFAULT false,
    error text,
    latency_ms integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS lens_spec_cache (
    server text NOT NULL,
    tool text NOT NULL,
    shape_hash text NOT NULL,
    spec jsonb NOT NULL,
    model text NOT NULL,
    hits integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (server, tool, shape_hash)
);
"""


def _new_id() -> str:
    return uuid.uuid4().hex


class LensStore(Protocol):
    async def ensure_schema(self) -> None: ...
    async def create_workspace(self, title: str, owner_id: str | None = None) -> Workspace: ...
    async def list_workspaces(self) -> list[Workspace]: ...
    async def get_workspace(self, workspace_id: str) -> Workspace | None: ...
    async def add_input(self, workspace_id: str, text: str, mentions: list[str]) -> str: ...
    async def set_input_status(self, input_id: str, status: str) -> None: ...
    async def get_input(self, input_id: str) -> dict[str, Any] | None: ...
    async def append_ops(
        self, workspace_id: str, input_id: str | None, ops: list[tuple[OpKind, dict]],
    ) -> list[Op]: ...
    async def list_ops(self, workspace_id: str, after_seq: int = 0) -> list[Op]: ...
    async def add_tool_call(self, rec: ToolCallRecord) -> None: ...
    async def get_tool_call(self, call_id: str) -> ToolCallRecord | None: ...
    async def get_spec(self, server: str, tool: str, shape_hash: str) -> ViewSpec | None: ...
    async def put_spec(
        self, server: str, tool: str, shape_hash: str, spec: ViewSpec, model: str,
    ) -> None: ...


class MemoryLensStore:
    def __init__(self) -> None:
        self.workspaces: dict[str, Workspace] = {}
        self.inputs: dict[str, dict[str, Any]] = {}
        self.ops: dict[str, list[Op]] = {}
        self.calls: dict[str, ToolCallRecord] = {}
        self.specs: dict[tuple[str, str, str], ViewSpec] = {}
        self.spec_hits: dict[tuple[str, str, str], int] = {}

    async def ensure_schema(self) -> None:
        return None

    async def create_workspace(self, title: str, owner_id: str | None = None) -> Workspace:
        ws = Workspace(id=_new_id(), title=title, owner_id=owner_id,
                       created_at=datetime.now(UTC))
        self.workspaces[ws.id] = ws
        self.ops[ws.id] = []
        return ws

    async def list_workspaces(self) -> list[Workspace]:
        return sorted(self.workspaces.values(), key=lambda w: w.created_at, reverse=True)

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        return self.workspaces.get(workspace_id)

    async def add_input(self, workspace_id: str, text: str, mentions: list[str]) -> str:
        iid = _new_id()
        self.inputs[iid] = {"workspace_id": workspace_id, "text": text,
                            "mentions": list(mentions), "status": "pending"}
        return iid

    async def set_input_status(self, input_id: str, status: str) -> None:
        self.inputs[input_id]["status"] = status

    async def get_input(self, input_id: str) -> dict[str, Any] | None:
        row = self.inputs.get(input_id)
        return {"id": input_id, **row} if row else None

    async def append_ops(
        self, workspace_id: str, input_id: str | None, ops: list[tuple[OpKind, dict]],
    ) -> list[Op]:
        log = self.ops.setdefault(workspace_id, [])
        out = []
        for kind, payload in ops:
            op = Op(workspace_id=workspace_id, seq=len(log) + 1, kind=kind, payload=payload,
                    input_id=input_id, created_at=datetime.now(UTC))
            log.append(op)
            out.append(op)
        return out

    async def list_ops(self, workspace_id: str, after_seq: int = 0) -> list[Op]:
        return [o for o in self.ops.get(workspace_id, []) if o.seq > after_seq]

    async def add_tool_call(self, rec: ToolCallRecord) -> None:
        self.calls[rec.id] = rec

    async def get_tool_call(self, call_id: str) -> ToolCallRecord | None:
        return self.calls.get(call_id)

    async def get_spec(self, server: str, tool: str, shape_hash: str) -> ViewSpec | None:
        key = (server, tool, shape_hash)
        if key in self.specs:
            self.spec_hits[key] = self.spec_hits.get(key, 0) + 1
        return self.specs.get(key)

    async def put_spec(
        self, server: str, tool: str, shape_hash: str, spec: ViewSpec, model: str,
    ) -> None:
        self.specs[(server, tool, shape_hash)] = spec


class PgLensStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool

    async def ensure_schema(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(SCHEMA_SQL)

    async def create_workspace(self, title: str, owner_id: str | None = None) -> Workspace:
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "INSERT INTO lens_workspace (id, title, owner_id) VALUES (%s, %s, %s) "
                "RETURNING id, title, owner_id, created_at",
                (_new_id(), title, owner_id),
            )
            return Workspace.model_validate(await cur.fetchone())

    async def list_workspaces(self) -> list[Workspace]:
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "SELECT id, title, owner_id, created_at FROM lens_workspace "
                "ORDER BY created_at DESC"
            )
            return [Workspace.model_validate(r) for r in await cur.fetchall()]

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "SELECT id, title, owner_id, created_at FROM lens_workspace WHERE id = %s",
                (workspace_id,),
            )
            row = await cur.fetchone()
            return Workspace.model_validate(row) if row else None

    async def add_input(self, workspace_id: str, text: str, mentions: list[str]) -> str:
        iid = _new_id()
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO lens_input (id, workspace_id, text, mentions) "
                "VALUES (%s, %s, %s, %s)",
                (iid, workspace_id, text, Jsonb(list(mentions))),
            )
        return iid

    async def set_input_status(self, input_id: str, status: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute("UPDATE lens_input SET status = %s WHERE id = %s",
                               (status, input_id))

    async def get_input(self, input_id: str) -> dict[str, Any] | None:
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "SELECT id, workspace_id, text, mentions, status FROM lens_input WHERE id = %s",
                (input_id,),
            )
            return await cur.fetchone()

    async def append_ops(
        self, workspace_id: str, input_id: str | None, ops: list[tuple[OpKind, dict]],
    ) -> list[Op]:
        out: list[Op] = []
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (workspace_id,))
            cur = await conn.execute(
                "SELECT coalesce(max(seq), 0) FROM lens_op WHERE workspace_id = %s",
                (workspace_id,),
            )
            (seq,) = await cur.fetchone()
            for kind, payload in ops:
                seq += 1
                c = await conn.execute(
                    "INSERT INTO lens_op (workspace_id, seq, kind, payload, input_id) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING created_at",
                    (workspace_id, seq, kind, Jsonb(payload), input_id),
                )
                (created_at,) = await c.fetchone()
                out.append(Op(workspace_id=workspace_id, seq=seq, kind=kind, payload=payload,
                              input_id=input_id, created_at=created_at))
        return out

    async def list_ops(self, workspace_id: str, after_seq: int = 0) -> list[Op]:
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "SELECT workspace_id, seq, kind, payload, input_id, created_at FROM lens_op "
                "WHERE workspace_id = %s AND seq > %s ORDER BY seq",
                (workspace_id, after_seq),
            )
            return [Op.model_validate(r) for r in await cur.fetchall()]

    async def add_tool_call(self, rec: ToolCallRecord) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO lens_tool_call (id, input_id, server, namespace, tool, args, "
                "payload, shape_hash, is_error, error, latency_ms) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (rec.id, rec.input_id, rec.server, rec.namespace, rec.tool, Jsonb(rec.args),
                 Jsonb(rec.payload), rec.shape_hash, rec.is_error, rec.error, rec.latency_ms),
            )

    async def get_tool_call(self, call_id: str) -> ToolCallRecord | None:
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "SELECT id, input_id, server, namespace, tool, args, payload, shape_hash, "
                "is_error, error, latency_ms FROM lens_tool_call WHERE id = %s",
                (call_id,),
            )
            row = await cur.fetchone()
            return ToolCallRecord.model_validate(row) if row else None

    async def get_spec(self, server: str, tool: str, shape_hash: str) -> ViewSpec | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE lens_spec_cache SET hits = hits + 1 "
                "WHERE server = %s AND tool = %s AND shape_hash = %s RETURNING spec",
                (server, tool, shape_hash),
            )
            row = await cur.fetchone()
            return ViewSpec.model_validate(row[0]) if row else None

    async def put_spec(
        self, server: str, tool: str, shape_hash: str, spec: ViewSpec, model: str,
    ) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO lens_spec_cache (server, tool, shape_hash, spec, model) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (server, tool, shape_hash) "
                "DO UPDATE SET spec = EXCLUDED.spec, model = EXCLUDED.model, hits = 0",
                (server, tool, shape_hash, Jsonb(spec.model_dump(mode="json")), model),
            )
