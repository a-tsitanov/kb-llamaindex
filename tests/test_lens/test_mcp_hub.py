import asyncio
from types import SimpleNamespace

from fastmcp import Client, FastMCP
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from src.lens.config import McpServerConfig
from src.lens.mcp_hub import McpHub

kb = FastMCP("kb")


@kb.tool
def find_entity(name: str) -> dict:
    """Find entity by name."""
    return {"results": [{"id": "Q1", "name": name}]}


@kb.tool
def as_text(q: str) -> str:
    return "plain text answer"


@kb.tool
def as_json_text(q: str) -> str:
    return '{"a": 1}'


@kb.tool
def as_list(q: str) -> list[dict]:
    return [{"id": "x"}]


@kb.tool
def boom(q: str) -> dict:
    raise ValueError("kaput")


class _DeadClient:
    async def __aenter__(self):
        raise ConnectionError("refused")

    async def __aexit__(self, *a):
        return False


class _FlakyClient:
    """Connects fine, first call_tool dies like a restarted server."""

    fail_next = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def list_tools(self):
        return [SimpleNamespace(name="ping", description="", inputSchema={})]

    async def call_tool(self, name, args, **kw):
        _FlakyClient.last_kw = kw
        if _FlakyClient.fail_next:
            _FlakyClient.fail_next = False
            raise ConnectionError("session terminated")
        return SimpleNamespace(structured_content={"ok": True}, content=[], is_error=False)


class _McpErrorClient:
    """Connects fine; every call_tool raises an McpError (timeout/JSON-RPC error)."""

    calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def list_tools(self):
        return [SimpleNamespace(name="ping", description="", inputSchema={})]

    async def call_tool(self, name, args, **kw):
        _McpErrorClient.calls += 1
        raise McpError(ErrorData(code=-32001, message="Request timed out"))


class _GenClient:
    """The 1st-generation instance (connected at start()) always fails call_tool;
    every later generation (i.e. after a reconnect) always succeeds."""

    def __init__(self, gen: int):
        self.gen = gen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def list_tools(self):
        return [SimpleNamespace(name="ping", description="", inputSchema={})]

    async def call_tool(self, name, args, **kw):
        await asyncio.sleep(0)  # force a genuine interleaving point between concurrent callers
        if self.gen == 0:
            raise ConnectionError("session terminated")
        return SimpleNamespace(structured_content={"ok": True}, content=[], is_error=False)


def cfg(name, **kw):
    return McpServerConfig(name=name, url=f"memory://{name}", **kw)


async def make_hub(*configs, factory=None, **kw):
    def default_factory(c):
        return {"dead": _DeadClient, "flaky": _FlakyClient}.get(c.name, lambda: Client(kb))()

    hub = McpHub(list(configs), client_factory=factory or default_factory, **kw)
    await hub.start()
    return hub


async def test_catalog_namespace_and_structured_call():
    hub = await make_hub(cfg("kb-tools", namespace="kb"))
    try:
        info = hub.find("kb-tools__find_entity")
        assert info.namespace == "kb"
        assert info.description.startswith("Find entity")
        assert "name" in info.input_schema["properties"]
        res = await hub.call("kb-tools", "find_entity", {"name": "Росатом"})
        assert res.is_error is False
        assert res.payload == {"results": [{"id": "Q1", "name": "Росатом"}]}
    finally:
        await hub.close()


async def test_wrapped_results_are_unwrapped():
    hub = await make_hub(cfg("kb"))
    try:
        assert (await hub.call("kb", "as_text", {"q": "x"})).payload == {
            "text": "plain text answer"}
        assert (await hub.call("kb", "as_json_text", {"q": "x"})).payload == {"a": 1}
        assert (await hub.call("kb", "as_list", {"q": "x"})).payload == [{"id": "x"}]
    finally:
        await hub.close()


async def test_call_error_is_result_not_exception():
    hub = await make_hub(cfg("kb"))
    try:
        res = await hub.call("kb", "boom", {"q": "x"})
        assert res.is_error is True and "kaput" in (res.error or "")
        unknown = await hub.call("nope", "x", {})
        assert unknown.is_error and "unknown server" in unknown.error
    finally:
        await hub.close()


