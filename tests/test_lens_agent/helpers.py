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