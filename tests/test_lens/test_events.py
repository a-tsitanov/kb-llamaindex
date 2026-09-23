import asyncio
import json

from src.lens.events import EventBus, sse_stream


async def test_publish_reaches_subscribers_of_that_workspace_only():
    bus = EventBus()
    a, b = bus.subscribe("w1"), bus.subscribe("w2")
    bus.publish("w1", {"type": "reply", "text": "x"})
    assert a.get_nowait() == {"type": "reply", "text": "x"}
    assert b.empty()
    bus.unsubscribe("w1", a)
    bus.publish("w1", {"type": "reply"})
    assert a.empty()


async def test_overflow_sends_resync_and_unsubscribes():
    bus = EventBus(queue_max=2)
    q = bus.subscribe("w")
    for i in range(3):
        bus.publish("w", {"type": "ops", "i": i})
    assert q.get_nowait() == {"type": "resync"} and q.empty()
    assert bus.subscriber_count("w") == 0


async def test_sse_stream_ready_event_then_data():
    bus = EventBus()
    gen = sse_stream(bus, "w", heartbeat_s=60)
    assert await gen.__anext__() == 'event: ready\ndata: {"type": "ready"}\n\n'
    bus.publish("w", {"type": "reply", "text": "привет"})  # subscription is live now
    frame = await gen.__anext__()
    assert frame.startswith("event: reply\n")
    assert json.loads(frame.split("data: ", 1)[1]) == {
        "type": "reply",
        "text": "привет",
    }
    await gen.aclose()
    assert bus.subscriber_count("w") == 0


async def test_sse_stream_heartbeat_when_idle():
    bus = EventBus()
    gen = sse_stream(bus, "w", heartbeat_s=0.01)
    await gen.__anext__()  # ready
    assert await asyncio.wait_for(gen.__anext__(), timeout=5) == ": ping\n\n"
    await gen.aclose()


async def test_sse_stream_ends_after_resync():
    bus = EventBus(queue_max=1)
    gen = sse_stream(bus, "w", heartbeat_s=60)
    await gen.__anext__()  # ready
    bus.publish("w", {"type": "ops"})
    bus.publish("w", {"type": "ops"})  # overflow
    assert (await gen.__anext__()).startswith("event: resync")
    try:
        await gen.__anext__()
        raise AssertionError("stream should have ended")
    except StopAsyncIteration:
        pass
