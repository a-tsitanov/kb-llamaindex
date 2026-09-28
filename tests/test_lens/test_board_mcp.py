import httpx
import pytest
from fastapi import FastAPI
from fastmcp.exceptions import ToolError

from src.lens.board import BoardLimits, BoardService
from src.lens.board_mcp import board_mcp_app
from src.lens.events import EventBus
from src.lens.store import MemoryLensStore
from tests.test_lens.fakes import lifespan_of, mcp_client

TOKEN = "board-secret"
SRC = {"server": "kb-tools", "tool": "find_entity_by_name", "call_id": "c1", "namespace": "kb"}


@pytest.fixture
async def env():
    store, bus = MemoryLensStore(), EventBus()
    board = BoardService(store, bus, BoardLimits(objects_per_call=2))
    ws = await store.create_workspace("t")
    mcp = board_mcp_app(lambda: board, TOKEN)
    app = FastAPI(lifespan=mcp.lifespan)
    app.mount("/mcp", mcp)
    async with lifespan_of(app):
        yield app, ws.id, board


def client(app, headers):
    return mcp_client(app, "http://test/mcp/mcp", headers)


def hdr(ws, run="r1", token=TOKEN):
    return {"Authorization": f"Bearer {token}", "X-Workspace": ws, "X-Run": run}


async def test_tools_round_trip_under_run_headers(env):
    app, ws, board = env
    async with client(app, hdr(ws)) as c:
        names = {t.name for t in await c.list_tools()}
        assert {"get_board", "add_objects", "add_relations", "add_note", "undo"} <= names
        r = await c.call_tool("add_objects", {"objects": [
            {"id": "A", "type": "organization", "label": "Росатом", "source": SRC},
            {"id": "B", "type": "person", "label": "Лихачёв", "source": SRC}]})
        assert r.data["keys"] == ["kb:a", "kb:b"]
        await c.call_tool("add_relations", {"relations": [
            {"from": "kb:b", "to": "kb:a", "kind": "работает_в", "source": SRC}]})
        g = (await c.call_tool("get_board", {})).data
        assert g["total"] == 2 and len(g["relations"]) == 1
    st = await board.state(ws)
    assert st.object_inputs["kb:a"] == ["r1"]


async def test_board_errors_become_tool_errors(env):
    app, ws, _ = env
    async with client(app, hdr(ws)) as c:
        with pytest.raises(ToolError, match="за вызов"):
            await c.call_tool("add_objects", {"objects": [
                {"id": str(i), "label": str(i), "source": SRC} for i in range(3)]})
        with pytest.raises(ToolError, match="нет объекта"):
            await c.call_tool("get_object", {"key": "kb:nope"})


async def test_unknown_workspace_or_missing_run_header(env):
    app, ws, _ = env
    async with client(app, hdr("nope")) as c:
        with pytest.raises(ToolError, match="нет расследования"):
            await c.call_tool("get_board", {})
    async with client(app, {"Authorization": f"Bearer {TOKEN}", "X-Workspace": ws}) as c:
        with pytest.raises(ToolError, match="X-Run"):
            await c.call_tool("get_board", {})


async def test_bearer_token_required(env):
    app, _, _ = env
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as h:
        for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}):
            r = await h.post("/mcp/mcp", json={}, headers=headers)
            assert r.status_code == 401


async def test_bearer_guard_closes_websocket_scope():
    store, bus = MemoryLensStore(), EventBus()
    board = BoardService(store, bus)
    guard = board_mcp_app(lambda: board, TOKEN)
    sent = []

    async def send(message):
        sent.append(message)

    async def receive():  # pragma: no cover - not exercised, guard denies before use
        return {"type": "websocket.receive"}

    await guard({"type": "websocket", "headers": []}, receive, send)
    assert sent == [{"type": "websocket.close", "code": 1008}]


async def test_empty_token_refuses_everything():
    store, bus = MemoryLensStore(), EventBus()
    board = BoardService(store, bus)
    mcp = board_mcp_app(lambda: board, "")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mcp),
                                 base_url="http://test") as h:
        r = await h.post("/mcp", json={}, headers={"Authorization": "Bearer "})
        assert r.status_code == 401
