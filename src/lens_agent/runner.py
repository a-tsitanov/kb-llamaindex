"""Runs: connect MCP servers per run, drive the agent, map its events to our stream.

The web never sees PydanticAI types: text/thinking come from the ``agent.run`` event stream
handler, final/usage from its result, tool_call/tool_result from the ``RunCalls`` hook. Every
run ends with exactly one ``done``.

The whole run lives in its own task: ``agent.run`` drives the model and the tools in the
calling task and tool calls are forced sequential (pydantic-ai would otherwise start them as
detached tasks), so a cancel or the run timeout reaches the model request and the tool call in
flight, and the MCP connections are closed by the task that opened them.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import Callable
from contextlib import AsyncExitStack
from typing import Any

from pydantic_ai import (
    Agent,
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
from pydantic_ai.usage import RunUsage

from src.lens.events import EventBus
from src.lens_agent.calls import CallLimits, RunCalls, RunStalled
from src.lens_agent.config import AgentSettings, McpEntry
from src.lens_agent.prompt import INSTRUCTIONS, similar_objects, user_prompt
from src.lens_agent.store import AgentStore, RunRecord
from src.lens_agent.stream import RunEmitter

log = logging.getLogger(__name__)

# pydantic-ai 1.30 (_tool_manager.py): "Tool 'x' exceeded max retries count of N" — the model
# kept calling a failing tool; a tool problem, not a model one.
_TOOL_RETRIES = re.compile(r"^Tool '.+' exceeded max retries count of \d+")

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


def _usage_dict(u: RunUsage) -> dict[str, int]:
    return {"requests": u.requests, "tokens_in": u.input_tokens, "tokens_out": u.output_tokens}


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
        self._cancelling: set[str] = set()

    # ── control ─────────────────────────────────────────────────────────
    async def submit(self, workspace_id: str, text: str, mentions: list[str]) -> RunRecord:
        run = await self.store.create_run(workspace_id, text, mentions, self.settings.model,
                                          stale_after_s=2 * self.settings.run_timeout_s)
        task = asyncio.create_task(self._run(run), name=f"lens-run-{run.id}")
        self.tasks[run.id] = task
        task.add_done_callback(lambda _t, rid=run.id: self._forget(rid))
        return run

    def _forget(self, run_id: str) -> None:
        self.tasks.pop(run_id, None)
        self._cancelling.discard(run_id)

    def cancel(self, run_id: str) -> bool:
        """Idempotent: a run already being cancelled is not interrupted again (a second
        ``Task.cancel`` would break its end-of-run bookkeeping)."""
        task = self.tasks.get(run_id)
        if task is None:
            return False
        if run_id not in self._cancelling:
            self._cancelling.add(run_id)
            task.cancel()
        return True

    async def drain(self) -> None:
        tasks = list(self.tasks.values())
        for rid in list(self.tasks):
            self.cancel(rid)
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
            attrs = o.get("attrs") if isinstance(o.get("attrs"), dict) else {}
            out.append({"key": key, "label": o.get("label"), "type": o.get("type"),
                        "source_id": attrs.get("source_id")})
        return out

    async def _similar(self, board: MCPServer, text: str) -> list[dict]:
        """Board objects whose label resembles the request (outside the model's budgets)."""
        try:
            b = await board.direct_call_tool("get_board", {"limit": 200, "include_hidden": True})
        except Exception:
            return []
        objects = b.get("objects", []) if isinstance(b, dict) else []
        return similar_objects(text, objects)

    async def _heartbeat(self, run_id: str) -> None:
        while True:
            await asyncio.sleep(self.settings.heartbeat_s)
            with contextlib.suppress(Exception):
                await self.store.heartbeat(run_id)

    async def _agent_run(self, agent: Agent, prompt: str, em: RunEmitter, calls: RunCalls,
                         usage: RunUsage) -> tuple[str, dict[str, int]]:
        async def on_events(_ctx, events) -> None:
            async for ev in events:
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

        limits = UsageLimits(request_limit=self.settings.request_limit)
        with Agent.sequential_tool_calls():  # no detached tool-call tasks: see module doc
            result = await agent.run(prompt, usage_limits=limits, usage=usage,
                                     event_stream_handler=on_events)
        return str(result.output), _usage_dict(result.usage())

    async def _execute(self, run: RunRecord, em: RunEmitter, calls: RunCalls,
                       t0: float, run_usage: RunUsage) -> dict[str, int]:
        s = self.settings
        async with AsyncExitStack() as stack:
            servers, statuses = await self._connect(stack, run, calls)
            await em.emit("run_started", input={"text": run.text, "mentions": run.mentions},
                          model=s.model, mcp=statuses)
            board_entry = s.board()
            board = servers.get(board_entry.name) if board_entry else None
            if board is None:
                raise RunFailure("internal", "доска недоступна (board MCP)")
            calls.board_direct = board.direct_call_tool
            # hook-only board ops stay out of the model's tool list
            hidden = {f"{board_entry.name}_redirect"}
            toolsets = [srv.filtered(lambda _ctx, td: td.name not in hidden)
                        if name == board_entry.name else srv
                        for name, srv in servers.items()]
            mentioned = await self._mentions(board, run.mentions)
            similar = [o for o in await self._similar(board, run.text)
                       if o["key"] not in run.mentions]
            prompt = user_prompt(run.text, mentioned, similar=similar)
            async def more(call_id: str, offset: int = 0) -> str:
                """Следующие строки уже полученного результата источника, начиная с offset
                (номер строки из «ещё: more(...)»). Не новый вызов источника: лимит не тратит."""
                return await calls.more(call_id, offset)

            agent = Agent(self.model_factory(), instructions=INSTRUCTIONS,
                          toolsets=toolsets, tools=[more])
            answer, usage = await asyncio.wait_for(
                self._agent_run(agent, prompt, em, calls, run_usage), s.run_timeout_s)
            await em.emit("final", answer=answer, usage=usage,
                          duration_ms=int((time.monotonic() - t0) * 1000))
            if answer.strip() and not calls.note_written and not calls.undone:
                try:  # the note is deterministic: written even if the model forgot
                    await board.direct_call_tool("add_note", {"text": answer})
                except Exception as e:
                    log.warning("run %s: add_note failed: %s", run.id, e)
                    err = _unwrap(e)
                    await em.emit("error", where="tool", message=(
                        f"заметка не записана: {type(err).__name__}: {err}")[:1000])
            return usage

    def _classify(self, run: RunRecord, e: BaseException) -> tuple[str, RunFailure | None]:
        """(status, failure) for an exception that ended the run."""
        if isinstance(e, TimeoutError):
            return "failed", RunFailure(
                "limit", f"время запуска исчерпано ({self.settings.run_timeout_s:.0f} с)")
        e = _unwrap(e)
        task = asyncio.current_task()
        if isinstance(e, asyncio.CancelledError) or (task and task.cancelling()):
            # closing MCP streams on cancel may raise its own error — still a cancel
            return "cancelled", None
        if isinstance(e, RunFailure):
            return "failed", e
        if isinstance(e, RunStalled):
            return "failed", RunFailure("limit", str(e))
        if isinstance(e, UsageLimitExceeded):
            return "failed", RunFailure("limit", str(e))
        if isinstance(e, UnexpectedModelBehavior) and _TOOL_RETRIES.match(e.message):
            return "failed", RunFailure("tool", str(e))
        if isinstance(e, ModelAPIError | UnexpectedModelBehavior):
            return "failed", RunFailure("model", str(e))
        log.error("run %s failed", run.id, exc_info=e)
        return "failed", RunFailure("internal", f"{type(e).__name__}: {e}")

    async def _finalize(self, run: RunRecord, em: RunEmitter, side: list[asyncio.Task],
                        status: str, failure: RunFailure | None,
                        usage: dict[str, int] | None) -> None:
        for t in side:
            t.cancel()
        await asyncio.gather(*side, return_exceptions=True)
        if failure is not None:
            await em.emit("error", where=failure.where, message=failure.message[:1000])
        await em.emit("done", status=status)
        await self.store.finish_run(run.id, status, usage=usage,
                                    error=failure.message if failure else None)

    async def _run(self, run: RunRecord) -> None:
        s = self.settings
        em = RunEmitter(self.store, self.bus, run.id)
        calls = RunCalls(run.id, self.store, em, CallLimits(
            result_chars=s.result_chars, source_calls=s.source_calls,
            board_calls=s.board_calls, tool_timeout_s=s.tool_timeout_s,
            stall_calls=s.stall_calls))
        t0 = time.monotonic()
        status, failure, usage = "failed", None, None
        run_usage = RunUsage()  # filled in place by agent.run — kept even if the run fails
        side = [asyncio.create_task(self._heartbeat(run.id)), asyncio.create_task(em.autoflush())]
        try:
            usage = await self._execute(run, em, calls, t0, run_usage)
            status = "done"
        except BaseException as e:  # every run must end with `done`
            status, failure = self._classify(run, e)
            if run_usage.requests:
                usage = _usage_dict(run_usage)
        # The bookkeeping must survive a further cancellation (shutdown during a cancel):
        # it runs shielded and this task waits it out.
        fin = asyncio.ensure_future(self._finalize(run, em, side, status, failure, usage))
        while not fin.done():
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(fin)
        fin.result()
