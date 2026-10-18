import pytest

from src.storage import pg_schema
from src.tenancy.context import default_graph_context, new_graph_context


class _Cur:
    def __init__(self, existing=()):
        self.sql, self._existing = [], list(existing)

    def execute(self, q, params=None):
        self.sql.append((q.as_string(None) if hasattr(q, "as_string") else str(q), params))

    def fetchall(self):
        return [(t,) for t in self._existing]


def test_graph_tables_cover_core_tables():
    tables = pg_schema.graph_tables()
    for t in ("documents", "ingest_metrics", "entity", "er_verdict", "watch", "entity_alias"):
        assert t in tables
    assert "graphs" not in tables and "api_keys" not in tables
    assert len(tables) == len(set(tables))


def test_missing_graph_tables_reports_absent():
    all_tables = pg_schema.graph_tables()
    cur = _Cur(existing=[t for t in all_tables if t != "entity"])
    assert pg_schema.missing_graph_tables(cur, new_graph_context("acme")) == ["entity"]
    stmt, params = cur.sql[-1]
    assert "information_schema.tables" in stmt and params == ("g_acme",)


def test_missing_graph_tables_empty_when_complete():
    cur = _Cur(existing=pg_schema.graph_tables())
    assert pg_schema.missing_graph_tables(cur, new_graph_context("acme")) == []


def test_migrate_creates_schema_then_runs_graph_ddl():
    cur = _Cur()
    pg_schema.migrate_graph_schema(cur, new_graph_context("acme"))
    stmts = [s for s, _ in cur.sql]
    assert stmts[0] == 'CREATE SCHEMA IF NOT EXISTS "g_acme"'
    assert stmts[1] == 'SET search_path TO "g_acme", extensions'
    assert stmts[-1] == "RESET search_path"
    assert len(stmts) == len(pg_schema.GRAPH_DDL) + 3


def test_drop_graph_schema_cascades():
    cur = _Cur()
    pg_schema.drop_graph_schema(cur, new_graph_context("acme"))
    assert cur.sql == [('DROP SCHEMA IF EXISTS "g_acme" CASCADE', None)]


def test_drop_refuses_default_schema():
    with pytest.raises(ValueError):
        pg_schema.drop_graph_schema(_Cur(), default_graph_context())


def test_setup_db_reexports_moved_names():
    from scripts import setup_db

    assert setup_db.GRAPH_DDL is pg_schema.GRAPH_DDL
    assert setup_db._DOCUMENTS_DDL is pg_schema._DOCUMENTS_DDL
    assert setup_db.migrate_graph_schema is pg_schema.migrate_graph_schema
