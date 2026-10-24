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
        self.serve_error: BaseException | None = None
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
        state={}, round_status={}, env=env,
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
    assert rec.served == [("MCP", "127.0.0.1", 9105)]
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


async def test_host_is_configurable_and_defaults_to_loopback(monkeypatch):
    rec = _Rec()
    rec.install(monkeypatch)
    _, _, task = _start({"TG_SOURCES_MCP_PORT": "9105", "TG_SOURCES_MCP_HOST": "0.0.0.0"})
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert rec.served == [("MCP", "0.0.0.0", 9105)]
    task.cancel()


async def test_busy_port_systemexit_does_not_kill_the_sweep(monkeypatch):
    """uvicorn при занятом порте делает sys.exit(1): это SystemExit, не Exception."""
    rec = _Rec()
    rec.serve_error = SystemExit(1)
    rec.install(monkeypatch)
    logged = []
    monkeypatch.setattr(T.logger, "exception", lambda *a, **k: logged.append((a, k)))
    _, _, task = _start({"TG_SOURCES_MCP_PORT": "9105"})
    await asyncio.wait_for(task, 1)       # SystemExit не вылетает в цикл
    assert not task.cancelled() and task.exception() is None
    assert logged


async def test_cancellation_still_propagates_through_the_host(monkeypatch):
    rec = _Rec()
    rec.install(monkeypatch)
    _, _, task = _start({"TG_SOURCES_MCP_PORT": "9105"})
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_round_runs_inside_the_shared_lock():
    lock = asyncio.Lock()
    status: dict = {"last_round": None}
    seen = {}

    async def body():
        seen["locked"] = lock.locked()
        waiter = asyncio.create_task(lock.acquire())
        await asyncio.sleep(0.01)
        seen["waiter_blocked"] = not waiter.done()
        waiter.cancel()
        return 3, {"sent": 2}

    await T.run_locked_round(lock, status, body)
    assert seen == {"locked": True, "waiter_blocked": True}
    assert not lock.locked()
    lr = status["last_round"]
    assert lr["ok"] is True and lr["dialogs"] == 3 and lr["tally"] == {"sent": 2}


async def test_failed_round_is_recorded_with_its_reason_and_reraised():
    lock = asyncio.Lock()
    status: dict = {"last_round": {"ok": True, "dialogs": 1, "tally": {}}}

    async def body():
        raise RuntimeError("flood storm")

    with pytest.raises(RuntimeError):
        await T.run_locked_round(lock, status, body)
    lr = status["last_round"]
    assert lr["ok"] is False and "flood storm" in lr["error"] and lr["finished_at"]
    assert not lock.locked()


def test_seed_cursor_creates_the_entry_and_saves():
    state, saved = {}, []
    T.seed_cursor(state, lambda: saved.append(1), -1001, 55, "Новости")
    assert state == {"-1001": {"last_id": 55, "title": "Новости"}}
    assert saved == [1]


def test_seed_cursor_never_moves_the_cursor_back():
    state, saved = {"7": {"last_id": 90, "title": "t"}}, []
    T.seed_cursor(state, lambda: saved.append(1), 7, 55)
    assert state["7"]["last_id"] == 90 and saved == [1]


async def test_host_wires_the_bootstrap_cursor_into_the_sweep_state(monkeypatch):
    rec = _Rec()
    rec.install(monkeypatch)
    state, saved = {}, []
    _tg, _lock, task = _start(
        {"TG_SOURCES_MCP_PORT": "9105"}, state=state, save=lambda: saved.append(1),
    )
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    on_cursor = rec.built[0].kw["ingest"].on_cursor
    on_cursor(-1001, 42)
    assert state["-1001"]["last_id"] == 42 and saved == [1]
    rec.release.set()
    await task


async def test_host_without_save_has_no_cursor_callback(monkeypatch):
    rec = _Rec()
    rec.install(monkeypatch)
    _tg, _lock, task = _start({"TG_SOURCES_MCP_PORT": "9105"})
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert rec.built[0].kw["ingest"].on_cursor is None
    rec.release.set()
    await task


class _RenameRepo:
    def __init__(self, rows):
        self.rows, self.listed, self.remembered = rows, 0, []

    async def list_active(self):
        self.listed += 1
        return self.rows

    async def remember_slug(self, peer_id, slug, *, display=None):
        self.remembered.append((peer_id, slug, display))


def _row(peer_id, slug):
    return SimpleNamespace(peer_id=peer_id, slug=slug)


def _dialog(id, username=None):
    return SimpleNamespace(id=id, entity=SimpleNamespace(username=username))


async def test_renamed_dialog_adds_the_new_key_and_display():
    repo = _RenameRepo([_row(-1001, "@old_name")])
    n = await T.sync_renames(repo, [_dialog(-1001, "New_Name")])
    assert n == 1 and repo.listed == 1
    assert repo.remembered == [(-1001, "@New_Name", "@New_Name")]


async def test_unchanged_dialog_writes_nothing():
    # регистр и «@» — не переименование
    repo = _RenameRepo([_row(-1001, "@Five"), _row(-1002, "")])
    n = await T.sync_renames(repo, [_dialog(-1001, "five"), _dialog(-1002), _dialog(-9, "x")])
    assert n == 0 and repo.remembered == [] and repo.listed == 1


async def test_channel_that_lost_its_username_is_a_rename_too():
    repo = _RenameRepo([_row(-1001, "@five")])
    await T.sync_renames(repo, [_dialog(-1001)])
    assert repo.remembered == [(-1001, "", "")]


@pytest.mark.parametrize(("raw", "depth"), [
    (None, 100), ("", 100), ("0", 0), ("25", 25), ("junk", 100),
])
async def test_apply_bootstrap_is_its_own_knob_defaulting_to_100(monkeypatch, raw, depth):
    rec = _Rec()
    rec.install(monkeypatch)
    env = {"TG_SOURCES_MCP_PORT": "9105", "TG_INGEST_BOOTSTRAP_LIMIT": "0"}
    if raw is not None:
        env["TG_SOURCES_BOOTSTRAP"] = raw
    _, _, task = _start(env)
    await asyncio.sleep(0)
    assert rec.built[0].kw["ingest"].bootstrap == depth
    task.cancel()
