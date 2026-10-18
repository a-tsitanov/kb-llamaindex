from contextlib import asynccontextmanager

import pytest

from src.tenancy import graph_repo
from src.tenancy.context import new_graph_context
from src.tenancy.registry import GraphNotFound


class _Cur:
    def __init__(self, results):
        self.results, self.sql = list(results), []

    async def execute(self, q, params=None):
        self.sql.append((str(q), params))

    async def fetchone(self):
        return self.results.pop(0) if self.results else None

    async def fetchall(self):
        return self.results.pop(0) if self.results else []


class _Conn:
    def __init__(self, cur):
        self.cur, self.commits = cur, 0

    def cursor(self, row_factory=None):
        cur = self.cur

        @asynccontextmanager
        async def cm():
            yield cur

        return cm()

    async def commit(self):
        self.commits += 1


def _factory(results):
    cur = _Cur(results)
    conn = _Conn(cur)

    @asynccontextmanager
    async def f():
        yield conn

    return f, cur, conn


def _row(gid, status="ready", generation=5):
    c = new_graph_context(gid)
    return {
        "id": gid,
        "owner": "o",
        "status": status,
        "status_error": "",
        "nebula_space": c.nebula_space,
        "nebula_partition_num": 10,
        "chunks_collection": c.chunks_collection,
        "er_vec_collection": c.er_vec_collection,
        "report_vec_collection": c.report_vec_collection,
        "pg_schema": c.pg_schema,
        "max_inflight": None,
        "generation": generation,
        "created_at": None,
        "updated_at": None,
    }


async def test_create_or_resume_inserts_new_row():
    f, cur, conn = _factory([{"id": "acme"}])
    out = await graph_repo.create_or_resume("acme", "team", 12, conn_factory=f)
    assert out == graph_repo.CreateOutcome("created", "provisioning")
    stmt, params = cur.sql[0]
    assert "INSERT INTO public.graphs" in stmt and "ON CONFLICT (id) DO NOTHING" in stmt
    assert "clock_timestamp()" in stmt
    assert params[:4] == ("acme", "team", "g_acme", 12)
    assert conn.commits == 1


async def test_create_or_resume_resumes_failed():
    f, cur, _ = _factory([None, {"id": "acme"}])
    out = await graph_repo.create_or_resume("acme", "team", 10, conn_factory=f)
    assert out == graph_repo.CreateOutcome("resumed", "provisioning")
    assert "status = 'failed'" in cur.sql[1][0]


async def test_resume_bumps_generation():
    # A failed delete may have dropped storage cached under the old
    # `id#generation`; the resumed graph must get a fresh cache key.
    f, cur, _ = _factory([None, {"id": "acme"}])
    await graph_repo.create_or_resume("acme", "team", 10, conn_factory=f)
    stmt = cur.sql[1][0]
    assert stmt.startswith("UPDATE") and "generation = " in stmt and "clock_timestamp()" in stmt


@pytest.mark.parametrize("status", ["ready", "provisioning", "deleting"])
async def test_create_or_resume_conflicts(status):
    f, _, _ = _factory([None, None, {"status": status}])
    out = await graph_repo.create_or_resume("acme", "team", 10, conn_factory=f)
    assert out == graph_repo.CreateOutcome("conflict", status)


async def test_create_rejects_default_and_bad_slug():
    from src.tenancy.context import InvalidGraphId

    for gid in ("default", "Bad"):
        with pytest.raises(InvalidGraphId):
            await graph_repo.create_or_resume(gid, "o", 10, conn_factory=_factory([])[0])


async def test_load_context_any_status_ignores_status():
    f, _, _ = _factory([_row("acme", status="provisioning", generation=9)])
    g = await graph_repo.load_context_any_status("acme", conn_factory=f)
    assert g.id == "acme" and g.generation == 9


async def test_load_context_any_status_missing():
    f, _, _ = _factory([None])
    with pytest.raises(GraphNotFound):
        await graph_repo.load_context_any_status("acme", conn_factory=f)


async def test_load_context_any_status_with_expect_rejects_other_status():
    f, _, _ = _factory([_row("acme", status="ready")])
    with pytest.raises(graph_repo.GraphStateChanged) as ei:
        await graph_repo.load_context_any_status("acme", expect="deleting", conn_factory=f)
    assert ei.value.status == "ready" and ei.value.expected == "deleting"


async def test_load_context_any_status_with_expect_matching():
    f, _, _ = _factory([_row("acme", status="deleting")])
    g = await graph_repo.load_context_any_status("acme", expect="deleting", conn_factory=f)
    assert g.id == "acme"


async def test_delete_row_with_expect_is_conditional():
    f, cur, _ = _factory([None])
    assert await graph_repo.delete_row("acme", expect="deleting", conn_factory=f) is False
    stmt, params = cur.sql[0]
    assert "AND status = %s" in stmt and params == ("acme", "deleting")


async def test_mark_deleting_returns_previous_status():
    f, cur, _ = _factory([{"prev": "ready"}])
    assert await graph_repo.mark_deleting("acme", conn_factory=f) == "ready"
    assert "status = 'deleting'" in cur.sql[0][0]


async def test_mark_deleting_skips_provisioning_atomically():
    # The provisioning guard is part of the locked write itself, so a
    # concurrent resume (failed → provisioning) cannot be overwritten.
    f, cur, _ = _factory([{"prev": "provisioning"}])
    assert await graph_repo.mark_deleting("acme", conn_factory=f) == "provisioning"
    assert len(cur.sql) == 1
    stmt = cur.sql[0][0]
    assert "FOR UPDATE" in stmt and "<> 'provisioning'" in stmt


async def test_set_status_unconditional_by_default():
    f, cur, _ = _factory([{"id": "acme"}])
    assert await graph_repo.set_status("acme", "failed", "boom", conn_factory=f) is True
    stmt, params = cur.sql[0]
    assert "AND status" not in stmt and params == ("failed", "boom", "acme")


async def test_set_status_with_expect_is_conditional():
    f, cur, _ = _factory([None])
    changed = await graph_repo.set_status("acme", "ready", expect="provisioning", conn_factory=f)
    assert changed is False
    stmt, params = cur.sql[0]
    assert "AND status = %s" in stmt and params == ("ready", "", "acme", "provisioning")


async def test_list_ready_contexts():
    f, cur, _ = _factory([[_row("acme"), _row("beta")]])
    gs = await graph_repo.list_ready_contexts(conn_factory=f)
    assert [g.id for g in gs] == ["acme", "beta"]
    assert "status = 'ready'" in cur.sql[0][0]


async def test_mark_deleting_refuses_default():
    with pytest.raises(ValueError):
        await graph_repo.mark_deleting("default", conn_factory=_factory([])[0])
