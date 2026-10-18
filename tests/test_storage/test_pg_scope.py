from contextlib import asynccontextmanager

from src.storage import pg_scope
from src.tenancy.context import default_graph_context, new_graph_context


class _AConn:
    def __init__(self):
        self.log = []

    async def execute(self, q, params=None):
        self.log.append(("execute", q.as_string(None) if hasattr(q, "as_string") else str(q)))

    async def commit(self):
        self.log.append(("commit",))

    async def rollback(self):
        self.log.append(("rollback",))


class _APool:
    def __init__(self):
        self.conn = _AConn()

    @asynccontextmanager
    async def connection(self, timeout=None):
        yield self.conn


def test_search_path_sql_quotes_identifier():
    s = pg_scope.search_path_sql(new_graph_context("acme")).as_string(None)
    assert s == 'SET search_path TO "g_acme", extensions'
    default_sql = pg_scope.search_path_sql(default_graph_context()).as_string(None)
    assert default_sql == 'SET search_path TO "public", extensions'


def test_non_default_search_path_has_no_public():
    # R-P5: a missing per-graph table must error, never resolve to the
    # default graph's table in `public`.
    s = pg_scope.search_path_sql(new_graph_context("acme")).as_string(None)
    assert "public" not in s


async def test_graph_connection_commits_set_before_yield(monkeypatch):
    pool = _APool()

    async def fake_get_pool():
        return pool
    monkeypatch.setattr(pg_scope, "get_pg_pool", fake_get_pool)
    async with pg_scope.graph_connection(new_graph_context("acme")) as conn:
        assert conn.log == [("execute", 'SET search_path TO "g_acme", extensions'), ("commit",)]
        await conn.rollback()  # a later rollback cannot revert a committed SET


async def test_reset_callback_resets_search_path_and_commits():
    conn = _AConn()
    await pg_scope.reset_search_path(conn)
    assert conn.log == [("execute", "RESET search_path"), ("commit",)]


def test_sync_reset_callback():
    log = []

    class C:
        def execute(self, q, params=None):
            log.append(("execute", str(q)))

        def commit(self):
            log.append(("commit",))
    pg_scope.reset_search_path_sync(C())
    assert log == [("execute", "RESET search_path"), ("commit",)]


def test_pools_install_reset_callbacks(monkeypatch):
    import src.storage.pg_pool as ap
    import src.storage.pg_sync_pool as sp
    seen = {}

    class FakeAsyncPool:
        def __init__(self, **kw):
            seen["async"] = kw.get("reset")

        async def open(self):
            pass

    class FakeSyncPool:
        def __init__(self, **kw):
            seen["sync"] = kw.get("reset")

        def open(self, *a, **k):
            pass
    monkeypatch.setattr(ap, "AsyncConnectionPool", FakeAsyncPool)
    monkeypatch.setattr(sp, "ConnectionPool", FakeSyncPool)
    ap.reset_for_tests()
    monkeypatch.setattr(sp, "_pool", None)
    import asyncio
    asyncio.run(ap.get_pg_pool())
    sp.get_pg_sync_pool()
    assert seen["async"] is pg_scope.reset_search_path
    assert seen["sync"] is pg_scope.reset_search_path_sync
    ap.reset_for_tests()
    monkeypatch.setattr(sp, "_pool", None)
