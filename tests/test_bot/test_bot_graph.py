"""The bot reaches graph data only over the HTTP API, so it binds to one graph
by sending ``X-Graph: <BOT_GRAPH>`` on every KB call (spec §4, Task 11)."""

from __future__ import annotations

import sys
import types

import httpx
import pytest

from src.bot import search_client, stats_client


def _client_patch(monkeypatch, seen: list):
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("X-Graph"))
        return httpx.Response(200, json={})

    def _factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


def _calls(graph):
    kw = {"api_base": "http://api:8000", "api_key": "k"}
    if graph is not None:
        kw["graph"] = graph
    return [
        lambda: search_client.make_search(**kw)("q"),
        lambda: search_client.make_search_full(**kw)("q"),
        lambda: search_client.make_analyze(**kw)("q"),
        lambda: stats_client.make_channels(**kw)(),
        lambda: stats_client.make_timeline(**kw)(),
        lambda: stats_client.make_entities(**kw)("q"),
    ]


@pytest.mark.parametrize("graph, expected", [(None, "default"), ("acme", "acme")])
async def test_every_kb_call_sends_x_graph(monkeypatch, graph, expected):
    seen: list = []
    _client_patch(monkeypatch, seen)
    for call in _calls(graph):
        await call()
    assert seen == [expected] * 6


def test_bot_graph_setting_defaults_to_default(monkeypatch):
    from src.config import BotSettings

    monkeypatch.delenv("BOT_GRAPH", raising=False)
    assert BotSettings(_env_file=None).graph == "default"
    monkeypatch.setenv("BOT_GRAPH", "acme")
    assert BotSettings(_env_file=None).graph == "acme"


@pytest.fixture
def bot_main(monkeypatch):
    """Import the bot entrypoint; stub aiogram (the `bot` extra) when absent
    so ``build_ctx`` wiring is testable in the dev env."""
    try:
        import aiogram  # noqa: F401
    except ImportError:
        fake = types.ModuleType("aiogram")
        fake.Bot = fake.Dispatcher = object
        filters = types.ModuleType("aiogram.filters")
        filters.Command = filters.CommandObject = object
        tys = types.ModuleType("aiogram.types")
        tys.Message = object
        monkeypatch.setitem(sys.modules, "aiogram", fake)
        monkeypatch.setitem(sys.modules, "aiogram.filters", filters)
        monkeypatch.setitem(sys.modules, "aiogram.types", tys)
        monkeypatch.delitem(sys.modules, "src.bot.__main__", raising=False)
    import src.bot.__main__ as mod

    return mod


def test_build_ctx_binds_every_client_to_bot_graph(monkeypatch, bot_main):

    seen: list = []

    def _spy(*a, **kw):
        seen.append(kw.get("graph"))
        return object()

    for name in ("make_search_full", "make_channels", "make_timeline", "make_entities"):
        monkeypatch.setattr(bot_main, name, _spy)
    monkeypatch.setattr(bot_main, "BotRepository", lambda: object())
    monkeypatch.setattr(bot_main, "make_rewrite", lambda: None)
    monkeypatch.setattr(bot_main.settings.bot, "graph", "acme", raising=False)
    bot_main.build_ctx()
    assert seen and all(g == "acme" for g in seen)
    assert len(seen) == 5


def test_build_ctx_rejects_invalid_bot_graph(monkeypatch, bot_main):
    from src.tenancy.context import InvalidGraphId

    monkeypatch.setattr(bot_main.settings.bot, "graph", "Bad Graph!", raising=False)
    with pytest.raises(InvalidGraphId):
        bot_main.build_ctx()
