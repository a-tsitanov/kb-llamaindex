"""MCP источников: инструменты — тонкие обёртки; фейки вместо телеграма и Postgres.

Инструменты зовутся напрямую (`tool.fn`), без транспорта FastMCP.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError

from src.intake.sources import mcp_server
from src.intake.sources.mcp_server import build_sources_mcp
from src.intake.sources.proposals import ProposalStore
from src.intake.sources.service import AmbiguousMove
from src.intake.sources.telegram import (
    Candidate,
    FloodWait,
    FolderNotEditable,
    FolderNotFound,
)

TOOLS = (
    "sources_list", "sources_search", "sources_resolve", "sources_propose",
    "sources_apply", "source_move", "source_leave", "source_trust_set",
    "source_report", "feeder_status",
)
# минимальные валидные аргументы каждого инструмента (для проверки «шов первым»)
ARGS = {
    "sources_list": {},
    "sources_search": {"query": "q"},
    "sources_resolve": {"handle": "@a"},
    "sources_propose": {"action": "leave", "channels": [{"peer_id": 1}]},
    "sources_apply": {"proposal_id": "x", "code": "ABCDEF"},
    "source_move": {"proposal_id": "x", "code": "ABCDEF", "peer_id": 1},
    "source_leave": {"proposal_id": "x", "code": "ABCDEF", "peer_id": 1},
    "source_trust_set": {"peer_id": 1, "trust": 0.5},
    "source_report": {"peer_id": 1},
    "feeder_status": {},
}

CTX = SimpleNamespace(graph_id="feeder")


class Ops:
    def __init__(self, log, folders=("news", "digest"), members=None, fail=None):
        self.log = log
        self._folders = list(folders)
        self.members = members or {}
        self.fail = fail or {}

    def _f(self, name):
        self.log.append(name)
        if name in self.fail:
            raise self.fail[name]

    async def folders(self):
        self._f("folders")
        return self._folders

    async def folders_with_members(self):
        self._f("folders_with_members")
        return {f: set(self.members.get(f, set())) for f in self._folders}

    async def search(self, query, limit):
        self._f("search")
        return [Candidate(5, "@five", "Five", 100, True)]

    async def resolve(self, handle):
        self._f("resolve")
        return Candidate(5, "@five", "Five", 100, True) if handle == "@five" else None

    async def join(self, peer_id):
        self._f("join")

    async def add_to_folder(self, peer_id, folder):
        self._f("add_to_folder")
        return True

    async def remove_from_folder(self, peer_id, folder):
        self._f("remove_from_folder")
        return True

    async def leave(self, peer_id):
        self._f("leave")

    async def history(self, peer_id, limit):
        self._f("history")
        return []


class Repo:
    def __init__(self, log, ctx):
        self.log = log
        self.ctx = ctx
        self.rows = {}

    def seed(self, peer_id, group="news", trust=None, state="active"):
        self.rows[peer_id] = SimpleNamespace(
            peer_id=peer_id, slug=f"@c{peer_id}", title=f"C{peer_id}",
            group_name=group, trust=trust, state=state, added_by="bob", note="",
        )

    async def list_active(self):
        self.log.append("repo.list_active")
        return [r for r in self.rows.values() if r.state == "active"]

    async def get(self, peer_id):
        self.log.append("repo.get")
        return self.rows.get(peer_id)

    async def add(self, peer_id, slug, title, group_name, *, added_by):
        self.log.append("repo.add")
        self.seed(peer_id, group_name)
        self.rows[peer_id].added_by = added_by

    async def mark_left(self, peer_id):
        self.log.append("repo.mark_left")
        self.rows[peer_id].state = "left"
        return True

    async def set_group(self, peer_id, group):
        self.log.append("repo.set_group")
        self.rows[peer_id].group_name = group
        return True

    async def set_trust(self, peer_id, trust):
        self.log.append("repo.set_trust")
        self.rows[peer_id].trust = trust
        return True


class Env:
    def __init__(self, monkeypatch, *, ops_kw=None, status=None, **build_kw):
        self.log: list = []
        self.ops = Ops(self.log, **(ops_kw or {}))
        self.store = ProposalStore()
        self.repos: list[Repo] = []
        self.shared = None

        def factory(ctx):
            self.log.append("repo_factory")
            if self.shared is None:
                self.shared = Repo(self.log, ctx)
            self.repos.append(self.shared)
            return self.shared

        async def access(graph_id):
            self.log.append(("access", graph_id))
            return CTX

        monkeypatch.setattr(mcp_server, "require_sources_access", access)
        monkeypatch.setattr(mcp_server, "current_principal", lambda: "alice")
        kw = {}
        if status is not None:
            kw["status"] = status
        kw.update(build_kw)
        self.mcp = build_sources_mcp(self.ops, factory, self.store, "feeder", **kw)

    @property
    def repo(self) -> Repo:
        if self.shared is None:
            self.shared = Repo(self.log, CTX)
        return self.shared

    async def call(self, name, **kw):
        tool = await self.mcp.get_tool(name)
        return await tool.fn(**kw)


@pytest.fixture
def env(monkeypatch):
    return Env(monkeypatch)


# ---------- шов доступа первым ----------


async def test_exposes_exactly_the_documented_tools(env):
    names = {t.name for t in await env.mcp.list_tools()}
    assert names == set(TOOLS)


@pytest.mark.parametrize("name", TOOLS)
async def test_every_tool_checks_access_before_anything_else(monkeypatch, name):
    e = Env(monkeypatch)

    async def deny(graph_id):
        e.log.append(("access", graph_id))
        raise ToolError("forbidden: sources not allowed")

    monkeypatch.setattr(mcp_server, "require_sources_access", deny)
    with pytest.raises(ToolError, match="forbidden"):
        await e.call(name, **ARGS[name])
    # дальше шва не дошли ни до телеграма, ни до базы
    assert e.log == [("access", "feeder")]


async def test_repo_is_built_from_the_context_the_seam_returned(env):
    await env.call("sources_list")
    assert env.log[0] == ("access", "feeder")
    assert env.repos and env.repos[0].ctx is CTX


# ---------- список ----------


async def test_sources_list_reports_group_trust_and_folder_divergence(monkeypatch):
    e = Env(monkeypatch, ops_kw={"members": {"news": {1}, "digest": set()}})
    e.repo.seed(1, "news", trust=0.9)
    e.repo.seed(2, "news")          # убрали из папки руками
    e.repo.seed(3, "digest", trust=0.2)
    e.repo.seed(4, "official", state="left")   # не активный — не в списке
    out = await e.call("sources_list")
    by = {s["peer_id"]: s for s in out["sources"]}
    assert set(by) == {1, 2, 3}
    assert by[1]["group"] == "news" and by[1]["trust"] == 0.9 and by[1]["in_folder"] is True
    assert by[2]["in_folder"] is False and by[2]["trust"] is None
    assert by[3]["in_folder"] is False
    assert out["folders"] == ["news", "digest"]
    # состав всех папок читается ОДНИМ обращением, а не по запросу на группу
    assert env_log_count(e.log, "folders_with_members") == 1
    assert "folders" not in e.log


def env_log_count(log, name):
    return sum(1 for x in log if x == name)


async def test_sources_list_missing_folder_is_divergence_not_error(monkeypatch):
    e = Env(monkeypatch, ops_kw={"members": {}})
    e.repo.seed(1, "news")
    out = await e.call("sources_list")
    assert out["sources"][0]["in_folder"] is False


# ---------- поиск / резолв ----------


async def test_search_marks_already_connected(env):
    env.repo.seed(5, "news")
    out = await env.call("sources_search", query="x", limit=5)
    assert out["candidates"] == [{
        "peer_id": 5, "slug": "@five", "title": "Five",
        "participants": 100, "public": True, "connected": True,
    }]


async def test_resolve_unknown_handle_is_none(env):
    assert (await env.call("sources_resolve", handle="@nobody")) == {"candidate": None}
    out = await env.call("sources_resolve", handle="@five")
    assert out["candidate"]["peer_id"] == 5


# ---------- петля подтверждения ----------


async def _propose_connect(env, group="news"):
    return await env.call(
        "sources_propose", action="connect",
        channels=[{"peer_id": 5, "slug": "@five", "title": "Five", "group": group}],
    )


async def test_propose_returns_items_and_one_time_code_and_touches_no_telegram(env):
    out = await _propose_connect(env)
    assert out["code"] and out["proposal_id"] and out["action"] == "connect"
    assert out["items"][0]["peer_id"] == 5 and out["items"][0]["group"] == "news"
    assert env.log == [("access", "feeder")] or "join" not in env.log
    assert "join" not in env.log and "add_to_folder" not in env.log


async def test_propose_rejects_group_outside_group_set(env):
    with pytest.raises(ToolError, match="групп"):
        await _propose_connect(env, group="memes")


async def test_apply_requires_the_code(env):
    out = await _propose_connect(env)
    env.log.clear()
    with pytest.raises(ToolError, match="код"):
        await env.call("sources_apply", proposal_id=out["proposal_id"], code="WRONG1")
    assert "join" not in env.log and "add_to_folder" not in env.log


async def test_apply_with_code_connects_and_is_one_shot(env):
    out = await _propose_connect(env)
    res = await env.call("sources_apply", proposal_id=out["proposal_id"], code=out["code"])
    assert res["connected"] == [5] and res["skipped"] == []
    assert env.repo.rows[5].group_name == "news"
    assert env.repo.rows[5].added_by == "alice"
    with pytest.raises(ToolError, match=r"использован|просрочен"):
        await env.call("sources_apply", proposal_id=out["proposal_id"], code=out["code"])


async def test_leave_requires_the_code(env):
    env.repo.seed(7, "news")
    p = await env.call("sources_propose", action="leave", channels=[{"peer_id": 7}])
    env.log.clear()
    with pytest.raises(ToolError, match="код"):
        await env.call("source_leave", proposal_id=p["proposal_id"], code="WRONG1", peer_id=7)
    assert "leave" not in env.log


async def test_leave_with_code_leaves_and_marks(env):
    env.repo.seed(7, "news")
    p = await env.call("sources_propose", action="leave", channels=[{"peer_id": 7}])
    res = await env.call("source_leave", proposal_id=p["proposal_id"], code=p["code"], peer_id=7)
    assert res == {"left": True, "peer_id": 7}
    assert "leave" in env.log and env.repo.rows[7].state == "left"


async def test_move_goes_to_the_folder_the_user_approved(env):
    env.repo.seed(7, "news")
    p = await env.call(
        "sources_propose", action="move", channels=[{"peer_id": 7, "group": "digest"}],
    )
    res = await env.call("source_move", proposal_id=p["proposal_id"], code=p["code"], peer_id=7)
    assert res["folder"] == "digest"
    assert env.repo.rows[7].group_name == "digest"


async def test_move_unknown_proposal_is_refused_before_telegram(env):
    env.repo.seed(7, "news")
    env.log.clear()
    with pytest.raises(ToolError, match="предложени"):
        await env.call("source_move", proposal_id="nope", code="ABCDEF", peer_id=7)
    assert "add_to_folder" not in env.log


async def test_move_and_leave_proposals_are_single_channel(env):
    env.repo.seed(7, "news")
    env.repo.seed(8, "news")
    with pytest.raises(ToolError, match="один"):
        await env.call("sources_propose", action="leave",
                       channels=[{"peer_id": 7}, {"peer_id": 8}])


async def test_trust_set_returns_row_and_never_asks_a_code(env):
    env.repo.seed(7, "news")
    res = await env.call("source_trust_set", peer_id=7, trust=0.4)
    assert res["trust"] == 0.4 and res["peer_id"] == 7
    with pytest.raises(ToolError, match="доверие"):
        await env.call("source_trust_set", peer_id=7, trust=3.0)


async def test_report_delegates_with_context(env, monkeypatch):
    seen = {}

    async def fake_report(graph, peer_id, *, days=30):
        seen.update(graph=graph, peer_id=peer_id, days=days)
        return {"volume": 1}

    monkeypatch.setattr(mcp_server, "channel_report", fake_report)
    out = await env.call("source_report", peer_id=9, days=7)
    assert out == {"volume": 1}
    assert seen == {"graph": CTX, "peer_id": 9, "days": 7}


# ---------- перевод ошибок ----------


@pytest.mark.parametrize("exc, needles", [
    (FloodWait(42), ["42"]),
    (FolderNotEditable("x", folder="digest"), ["digest", "общий список"]),
    (FolderNotFound("x", folder="memes"), ["memes", "не создаёт"]),
    (AmbiguousMove("x", old="news", new="digest", seconds=9), ["news", "digest", "9", "Повтор переноса сходится"]),
])
async def test_telegram_errors_become_actionable_tool_errors(monkeypatch, exc, needles):
    e = Env(monkeypatch, ops_kw={"fail": {"search": exc}})

    async def boom(query, limit):
        raise exc

    e.ops.search = boom
    with pytest.raises(ToolError) as ei:
        await e.call("sources_search", query="x")
    for n in needles:
        assert n in str(ei.value)
    assert type(ei.value) is ToolError


async def test_bad_proposal_is_a_refusal_naming_the_causes(env):
    with pytest.raises(ToolError) as ei:
        await env.call("sources_apply", proposal_id="nope", code="ABCDEF")
    msg = str(ei.value)
    for n in ("код", "просрочен", "использован", "другого"):
        assert n in msg


# ---------- feeder_status ----------


async def test_feeder_status_reports_cursors_last_round_and_folders(monkeypatch):
    status = lambda: {  # noqa: E731
        "cursors": {"-100": {"title": "Chan", "last_id": 77}},
        "last_round": {"dialogs": 3, "tally": {"sent": 2}, "finished_at": "t"},
    }
    e = Env(monkeypatch, status=status)
    out = await e.call("feeder_status")
    assert out["cursors"] == {"-100": {"title": "Chan", "last_id": 77}}
    assert out["last_round"]["tally"] == {"sent": 2}
    assert out["folders"] == ["news", "digest"]


async def test_feeder_status_without_a_finished_round(env):
    out = await env.call("feeder_status")
    assert out["last_round"] is None and out["cursors"] == {}


# ---------- замечания ревью ----------


async def test_move_with_wrong_code_is_refused_and_nothing_reaches_telegram(env):
    env.repo.seed(7, "news")
    p = await env.call(
        "sources_propose", action="move", channels=[{"peer_id": 7, "group": "digest"}],
    )
    env.log.clear()
    with pytest.raises(ToolError, match="код не принят"):
        await env.call("source_move", proposal_id=p["proposal_id"], code="WRONG1", peer_id=7)
    assert not {"add_to_folder", "remove_from_folder", "join", "leave"} & set(env.log)
    assert env.repo.rows[7].group_name == "news"


async def test_move_with_code_issued_for_another_channel_is_refused(env):
    env.repo.seed(7, "news")
    env.repo.seed(8, "news")
    p = await env.call(
        "sources_propose", action="move", channels=[{"peer_id": 7, "group": "digest"}],
    )
    env.log.clear()
    with pytest.raises(ToolError, match="код не принят"):
        await env.call("source_move", proposal_id=p["proposal_id"], code=p["code"], peer_id=8)
    assert not {"add_to_folder", "remove_from_folder"} & set(env.log)
    assert env.repo.rows[8].group_name == "news"


async def test_sources_list_reports_floodwait_instead_of_a_traceback(monkeypatch):
    e = Env(monkeypatch, ops_kw={"fail": {"folders_with_members": FloodWait(33)}})
    e.repo.seed(1, "news")
    with pytest.raises(ToolError, match="33") as ei:
        await e.call("sources_list")
    assert type(ei.value) is ToolError


async def test_foreign_errors_are_not_passed_to_the_harness_as_text(monkeypatch):
    e = Env(monkeypatch)

    async def boom():
        raise KeyError("driver internals")

    e.repo.list_active = boom
    with pytest.raises(KeyError):
        await e.call("sources_list")

    async def boom2():
        raise ValueError("asyncpg: invalid input")

    e.repo.list_active = boom2
    with pytest.raises(ValueError) as ei:
        await e.call("sources_list")
    assert not isinstance(ei.value, ToolError)


async def test_own_input_errors_still_reach_the_harness(env):
    with pytest.raises(ToolError, match="не из connect"):
        await env.call("sources_propose", action="nope", channels=[])
    with pytest.raises(ToolError, match="не подключён"):
        await env.call("source_trust_set", peer_id=404, trust=0.5)


async def test_approved_moves_are_pruned_when_used_or_expired(monkeypatch):
    now = [0.0]
    approved: dict = {}
    e = Env(monkeypatch, approved_moves=approved)
    e.store._clock = lambda: now[0]
    e.repo.seed(7, "news")
    e.repo.seed(8, "news")
    p7 = await e.call(
        "sources_propose", action="move", channels=[{"peer_id": 7, "group": "digest"}],
    )
    assert list(approved) == [p7["proposal_id"]]
    # использованное предложение уходит
    await e.call("source_move", proposal_id=p7["proposal_id"], code=p7["code"], peer_id=7)
    assert approved == {}
    # просроченное уходит при следующем предложении
    await e.call(
        "sources_propose", action="move", channels=[{"peer_id": 8, "group": "digest"}],
    )
    assert len(approved) == 1
    now[0] += 10_000
    await e.call(
        "sources_propose", action="move", channels=[{"peer_id": 8, "group": "official"}],
    )
    assert len(approved) == 1


async def test_feeder_status_answers_while_someone_holds_the_lock(monkeypatch):
    lock = asyncio.Lock()
    status = lambda: {  # noqa: E731
        "cursors": {"-100": {"last_id": 1}},
        "last_round": {"ok": True, "tally": {}},
    }
    e = Env(monkeypatch, status=status, folders_timeout=0.05)

    async def locked_folders():
        async with lock:
            return ["news"]

    e.ops.folders = locked_folders
    await lock.acquire()          # свип сидит в раунде
    try:
        out = await asyncio.wait_for(e.call("feeder_status"), 2)
    finally:
        lock.release()
    assert out["cursors"] == {"-100": {"last_id": 1}}
    assert out["last_round"]["ok"] is True
    assert out["folders"] is None
    assert out["folders_state"] == "unavailable"


async def test_feeder_status_survives_any_folders_error(monkeypatch):
    """Папки — не предмет диагностики: оборванная сессия или любой другой сбой
    чтения папок не должен лишать оператора курсоров и прошлого раунда."""
    status = {"cursors": {"-100": {"last_id": 7}}, "last_round": {"ok": True, "tally": {}}}
    e = Env(monkeypatch, status=lambda: status)

    async def broken_folders():
        raise ConnectionError("сессия телеграма оборвалась")

    e.ops.folders = broken_folders
    out = await e.call("feeder_status")
    assert out["cursors"] == {"-100": {"last_id": 7}}
    assert out["folders"] is None and out["folders_state"] == "unavailable"


async def test_feeder_status_marks_folders_stale_after_a_timeout(monkeypatch):
    lock = asyncio.Lock()
    e = Env(monkeypatch, folders_timeout=0.05)
    first = await e.call("feeder_status")
    assert first["folders"] == ["news", "digest"] and first["folders_state"] == "fresh"

    async def locked_folders():
        async with lock:
            return ["news"]

    e.ops.folders = locked_folders
    await lock.acquire()
    try:
        out = await e.call("feeder_status")
    finally:
        lock.release()
    assert out["folders"] == ["news", "digest"] and out["folders_state"] == "stale"
