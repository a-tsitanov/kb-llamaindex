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
