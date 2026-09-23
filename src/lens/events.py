"""Per-workspace pub/sub and SSE framing.

Client protocol (no lost updates):
1. open the stream and wait for ``ready`` (subscription is live);
2. ``GET /workspaces/{id}`` → state with ``last_seq``;
3. apply ``ops`` events, ignoring ops with ``seq <= last_seq``; on a seq gap call
   ``GET /workspaces/{id}/ops?after_seq=<last>``;
4. on ``resync`` (the client fell behind and its queue overflowed) the stream ends:
   reconnect and start again from 1.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

QUEUE_MAX = 1000


class EventBus:
    def __init__(self, queue_max: int = QUEUE_MAX) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._queue_max = queue_max

    def subscribe(self, workspace_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_max)
        self._subs.setdefault(workspace_id, set()).add(q)
        return q

    def unsubscribe(self, workspace_id: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(workspace_id)
        if subs is not None:
            subs.discard(q)
            if not subs:
                del self._subs[workspace_id]

    def subscriber_count(self, workspace_id: str) -> int:
        return len(self._subs.get(workspace_id, ()))

    def publish(self, workspace_id: str, event: dict) -> None:
        for q in list(self._subs.get(workspace_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer: drop its backlog, tell it to resync, cut it off.
                while not q.empty():
                    q.get_nowait()
                q.put_nowait({"type": "resync"})
                self.unsubscribe(workspace_id, q)


def _frame(ev: dict) -> str:
    return (
        f"event: {ev.get('type', 'message')}\n"
        f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
    )


async def sse_stream(
    bus: EventBus, workspace_id: str, *, heartbeat_s: float = 15.0,
) -> AsyncIterator[str]:
    q = bus.subscribe(workspace_id)
    try:
        yield _frame({"type": "ready"})
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=heartbeat_s)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            yield _frame(ev)
            if ev.get("type") == "resync":
                return
    finally:
        bus.unsubscribe(workspace_id, q)
