import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from src.lens_agent.store import Busy, CallPayload, MemoryAgentStore, PgAgentStore

PG_DSN = os.environ.get("LENS_TEST_PG_DSN")


@pytest.fixture(params=["memory", "pg"])
async def store(request):
    if request.param == "memory":
        yield MemoryAgentStore()
        return
    if not PG_DSN:
        pytest.skip("LENS_TEST_PG_DSN not set")
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(PG_DSN, min_size=1, max_size=2, open=False)
    await pool.open()
    s = PgAgentStore(pool)
    await s.ensure_schema()
    yield s
    await pool.close()


def ws() -> str:
    return f"ws-{uuid.uuid4().hex[:8]}"


async def test_one_active_run_per_workspace(store):
    w = ws()
    run = await store.create_run(w, "q", ["kb:1"], "large", stale_after_s=600)
    assert run.status == "running" and run.mentions == ["kb:1"]
    with pytest.raises(Busy) as e:
        await store.create_run(w, "q2", [], "large", stale_after_s=600)
    assert e.value.run_id == run.id
    assert (await store.active_run(w)).id == run.id
    other = await store.create_run(ws(), "q", [], "large", stale_after_s=600)
    assert other.status == "running"
    await store.finish_run(run.id, "done", usage={"requests": 2})
    again = await store.create_run(w, "q3", [], "large", stale_after_s=600)
    assert [r.id for r in await store.list_runs(w, 10)] == [again.id, run.id]
    assert (await store.get_run(run.id)).usage == {"requests": 2}


async def test_stale_heartbeat_frees_the_workspace(store):
    w = ws()
    run = await store.create_run(w, "q", [], "large", stale_after_s=600)
    if isinstance(store, MemoryAgentStore):
        store.runs[run.id].heartbeat_at = datetime.now(UTC) - timedelta(seconds=5)
    else:
        async with store.pool.connection() as conn:
            await conn.execute("UPDATE agent_run SET heartbeat_at = now() - interval '5 s' "
                               "WHERE id = %s", (run.id,))
    fresh = await store.create_run(w, "q2", [], "large", stale_after_s=1)
    old = await store.get_run(run.id)
    assert fresh.status == "running" and old.status == "failed" and old.error
    assert [(e.type, e.data) for e in await store.list_events(run.id)] == [
        ("error", {"where": "internal", "message": old.error}), ("done", {"status": "failed"})]
    assert await store.list_events(fresh.id) == []


async def test_fail_orphans_on_restart(store):
    run = await store.create_run(ws(), "q", [], "large", stale_after_s=600)
    assert await store.fail_orphans("прервано перезапуском") >= 1
    r = await store.get_run(run.id)
    assert r.status == "failed" and r.error == "прервано перезапуском" and r.finished_at
    assert [(e.seq, e.type, e.data) for e in await store.list_events(run.id)] == [
        (1, "error", {"where": "internal", "message": "прервано перезапуском"}),
        (2, "done", {"status": "failed"})]


async def test_events_are_sequenced_and_filtered(store):
    run = await store.create_run(ws(), "q", [], "large", stale_after_s=600)
    a = await store.append_event(run.id, "run_started", {"model": "large"})
    b = await store.append_event(run.id, "text", {"delta": "при"})
    assert (a.seq, b.seq) == (1, 2)
    assert [e.type for e in await store.list_events(run.id, after_seq=1)] == ["text"]
    env = b.envelope()
    assert env["run_id"] == run.id and env["seq"] == 2 and env["delta"] == "при"


async def test_payload_roundtrip_and_cleanup(store):
    run = await store.create_run(ws(), "q", [], "large", stale_after_s=600)
    rec = CallPayload(run_id=run.id, call_id="c1", server="kb", tool="t", args={"a": 1},
                      payload={"x": [1, 2]})
    await store.save_payload(rec)
    assert (await store.get_payload(run.id, "c1")).payload == {"x": [1, 2]}
    assert await store.get_payload(run.id, "c9") is None
    await store.finish_run(run.id, "done")
    assert await store.cleanup(30) == 0
    if isinstance(store, MemoryAgentStore):
        store.runs[run.id].created_at -= timedelta(days=31)
    else:
        async with store.pool.connection() as conn:
            await conn.execute("UPDATE agent_run SET created_at = now() - interval '31 days' "
                               "WHERE id = %s", (run.id,))
    assert await store.cleanup(30) >= 1
    assert await store.get_run(run.id) is None
    assert await store.get_payload(run.id, "c1") is None
