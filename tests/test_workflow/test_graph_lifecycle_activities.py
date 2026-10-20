from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from src.tenancy.context import new_graph_context
from src.tenancy.registry import GraphNotFound
from src.workflow.graph_lifecycle import activities as A
from src.workflow.graph_lifecycle.contracts import GraphLifecycleIn, SetStatusIn

ACME = replace(new_graph_context("acme"), generation=3)


# Row status the fake repo reports; None = whatever the step expects.
ROW_STATUS: dict[str, str | None] = {}


@pytest.fixture
def repo(monkeypatch):
    calls = []
    ROW_STATUS.clear()

    async def load(gid, expect=None, **kw):
        if gid == "gone":
            raise GraphNotFound(gid)
        status = ROW_STATUS.get(gid)
        if expect is not None and status is not None and status != expect:
            raise A.graph_repo.GraphStateChanged(gid, status, expect)
        return ACME

    async def set_status(gid, status, error="", **kw):
        calls.append(("status", gid, status, error))

    async def delete_row(gid, expect=None, **kw):
        calls.append(("delete", gid, expect))
        return True

    monkeypatch.setattr(A.graph_repo, "load_context_any_status", load)
    monkeypatch.setattr(A.graph_repo, "set_status", set_status)
    monkeypatch.setattr(A.graph_repo, "delete_row", delete_row)
    return calls


@pytest.mark.parametrize("fn", [A.provision_nebula, A.provision_milvus, A.provision_pg,
                                A.drop_nebula, A.drop_milvus, A.drop_pg, A.purge_minio,
                                A.terminate_graph_ingests, A.delete_graph_row])
async def test_drop_refuses_default_everywhere(fn, repo):
    with pytest.raises(ApplicationError) as ei:
        await fn(GraphLifecycleIn(graph_id="default"))
    assert ei.value.type == "DefaultGraphProtected" and ei.value.non_retryable


async def test_provision_unknown_graph_is_non_retryable(repo):
    with pytest.raises(ApplicationError) as ei:
        await A.provision_pg(GraphLifecycleIn(graph_id="gone"))
    assert ei.value.type == "GraphUnavailable" and ei.value.non_retryable


async def test_drop_on_missing_row_is_noop(repo):
    assert await A.drop_pg(GraphLifecycleIn(graph_id="gone")) is None


async def test_provision_pg_raises_when_tables_missing(repo, monkeypatch):
    monkeypatch.setattr(A, "_pg_provision_sync", lambda g: ["entity"])
    with pytest.raises(ApplicationError) as ei:
        await A.provision_pg(GraphLifecycleIn(graph_id="acme"))
    assert "entity" in str(ei.value) and not ei.value.non_retryable


async def test_provision_nebula_raises_when_schema_missing(repo, monkeypatch):
    monkeypatch.setattr(A, "_nebula_provision_sync", lambda g: ["Community"])
    with pytest.raises(ApplicationError):
        await A.provision_nebula(GraphLifecycleIn(graph_id="acme"))


async def test_provision_milvus_checks_all_three(repo, monkeypatch):
    seen = []
    monkeypatch.setattr(A, "_milvus_provision_sync", lambda g: seen.append(g.id) or [])
    await A.provision_milvus(GraphLifecycleIn(graph_id="acme"))
    assert seen == ["acme"]


async def test_set_status_invalidates_local_registry(repo, monkeypatch):
    invalidated = []

    class _Reg:
        def invalidate(self, gid=None):
            invalidated.append(gid)

    monkeypatch.setattr(A, "get_graph_registry", lambda: _Reg())
    await A.set_graph_status(SetStatusIn(graph_id="acme", status="ready"))
    assert repo == [("status", "acme", "ready", "")] and invalidated == ["acme"]


async def test_terminate_graph_ingests_targets_scoped_ids(repo, monkeypatch):
    monkeypatch.setattr(A, "_inflight_doc_ids", _async_return(["d1", "d2"]))
    terminated = []

    class _H:
        def __init__(self, wid):
            self.wid = wid

        async def terminate(self, reason=None):
            if self.wid.endswith("d2") and self.wid.startswith("graph-"):
                from temporalio.service import RPCError, RPCStatusCode
                raise RPCError("not found", RPCStatusCode.NOT_FOUND, b"")
            terminated.append(self.wid)

    class _Client:
        def get_workflow_handle(self, wid):
            return _H(wid)

        def list_workflows(self, query):
            return _aiter([])

    monkeypatch.setattr(A, "get_temporal_client", _async_return(_Client()))
    heartbeats = []
    env = ActivityEnvironment()
    env.on_heartbeat = lambda *d: heartbeats.append(d)
    n = await env.run(A.terminate_graph_ingests, GraphLifecycleIn(graph_id="acme"))
    assert terminated == ["ingest-acme-d1", "graph-acme-d1", "ingest-acme-d2"]
    assert n == 3
    assert heartbeats == [(2,), (3,)]


async def test_terminate_graph_ingests_also_terminates_graph_wide_workflows(repo, monkeypatch):
    # community-build / analytics-materialize activities would otherwise
    # re-create the dropped Milvus collections after drop_milvus.
    monkeypatch.setattr(A, "_inflight_doc_ids", _async_return([]))
    terminated, queries = [], []

    class _H:
        def __init__(self, wid):
            self.wid = wid

        async def terminate(self, reason=None):
            terminated.append(self.wid)

    class _Client:
        def get_workflow_handle(self, wid):
            return _H(wid)

        def list_workflows(self, query):
            queries.append(query)
            prefix = query.split("'")[1]
            return _aiter([SimpleNamespace(id=prefix + "abc")])

    monkeypatch.setattr(A, "get_temporal_client", _async_return(_Client()))
    n = await ActivityEnvironment().run(A.terminate_graph_ingests, GraphLifecycleIn(graph_id="acme"))
    assert terminated == ["community-build-acme-abc", "analytics-materialize-acme-abc"]
    assert n == 2
    assert all("ExecutionStatus = 'Running'" in q for q in queries)
    assert "WorkflowId STARTS_WITH 'community-build-acme-'" in queries[0]


