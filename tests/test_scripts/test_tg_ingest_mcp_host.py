"""Хостинг MCP источников в процессе фидера: тот же клиент и замок, без порта
сервера нет, падение сервера не роняет свип. Ни телеграма, ни транспорта."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import scripts.tg_ingest as T
from src.intake.sources import mcp_server


class _Rec:
    def __init__(self):
        self.built = []
        self.served = []
        self.serve_error: Exception | None = None
        self.release = asyncio.Event()

    def install(self, monkeypatch):
        def build(ops, repo_factory, store, feeder_graph_id, **kw):
            self.built.append(SimpleNamespace(
                ops=ops, repo_factory=repo_factory, graph=feeder_graph_id, kw=kw,
            ))
            return "MCP"

        async def serve(mcp, host, port):
            self.served.append((mcp, host, port))
            if self.serve_error is not None:
                raise self.serve_error
            await self.release.wait()

        monkeypatch.setattr(mcp_server, "build_sources_mcp", build)
        monkeypatch.setattr(mcp_server, "serve_sources_mcp", serve)


def _start(env, **over):
    tg, lock = object(), asyncio.Lock()
    kw = dict(
        http=object(), api_base="http://api", api_key="k", graph=None,
        bootstrap_limit=100, state={}, round_status={}, env=env,
    )
    kw.update(over)
    return tg, lock, T.start_sources_mcp(tg, lock, **kw)


async def test_port_set_starts_server_with_the_same_client_and_lock(monkeypatch):
    rec = _Rec()
    rec.install(monkeypatch)
    tg, lock, task = _start({"TG_SOURCES_MCP_PORT": "9105"})
    assert isinstance(task, asyncio.Task)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    built = rec.built[0]
    assert built.ops._client is tg
    assert built.ops._lock is lock
    assert built.graph == "default"
    assert rec.served == [("MCP", "0.0.0.0", 9105)]
    task.cancel()


async def test_graph_flag_is_the_feeder_graph(monkeypatch):
    rec = _Rec()
    rec.install(monkeypatch)
    _, _, task = _start({"TG_SOURCES_MCP_PORT": "9105"}, graph="acme")
    await asyncio.sleep(0)
    assert rec.built[0].graph == "acme"
    task.cancel()


@pytest.mark.parametrize("env", [{}, {"TG_SOURCES_MCP_PORT": ""}, {"TG_SOURCES_MCP_PORT": " "}])
async def test_without_port_nothing_is_built_or_started(monkeypatch, env):
    rec = _Rec()
    rec.install(monkeypatch)
    _, _, task = _start(env)
    await asyncio.sleep(0)
    assert task is None
    assert rec.built == [] and rec.served == []


async def test_server_crash_is_logged_and_does_not_propagate(monkeypatch):
    rec = _Rec()
    rec.serve_error = RuntimeError("port busy")
    rec.install(monkeypatch)
    logged = []
    monkeypatch.setattr(T.logger, "exception", lambda *a, **k: logged.append((a, k)))
    _, _, task = _start({"TG_SOURCES_MCP_PORT": "9105"})
    await asyncio.wait_for(task, 1)       # не бросает
    assert task.exception() is None
    assert logged


async def test_build_failure_is_also_contained(monkeypatch):
    def build(*a, **k):
        raise RuntimeError("no db")

    monkeypatch.setattr(mcp_server, "build_sources_mcp", build)
    logged = []
    monkeypatch.setattr(T.logger, "exception", lambda *a, **k: logged.append(a))
    _, _, task = _start({"TG_SOURCES_MCP_PORT": "9105"})
    await asyncio.wait_for(task, 1)
    assert task.exception() is None and logged


async def test_bad_port_does_not_kill_the_sweep(monkeypatch):
    rec = _Rec()
    rec.install(monkeypatch)
    _, _, task = _start({"TG_SOURCES_MCP_PORT": "not-a-port"})
    assert task is None and rec.served == []


async def test_status_snapshot_exposes_existing_cursors_and_last_round(monkeypatch):
    rec = _Rec()
    rec.install(monkeypatch)
    state = {"-100": {"title": "Chan", "last_id": 5}}
    round_status = {"last_round": {"dialogs": 2, "tally": {"sent": 1}}}
    _, _, task = _start(
        {"TG_SOURCES_MCP_PORT": "9105"}, state=state, round_status=round_status,
    )
    await asyncio.sleep(0)
    snap = rec.built[0].kw["status"]()
    assert snap == {"cursors": state, "last_round": round_status["last_round"]}
    task.cancel()
