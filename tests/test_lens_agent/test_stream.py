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
