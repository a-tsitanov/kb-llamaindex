"""lens-agent HTTP API.  Run: ``uvicorn src.lens_agent.app:app --host 0.0.0.0 --port 8020``.

REST takes ``X-API-Key`` (``LENS_API_KEYS``, shared with the board); the event stream takes
``?token=`` from ``POST /runs`` (HMAC bound to ``run:<run_id>``, secret ``LENS_STREAM_SECRET``;
the ``run:`` scope keeps a board workspace token from ever opening a run stream).
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


def _run_token(run_id: str) -> str:
    return make_stream_token(_token_scope(run_id), lens_settings.stream_secret_value())


def _token_scope(run_id: str) -> str:
    return f"run:{run_id}"


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
                "stream_token": _run_token(run.id)}

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
        return {"stream_token": _run_token(run_id)}

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
        if not check_stream_token(token, _token_scope(run_id),
                                  lens_settings.stream_secret_value()):
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
        try:
            n = await deps.store.cleanup(deps.settings.retention_days)
            if n:
                log.info("lens-agent cleanup: %d old runs removed", n)
        except Exception:
            log.exception("lens-agent cleanup failed")
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
            with contextlib.suppress(asyncio.CancelledError):
                await cleanup
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
