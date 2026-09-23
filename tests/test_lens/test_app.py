import json

import httpx
import pytest

from src.lens.app import LensDeps, create_app
from src.lens.auth import check_stream_token, make_stream_token
from src.lens.config import lens_settings
from src.lens.events import EventBus
from src.lens.model import ToolCallRecord
from src.lens.store import MemoryLensStore

KEY = "test-lens-key"


class FakeAgent:
    def __init__(self, store):
        self.store = store
        self.submitted = []

    async def submit(self, ws, text, mentions):
        self.submitted.append((ws, text, mentions))
        return "i1"

    async def pin(self, ws, key, x, y):
        return await self.store.append_ops(ws, None, [("pin", {"key": key, "x": x, "y": y})])


class FakeHub:
    def status(self):
        return {"kb": "up"}


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(lens_settings, "api_keys", KEY)
    store = MemoryLensStore()
    deps = LensDeps(store=store, bus=EventBus(), agent=FakeAgent(store), hub=FakeHub())
    app = create_app(deps)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", headers={"X-API-Key": KEY}) as c:
        c.deps = deps
        yield c


async def test_health_is_public(client):
    r = await client.get("/lens/v1/health", headers={"X-API-Key": ""})
    assert r.json() == {"mcp": {"kb": "up"}}


async def test_auth_header_only_and_own_keys(client):
    assert (await client.get("/lens/v1/workspaces", headers={"X-API-Key": ""})).status_code \
        == 401
    assert (await client.get(f"/lens/v1/workspaces?key={KEY}",
                             headers={"X-API-Key": ""})).status_code == 401
    assert (await client.get("/lens/v1/workspaces",
                             headers={"X-API-Key": "dev-local-key"})).status_code == 403


async def test_workspace_input_pin_state_ops(client):
    ws = (await client.post("/lens/v1/workspaces", json={"title": "Росатом"})).json()
    r = await client.post(f"/lens/v1/workspaces/{ws['id']}/input",
                          json={"text": "встречи", "mentions": ["kb:1"]})
    assert r.status_code == 202 and r.json() == {"input_id": "i1"}
    assert client.deps.agent.submitted == [(ws["id"], "встречи", ["kb:1"])]
    assert (await client.post(f"/lens/v1/workspaces/{ws['id']}/input",
                              json={"text": "  "})).status_code == 422
    for i in range(2):
        r = await client.post(f"/lens/v1/workspaces/{ws['id']}/pin",
                              json={"key": "kb:1", "x": i, "y": 2})
    assert r.json() == {"seq": 2}
    body = (await client.get(f"/lens/v1/workspaces/{ws['id']}")).json()
    assert body["workspace"]["title"] == "Росатом" and body["state"]["last_seq"] == 2
    ops = (await client.get(f"/lens/v1/workspaces/{ws['id']}/ops",
                            params={"after_seq": 1})).json()
    assert [o["seq"] for o in ops] == [2]
    assert (await client.get("/lens/v1/workspaces/nope")).status_code == 404


async def test_tool_call_value_rows_and_filter(client):
    payload = {"hosts": [{"ip": f"10.0.0.{i}", "port": 22 + i} for i in range(5)]}
    await client.deps.store.add_tool_call(ToolCallRecord(
        id="c1", input_id=None, server="fofa", tool="hosts", args={}, payload=payload,
        shape_hash="h", latency_ms=1))
    v = await client.get("/lens/v1/tool_calls/c1/value", params={"path": "$.hosts[1].ip"})
    assert v.json() == {"value": "10.0.0.1"}
    cols = json.dumps([{"name": "ip", "path": "$.ip"}, {"name": "port", "path": "$.port"}])
    r = (await client.get("/lens/v1/tool_calls/c1/rows",
                          params={"path": "$.hosts[*]", "columns": cols, "offset": 1,
                                  "limit": 2})).json()
    assert r == {"total": 5, "rows": [{"ip": "10.0.0.1", "port": 23},
                                      {"ip": "10.0.0.2", "port": 24}]}
    f = (await client.get("/lens/v1/tool_calls/c1/rows",
                          params={"path": "$.hosts[*]", "columns": cols,
                                  "filter": json.dumps({"*": ["22", "25"]})})).json()
    assert [row["port"] for row in f["rows"]] == [22, 25] and f["total"] == 2
    assert (await client.get("/lens/v1/tool_calls/zz/value",
                             params={"path": "$"})).status_code == 404
    assert (await client.get("/lens/v1/tool_calls/c1/value",
                             params={"path": "hosts"})).status_code == 400


async def test_stream_requires_workspace_bound_token(client):
    ws = (await client.post("/lens/v1/workspaces", json={"title": "s"})).json()
    other = (await client.post("/lens/v1/workspaces", json={"title": "o"})).json()
    token = (await client.post(f"/lens/v1/workspaces/{ws['id']}/stream_token")).json()["token"]
    url = f"/lens/v1/workspaces/{other['id']}/stream"
    assert (await client.get(url, params={"token": token})).status_code == 401
    assert (await client.get(f"/lens/v1/workspaces/{ws['id']}/stream",
                             params={"token": "bad"})).status_code == 401
    # The SSE body itself is covered by test_events.py; httpx's ASGITransport buffers
    # whole bodies, so an infinite stream can't be read here.


def test_stream_token_expiry():
    tok = make_stream_token("w", "s", ttl_s=10, now=1000)
    assert check_stream_token(tok, "w", "s", now=1005)
    assert not check_stream_token(tok, "w", "s", now=1011)
    assert not check_stream_token(tok, "w", "other-secret", now=1005)
    assert not check_stream_token("garbage", "w", "s", now=1005)


def test_key_is_valid_checks_all_keys():
    from src.lens.auth import key_is_valid
    assert key_is_valid("b", ["a", "b"])
    assert not key_is_valid("c", ["a", "b"])
    assert not key_is_valid("", [])
    assert key_is_valid("ключ", ["ключ"])