async def test_dead_server_excluded_others_work():
    hub = await make_hub(cfg("dead"), cfg("kb"))
    try:
        st = hub.status()
        assert st["kb"] == "up" and st["dead"].startswith("down: ")
        assert all(t.server == "kb" for t in hub.catalog())
        assert (await hub.call("kb", "find_entity", {"name": "x"})).is_error is False
        assert (await hub.call("dead", "x", {})).error == "server 'dead' not connected"
    finally:
        await hub.close()


async def test_down_server_recovers_on_refresh_after_backoff():
    alive = {"on": False}
    now = {"t": 0.0}

    def factory(c):
        return Client(kb) if alive["on"] else _DeadClient()

    hub = await make_hub(cfg("kb"), factory=factory, backoff_s=10, clock=lambda: now["t"])
    try:
        assert hub.catalog() == []
        alive["on"] = True
        now["t"] = 5
        await hub.refresh()
        assert hub.catalog() == []  # still inside backoff
        now["t"] = 11
        await hub.refresh()
        assert hub.status()["kb"] == "up" and hub.find("kb__find_entity") is not None
    finally:
        await hub.close()


async def test_transport_failure_reconnects_once_and_passes_timeout():
    _FlakyClient.fail_next = True
    hub = await make_hub(cfg("flaky"), timeout_s=7)
    try:
        res = await hub.call("flaky", "ping", {})
        assert res.is_error is False and res.payload == {"ok": True}
        assert _FlakyClient.last_kw == {"timeout": 7, "raise_on_error": False}
    finally:
        await hub.close()


async def test_mcp_error_is_reported_without_disconnect():
    """McpError (request timeout, JSON-RPC error) is a tool-level failure, not a
    dead server: no disconnect/reconnect, the tool stays in the catalog."""
    _McpErrorClient.calls = 0
    hub = await make_hub(cfg("kb-err"), factory=lambda c: _McpErrorClient())
    try:
        res = await hub.call("kb-err", "ping", {})
        assert res.is_error is True and "timed out" in (res.error or "").lower()
        assert hub.status()["kb-err"] == "up"
        assert hub.find("kb-err__ping") is not None
        assert _McpErrorClient.calls == 1  # no retry
    finally:
        await hub.close()


async def test_concurrent_calls_to_down_server_share_one_reconnect():
    """Two concurrent call()s whose shared client dies must trigger exactly one
    reconnect (no leaked AsyncExitStack), and both must succeed on the retry."""
    made = {"n": 0}

    def factory(c):
        made["n"] += 1
        return _GenClient(made["n"] - 1)

    hub = await make_hub(cfg("gen"), factory=factory)
    try:
        r1, r2 = await asyncio.gather(
            hub.call("gen", "ping", {}), hub.call("gen", "ping", {}))
        assert r1.is_error is False and r2.is_error is False
        assert made["n"] == 2  # 1 initial connect (start) + exactly 1 reconnect
        assert hub.status()["gen"] == "up"
    finally:
        await hub.close()


async def test_stale_failing_client_does_not_disconnect_replacement():
    hub = await make_hub(cfg("kb"))
    try:
        old_client = hub._clients["kb"]
        # Simulate: something else (a concurrent call) already replaced the client.
        new_client = object()
        hub._clients["kb"] = new_client
        await hub._disconnect("kb", "stale failure", client=old_client)
        assert hub._clients["kb"] is new_client
        assert hub.status()["kb"] == "up"
        assert hub.catalog()  # tools untouched
    finally:
        await hub.close()


def test_blank_token_becomes_none():
    assert McpServerConfig(name="a", url="u", token="").token is None
    assert McpServerConfig(name="a", url="u", token="  ").token is None
    assert McpServerConfig(name="a", url="u", token="k").token.get_secret_value() == "k"
    assert McpServerConfig(name="a", url="u").ns == "a"
