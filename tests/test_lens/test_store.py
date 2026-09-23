import os
import uuid

import pytest

from src.lens.model import ToolCallRecord
from src.lens.spec import ViewSpec
from src.lens.store import MemoryLensStore, PgLensStore

PG_DSN = os.environ.get("LENS_TEST_PG_DSN")


@pytest.fixture(params=["memory", "pg"])
async def store(request):
    if request.param == "memory":
        yield MemoryLensStore()
        return
    if not PG_DSN:
        pytest.skip("LENS_TEST_PG_DSN not set")
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(PG_DSN, min_size=1, max_size=2, open=False)
    await pool.open()
    s = PgLensStore(pool)
    await s.ensure_schema()
    yield s
    await pool.close()


async def test_workspace_roundtrip(store):
    ws = await store.create_workspace(f"t-{uuid.uuid4().hex[:6]}")
    assert (await store.get_workspace(ws.id)).title == ws.title
    assert ws.id in [w.id for w in await store.list_workspaces()]
    assert await store.get_workspace("missing") is None


async def test_ops_sequence_and_after(store):
    ws = await store.create_workspace("ops")
    iid = await store.add_input(ws.id, "q", ["kb:1"])
    a = await store.append_ops(ws.id, iid, [("hide", {"keys": ["a"]}),
                                            ("show", {"keys": ["a"]})])
    b = await store.append_ops(ws.id, None, [("pin", {"key": "a", "x": 1, "y": 2})])
    assert [o.seq for o in a + b] == [1, 2, 3]
    assert [o.kind for o in await store.list_ops(ws.id, after_seq=1)] == ["show", "pin"]
    assert a[0].input_id == iid and b[0].input_id is None
    await store.set_input_status(iid, "done")
    got = await store.get_input(iid)
    assert got["status"] == "done" and got["mentions"] == ["kb:1"]
    assert await store.get_input("missing") is None


async def test_tool_call_roundtrip(store):
    rec = ToolCallRecord(id=uuid.uuid4().hex, input_id=None, server="kb-tools", namespace="kb",
                         tool="t",
                         args={"q": "x"}, payload={"a": [1]}, shape_hash="h",
                         latency_ms=5)
    await store.add_tool_call(rec)
    got = await store.get_tool_call(rec.id)
    assert got.payload == {"a": [1]} and got.args == {"q": "x"}
    assert got.ns == "kb"
    assert await store.get_tool_call("nope") is None


async def test_spec_cache_upsert(store):
    tool = f"t-{uuid.uuid4().hex[:6]}"
    assert await store.get_spec("kb", tool, "h") is None
    s1 = ViewSpec.model_validate({"objects": [
        {"name": "o", "id": "$.id", "label": "$.n", "type": "person"}]})
    await store.put_spec("kb", tool, "h", s1, "m")
    await store.put_spec("kb", tool, "h", ViewSpec(), "m2")
    assert await store.get_spec("kb", tool, "h") == ViewSpec()
