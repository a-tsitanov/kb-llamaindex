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
        run = await store.get_run(run_id)
        if run is None or run.status != "running":
            # finished (the client already has `done`, or it lands right now): no live tail
            for ev in await store.list_events(run_id, after_seq=last):
                yield _frame(ev.envelope())
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
