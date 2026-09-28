"""Lens HTTP API.  Run: ``uvicorn src.lens.app:app --host 0.0.0.0 --port 8010``."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from src.lens.auth import make_stream_token, require_key, require_stream_token
from src.lens.board import BoardLimits, BoardService
from src.lens.board_mcp import board_mcp_app
from src.lens.config import lens_settings
from src.lens.events import EventBus, sse_stream
from src.lens.model import Column
from src.lens.paths import PathError, iter_path, resolve
from src.lens.state import fold, state_to_dict


@dataclass
class LensDeps:
    store: Any
    bus: EventBus
    agent: Any = None  # legacy input path only (LENS_LEGACY_INPUT=true)
    hub: Any = None
    board: BoardService | None = None

    def __post_init__(self) -> None:
        if self.board is None:
            self.board = BoardService(self.store, self.bus, BoardLimits(
                objects_per_call=lens_settings.board_objects_per_call,
                objects_per_run=lens_settings.board_objects_per_run))


class NewWorkspace(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class InputBody(BaseModel):
    text: str
    mentions: list[str] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be blank")
        return v


class PinBody(BaseModel):
    key: str
    x: float
    y: float


def _deps(request: Request) -> LensDeps:
    return request.app.state.deps


async def _workspace_or_404(deps: LensDeps, workspace_id: str):
    ws = await deps.store.get_workspace(workspace_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace not found")
    return ws


async def _call_or_404(deps: LensDeps, call_id: str):
    rec = await deps.store.get_tool_call(call_id)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tool call not found")
    return rec


_SCALAR_TYPES = (str, int, float)


def _validate_filter(raw: Any) -> dict[str, list[str]]:
    """``filter`` must be ``dict[str, list[str | int | float]]``; anything else
    (a bare scalar, a non-list value, a list with non-scalar items) is a 400,
    not a silent misinterpretation or an uncaught TypeError."""
    if not isinstance(raw, dict):
        raise ValueError("filter must be a JSON object")
    out: dict[str, list[str]] = {}
    for k, v in raw.items():
        if not isinstance(v, list) or not all(
            isinstance(x, _SCALAR_TYPES) and not isinstance(x, bool) for x in v
        ):
            raise ValueError(f"filter[{k!r}] must be a list of strings/numbers")
        out[str(k)] = [str(x) for x in v]
    return out


def _row_matches(row: dict[str, Any], flt: dict[str, list[str]]) -> bool:
    for col, allowed in flt.items():
        values = row.values() if col == "*" else [row.get(col)]
        flat = [str(x) for v in values for x in (v if isinstance(v, list) else [v])]
        if not any(v in allowed for v in flat):
            return False
    return True


def _routes() -> tuple[APIRouter, APIRouter, APIRouter]:
    public = APIRouter(prefix="/lens/v1")
    api = APIRouter(prefix="/lens/v1", dependencies=[Depends(require_key)])
    stream_api = APIRouter(prefix="/lens/v1", dependencies=[Depends(require_stream_token)])

    @public.get("/health")
    async def health(deps: LensDeps = Depends(_deps)):
        # Public: bucketed to "up"/"down" only — the raw status can carry connection
        # exception text (hostnames, ports, stack-adjacent detail) that's not for
        # anonymous callers.
        status_ = deps.hub.status() if deps.hub else {}
        return {"mcp": {name: "up" if s == "up" else "down" for name, s in status_.items()}}

    @api.get("/health/details")
    async def health_details(deps: LensDeps = Depends(_deps)):
        return {"mcp": deps.hub.status() if deps.hub else {}}

    @api.post("/workspaces")
    async def create_workspace(body: NewWorkspace, deps: LensDeps = Depends(_deps)):
        return (await deps.store.create_workspace(body.title)).model_dump(mode="json")

    @api.get("/workspaces")
    async def list_workspaces(deps: LensDeps = Depends(_deps)):
        return [w.model_dump(mode="json") for w in await deps.store.list_workspaces()]

    @api.get("/workspaces/{workspace_id}")
    async def get_workspace(workspace_id: str, deps: LensDeps = Depends(_deps)):
        ws = await _workspace_or_404(deps, workspace_id)
        state = fold(await deps.store.list_ops(workspace_id))
        return {"workspace": ws.model_dump(mode="json"), "state": state_to_dict(state)}

    @api.get("/workspaces/{workspace_id}/ops")
    async def get_ops(
        workspace_id: str, after_seq: int = Query(0, ge=0), deps: LensDeps = Depends(_deps),
    ):
        await _workspace_or_404(deps, workspace_id)
        return [o.model_dump(mode="json")
                for o in await deps.store.list_ops(workspace_id, after_seq=after_seq)]

    @api.post("/workspaces/{workspace_id}/input", status_code=status.HTTP_202_ACCEPTED)
    async def post_input(workspace_id: str, body: InputBody, deps: LensDeps = Depends(_deps)):
        await _workspace_or_404(deps, workspace_id)
        if deps.agent is None:
            raise HTTPException(status.HTTP_410_GONE,
                                "legacy input is disabled; send requests to lens-agent")
        input_id = await deps.agent.submit(workspace_id, body.text, body.mentions)
        return {"input_id": input_id}

    @api.post("/workspaces/{workspace_id}/pin")
    async def pin(workspace_id: str, body: PinBody, deps: LensDeps = Depends(_deps)):
        await _workspace_or_404(deps, workspace_id)
        op = await deps.board.pin(workspace_id, body.key, body.x, body.y)
        return {"seq": op.seq}

    @api.post("/workspaces/{workspace_id}/stream_token")
    async def stream_token(workspace_id: str, deps: LensDeps = Depends(_deps)):
        await _workspace_or_404(deps, workspace_id)
        return {"token": make_stream_token(workspace_id, lens_settings.stream_secret_value())}

    @stream_api.get("/workspaces/{workspace_id}/stream")
    async def stream(workspace_id: str, deps: LensDeps = Depends(_deps)):
        await _workspace_or_404(deps, workspace_id)
        return StreamingResponse(sse_stream(deps.bus, workspace_id),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @api.get("/tool_calls/{call_id}/value")
    async def call_value(call_id: str, path: str, deps: LensDeps = Depends(_deps)):
        rec = await _call_or_404(deps, call_id)
        try:
            return {"value": resolve(rec.payload, path)}
        except PathError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    @api.get("/tool_calls/{call_id}/rows")
    async def call_rows(
        call_id: str,
        path: str,
        columns: str,
        filter: str = "{}",  # public query parameter name
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
        deps: LensDeps = Depends(_deps),
    ):
        rec = await _call_or_404(deps, call_id)
        try:
            cols = [Column.model_validate(c) for c in json.loads(columns)]
            flt = _validate_filter(json.loads(filter))
            rows = []
            for _, item in iter_path(rec.payload, path):
                row = {}
                for c in cols:
                    m = iter_path(item, c.path)
                    row[c.name] = m[0][1] if len(m) == 1 else [v for _, v in m] or None
                if _row_matches(row, flt):
                    rows.append(row)
        except (PathError, ValueError, AttributeError) as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
        return {"total": len(rows), "rows": rows[offset:offset + limit]}

    return public, api, stream_api


async def _build_deps() -> LensDeps:
    from src.lens.store import PgLensStore
    from src.storage.pg_pool import get_pg_pool

    store = PgLensStore(await get_pg_pool())
    await store.ensure_schema()
    bus = EventBus()
    if not lens_settings.legacy_input:
        return LensDeps(store=store, bus=bus)
    return await _build_legacy_deps(store, bus)


async def _build_legacy_deps(store: Any, bus: EventBus) -> LensDeps:
    from src.lens.agent import Agent
    from src.lens.llm import OpenAICompatLLM
    from src.lens.mcp_hub import McpHub
    from src.lens.normalizer import Normalizer
    from src.lens.planner import Planner

    hub = McpHub(lens_settings.mcp_servers, timeout_s=lens_settings.tool_timeout_s,
                 backoff_s=lens_settings.reconnect_backoff_s)
    await hub.start()
    llm = OpenAICompatLLM()
    planner = Planner(llm, hub, store, model=lens_settings.planner_model(),
                      max_steps=lens_settings.max_tool_steps,
                      sample_chars=lens_settings.sample_chars)
    normalizer = Normalizer(llm, store, model=lens_settings.normalizer_model(),
                            vocabulary=lens_settings.vocabulary,
                            aggregate_threshold=lens_settings.aggregate_threshold,
                            aggregate_preview=lens_settings.aggregate_preview,
                            sample_chars=lens_settings.sample_chars)
    agent = Agent(store=store, bus=bus, planner=planner, normalizer=normalizer)
    return LensDeps(store=store, bus=bus, agent=agent, hub=hub)


def create_app(deps: LensDeps | None = None) -> FastAPI:
    # Board MCP for lens-agent; resolves the board per call (deps are built in lifespan).
    board_mcp = board_mcp_app(lambda: app.state.deps.board,
                              lens_settings.board_mcp_token.get_secret_value())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with board_mcp.lifespan(app):
            if deps is not None:
                app.state.deps = deps
                yield
                return
            from src.storage.pg_pool import close_pg_pool

            app.state.deps = await _build_deps()
            try:
                yield
            finally:
                if app.state.deps.agent is not None:
                    await app.state.deps.agent.drain()
                if app.state.deps.hub is not None:
                    await app.state.deps.hub.close()
                await close_pg_pool()

    app = FastAPI(title="Lens", lifespan=lifespan)
    if deps is not None:
        app.state.deps = deps
    app.add_middleware(CORSMiddleware, allow_origins=lens_settings.cors_list(),
                       allow_methods=["GET", "POST"], allow_headers=["X-API-Key",
                                                                    "Content-Type"])
    for router in _routes():
        app.include_router(router)
    app.mount("/mcp", board_mcp)  # endpoint: /mcp/mcp
    return app


app = create_app()