async def test_terminate_graph_ingests_tolerates_visibility_without_starts_with(repo, monkeypatch):
    from temporalio.service import RPCError, RPCStatusCode

    monkeypatch.setattr(A, "_inflight_doc_ids", _async_return([]))

    class _Client:
        def list_workflows(self, query):
            raise RPCError("bad query", RPCStatusCode.INVALID_ARGUMENT, b"")

    monkeypatch.setattr(A, "get_temporal_client", _async_return(_Client()))
    assert await ActivityEnvironment().run(
        A.terminate_graph_ingests, GraphLifecycleIn(graph_id="acme"),
    ) == 0


class _PgCur:
    def __init__(self, has_processing):
        self.has_processing, self.sql = has_processing, []

    async def execute(self, q, params=None):
        self.sql.append(q)
        if "FROM doc_processing" in q and not self.has_processing:
            import psycopg

            raise psycopg.errors.UndefinedTable('relation "doc_processing" does not exist')

    async def fetchone(self):
        return ("doc_processing",) if self.has_processing else (None,)

    async def fetchall(self):
        return [("d1",), ("d2",)]


def _fake_graph_connection(cur):
    @asynccontextmanager
    async def graph_connection(graph, timeout=None):
        class _Conn:
            def cursor(self):
                @asynccontextmanager
                async def cm():
                    yield cur
                return cm()
        yield _Conn()
    return graph_connection


@pytest.mark.parametrize("has_processing, expected", [(False, []), (True, ["d1", "d2"])])
async def test_inflight_doc_ids_tolerates_missing_schema(monkeypatch, has_processing, expected):
    # Delete retried after drop_pg, or of a graph whose provisioning failed
    # before provision_pg: no g_<id> schema, no `public` fallback (R-P5).
    from src.storage import pg_scope

    cur = _PgCur(has_processing)
    monkeypatch.setattr(pg_scope, "graph_connection", _fake_graph_connection(cur))
    assert await A._inflight_doc_ids(ACME) == expected


async def test_purge_minio_batches_with_heartbeats(repo, monkeypatch):
    batches = iter([1000, 1000, 5, 0])
    monkeypatch.setattr(A, "_minio_purge_sync", lambda g: next(batches))
    heartbeats = []
    env = ActivityEnvironment()
    env.on_heartbeat = lambda *d: heartbeats.append(d)
    assert await env.run(A.purge_minio, GraphLifecycleIn(graph_id="acme")) == 2005
    assert heartbeats == [(1000,), (2000,), (2005,)]


async def test_set_status_passes_expected_status(repo, monkeypatch):
    seen = []

    async def set_status(gid, status, error="", **kw):
        seen.append((gid, status, kw.get("expect")))

    monkeypatch.setattr(A.graph_repo, "set_status", set_status)
    monkeypatch.setattr(A, "get_graph_registry", lambda: SimpleNamespace(invalidate=lambda g=None: None))
    await A.set_graph_status(SetStatusIn(graph_id="acme", status="ready", expect="provisioning"))
    assert seen == [("acme", "ready", "provisioning")]


def _async_return(value):
    async def f(*a, **k):
        return value
    return f


async def _aiter(items):
    for i in items:
        yield i


_TEARDOWN = [A.terminate_graph_ingests, A.drop_nebula, A.drop_milvus, A.drop_pg,
             A.purge_minio, A.delete_graph_row]
_PROVISION = [A.provision_nebula, A.provision_milvus, A.provision_pg]


def _forbid_storage(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("storage touched on a graph in the wrong state")

    for name in ("_nebula_drop_sync", "_milvus_drop_sync", "_pg_drop_sync", "_minio_purge_sync",
                 "_nebula_provision_sync", "_milvus_provision_sync", "_pg_provision_sync",
                 "_inflight_doc_ids", "get_temporal_client"):
        monkeypatch.setattr(A, name, boom)


@pytest.mark.parametrize("fn", _TEARDOWN)
async def test_teardown_refuses_graph_no_longer_deleting(fn, repo, monkeypatch):
    # A stale delete workflow (its start reported as failed, the graph then
    # resumed to `ready`) must not drop the re-created graph or its row.
    ROW_STATUS["acme"] = "ready"
    _forbid_storage(monkeypatch)
    with pytest.raises(ApplicationError) as ei:
        await ActivityEnvironment().run(fn, GraphLifecycleIn(graph_id="acme"))
    assert ei.value.type == "GraphStateChanged" and ei.value.non_retryable
    assert repo == []


@pytest.mark.parametrize("fn", _PROVISION)
async def test_provision_refuses_graph_no_longer_provisioning(fn, repo, monkeypatch):
    # A stray provision workflow must not re-create storage a delete dropped.
    ROW_STATUS["acme"] = "deleting"
    _forbid_storage(monkeypatch)
    with pytest.raises(ApplicationError) as ei:
        await fn(GraphLifecycleIn(graph_id="acme"))
    assert ei.value.type == "GraphStateChanged" and ei.value.non_retryable


async def test_delete_graph_row_is_conditional_on_deleting(repo, monkeypatch):
    ROW_STATUS["acme"] = "deleting"
    monkeypatch.setattr(A, "get_graph_registry", lambda: SimpleNamespace(invalidate=lambda g: None))
    await A.delete_graph_row(GraphLifecycleIn(graph_id="acme"))
    assert repo == [("delete", "acme", "deleting")]
