import asyncio
import json

import httpx
import pytest

from src.lens.config import lens_settings
from src.lens_agent.app import AgentDeps, create_app
from tests.test_lens.fakes import lifespan_of
from tests.test_lens_agent.helpers import scripted, world

KEY = "agent-test-key"


@pytest.fixture
async def env(monkeypatch):
    monkeypatch.setattr(lens_settings, "api_keys", KEY)
    async with world() as w:
        app = create_app(AgentDeps(store=w.store, bus=w.bus, runner=w.runner,
                                   settings=w.settings))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://t", headers={"X-API-Key": KEY}) as c:
            yield w, c, app


async def test_run_lifecycle_over_http(env):
    w, c, _ = env
    w.model = scripted("готово")
    r = await c.post("/runs", json={"workspace_id": w.ws.id, "text": "Росатом"})
    assert r.status_code == 201
    run_id, token = r.json()["run_id"], r.json()["stream_token"]
    await w.wait(run_id)
    async with c.stream("GET", f"/runs/{run_id}/events", params={"token": token},
                        headers={"X-API-Key": ""}) as s:
        body = "".join([chunk async for chunk in s.aiter_text()])
    types = [json.loads(line[6:])["type"] for line in body.splitlines()
             if line.startswith("data: ")]
    assert types[0] == "run_started" and types[-2:] == ["final", "done"]
    runs = (await c.get("/runs", params={"workspace_id": w.ws.id})).json()
    assert runs["active"] is None and runs["runs"][0]["status"] == "done"
    assert (await c.get(f"/runs/{run_id}")).json()["text"] == "Росатом"
    assert (await c.post(f"/runs/{run_id}/cancel")).status_code == 409


async def test_last_event_id_header_resumes(env):
    w, c, _ = env
    w.model = scripted("готово")
    r = (await c.post("/runs", json={"workspace_id": w.ws.id, "text": "q"})).json()
    await w.wait(r["run_id"])
    async with c.stream("GET", f"/runs/{r['run_id']}/events",
                        params={"token": r["stream_token"]},
                        headers={"Last-Event-ID": "2"}) as s:
        body = "".join([chunk async for chunk in s.aiter_text()])
    ids = [int(line[4:]) for line in body.splitlines() if line.startswith("id: ")]
    assert ids and ids[0] == 3


async def test_busy_workspace_and_cancel(env):
    w, c, _ = env
    w.model = scripted([("kb_slow", {})], "не дойдёт")
    first = (await c.post("/runs", json={"workspace_id": w.ws.id, "text": "q"})).json()
    r = await c.post("/runs", json={"workspace_id": w.ws.id, "text": "ещё"})
    assert r.status_code == 409 and r.json()["detail"]["run_id"] == first["run_id"]
    active = (await c.get("/runs", params={"workspace_id": w.ws.id})).json()["active"]
    assert active["id"] == first["run_id"]
    await asyncio.sleep(0.1)
    assert (await c.post(f"/runs/{first['run_id']}/cancel")).status_code == 202
    await w.wait(first["run_id"])
    assert (await c.get(f"/runs/{first['run_id']}")).json()["status"] == "cancelled"


async def test_auth_token_and_payloads(env):
    w, c, _ = env
    assert (await c.post("/runs", json={"workspace_id": "x", "text": "q"},
                         headers={"X-API-Key": ""})).status_code == 401
    assert (await c.post("/runs", json={"workspace_id": "x", "text": "  "})).status_code == 422
    w.model = scripted([("kb_find_entity", {"name": "Р"})], "ok")
    r = (await c.post("/runs", json={"workspace_id": w.ws.id, "text": "q"})).json()
    await w.wait(r["run_id"])
    assert (await c.get(f"/runs/{r['run_id']}/events",
                        params={"token": "1.bad"})).status_code == 403
    other = (await c.post(f"/runs/{r['run_id']}/stream_token")).json()["stream_token"]
    assert other
    call = (await c.get(f"/runs/{r['run_id']}/calls/c1")).json()
    assert call["tool"] == "find_entity" and call["payload"]["entities"]
    assert (await c.get(f"/runs/{r['run_id']}/calls/c9")).status_code == 404
    assert (await c.get("/health", headers={"X-API-Key": ""})).json() == {
        "status": "up", "model": "large", "mcp": {"kb": "source", "board": "board"}}


async def test_startup_marks_orphans_failed(env):
    w, _, app = env
    orphan = await w.store.create_run(w.ws.id, "q", [], "large", stale_after_s=600)
    async with lifespan_of(app):
        assert (await w.store.get_run(orphan.id)).status == "failed"
        evs = await w.store.list_events(orphan.id)
        assert [(e.type, e.data) for e in evs] == [
            ("error", {"where": "internal", "message": "прервано перезапуском"}),
            ("done", {"status": "failed"})]


async def test_daily_cleanup_logs_errors(env, monkeypatch, caplog):
    from src.lens_agent.app import _daily_cleanup

    w, _, _ = env
    caplog.clear()
    caplog.set_level("ERROR", "src.lens_agent.app")

    async def cleanup_raises(*args, **kwargs):
        raise RuntimeError("cleanup failed")

    monkeypatch.setattr(w.store, "cleanup", cleanup_raises)
    task = asyncio.create_task(_daily_cleanup(
        AgentDeps(store=w.store, bus=w.bus, runner=w.runner, settings=w.settings)))

    # Let cleanup loop iterate once
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert "cleanup failed" in caplog.text
    assert caplog.records[0].levelname == "ERROR"


async def test_stream_token_is_scoped_to_runs(env):
    from src.lens.auth import make_stream_token

    w, c, _ = env
    w.model = scripted("готово")
    r = (await c.post("/runs", json={"workspace_id": w.ws.id, "text": "q"})).json()
    await w.wait(r["run_id"])
    secret = lens_settings.stream_secret_value()
    # a board (workspace) token over the same id must not open a run stream
    bare = make_stream_token(r["run_id"], secret)
    assert (await c.get(f"/runs/{r['run_id']}/events",
                        params={"token": bare})).status_code == 403
    for token in (r["stream_token"],
                  (await c.post(f"/runs/{r['run_id']}/stream_token")).json()["stream_token"]):
        async with c.stream("GET", f"/runs/{r['run_id']}/events",
                            params={"token": token}) as s:
            assert s.status_code == 200
