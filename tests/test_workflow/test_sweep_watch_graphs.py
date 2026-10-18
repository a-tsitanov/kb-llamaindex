from contextlib import asynccontextmanager

from src.tenancy.context import default_graph_context, new_graph_context
from src.workflow.monitor import activities as M


async def test_sweep_watch_covers_all_ready_graphs(monkeypatch):
    seen = []

    async def ready(**kw):
        return [default_graph_context(), new_graph_context("acme"), new_graph_context("beta")]

    async def run(repo):
        seen.append(repo.graph.id)
        if repo.graph.id == "beta":
            raise RuntimeError("beta broke")
        return {"new_mention": 2}

    class _Repo:
        def __init__(self, *, graph):
            self.graph = graph

    @asynccontextmanager
    async def hb(*a, **k):
        yield

    monkeypatch.setattr(M.graph_repo, "list_ready_contexts", ready)
    monkeypatch.setattr(M, "run_watch_sweep", run)
    monkeypatch.setattr(M, "WatchRepository", _Repo)
    monkeypatch.setattr(M, "heartbeat_every", hb)
    out = await M.sweep_watch()
    assert seen == ["default", "acme", "beta"]
    assert out.events == 4 and out.by_kind == {"new_mention": 4}
    assert "beta: beta broke" in out.error


async def test_sweep_watch_includes_default_when_registry_down(monkeypatch):
    async def ready(**kw):
        raise ConnectionError("pg down")

    seen = []

    async def run(repo):
        seen.append(repo.graph.id)
        return {}

    class _Repo:
        def __init__(self, *, graph):
            self.graph = graph

    @asynccontextmanager
    async def hb(*a, **k):
        yield

    monkeypatch.setattr(M.graph_repo, "list_ready_contexts", ready)
    monkeypatch.setattr(M, "run_watch_sweep", run)
    monkeypatch.setattr(M, "WatchRepository", _Repo)
    monkeypatch.setattr(M, "heartbeat_every", hb)
    await M.sweep_watch()
    assert seen == ["default"]
