from contextlib import asynccontextmanager

from src.storage import entity_lexicon as lx
from src.storage import pg_scope
from src.tenancy.context import new_graph_context


def test_queries_filter_dead_rows_and_escape_prefix():
    sql, params = lx.q_prefix("50%_off", 5)
    assert "name_norm LIKE %s" in sql and "alive IS NOT FALSE" in sql
    assert params == ["50\\%\\_off%", 5]
    sql, params = lx.q_word("лихачев", 20)
    assert "%s <%% name_norm" in sql and params == ["лихачев", "лихачев", 20]
    sql, params = lx.q_trigram("росатом", 20)
    assert "name_norm %% %s" in sql and params == ["росатом", "росатом", 20]


def test_alias_and_translit_read_the_alias_table():
    sql, params = lx.q_alias("гк росатом", 5)
    assert "FROM entity_alias WHERE alias_norm = %s" in sql and params == ["гк росатом", 5]
    sql, params = lx.q_translit("rosatom", 5)
    assert "name_translit = %s" in sql and "alias_translit = %s" in sql
    assert params == ["rosatom", 5, "rosatom", 5]
    assert lx.q_norm("росатом", 3)[1] == ["росатом", 3]


async def test_lexicon_reads_the_graph_schema(monkeypatch):
    log: list = []

    class _Cur:
        async def execute(self, sql, params=None):
            log.append(("query", sql, params))

        async def fetchall(self):
            return [{"name": "Росатом"}]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class _Conn:
        async def execute(self, q, params=None):
            log.append(("set", q.as_string(None)))

        async def commit(self):
            log.append(("commit",))

        def cursor(self, *a, **kw):
            return _Cur()

    class _Pool:
        @asynccontextmanager
        async def connection(self, timeout=None):
            yield _Conn()

    async def _get_pool():
        return _Pool()

    monkeypatch.setattr(pg_scope, "get_pg_pool", _get_pool)
    lex = lx.EntityLexicon(graph=new_graph_context("acme"))
    assert await lex.by_norm("росатом", 3) == [{"name": "Росатом"}]
    assert log[0] == ("set", 'SET search_path TO "g_acme", public')
    assert log[1] == ("commit",)
    assert log[2][0] == "query" and "FROM entity" in log[2][1]
