"""The entity mirror writer fills the name-resolution columns, and survives an old schema."""
from contextlib import contextmanager

import psycopg

from src.graph import entity_table
from src.tenancy.context import default_graph_context, new_graph_context


class _Cur:
    def __init__(self, log, fail_new):
        self.log, self.fail_new = log, fail_new

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def executemany(self, sql, values):
        if self.fail_new and "name_norm" in sql:
            raise psycopg.errors.UndefinedColumn("column name_norm does not exist")
        self.log.append((sql, list(values)))


class _Conn:
    def __init__(self, log, fail_new):
        self.log, self.fail_new, self.rolled_back = log, fail_new, False
        self.executed = []

    def execute(self, stmt, params=None):
        # graph_sync_connection's search_path SET
        self.executed.append(stmt)

    def commit(self):
        pass

    def cursor(self):
        return _Cur(self.log, self.fail_new)

    def rollback(self):
        self.rolled_back = True


def _pool(conn):
    class P:
        @contextmanager
        def connection(self, timeout=None):
            yield conn
    return P()


ROW = {"vid": "v1", "name": "Алексей Лихачёв", "label": "Person", "description": "d",
       "mention_count": 3}


def test_mirror_writes_norm_and_translit(monkeypatch):
    log = []
    import src.storage.pg_sync_pool as sp
    monkeypatch.setattr(sp, "get_pg_sync_pool", lambda: _pool(_Conn(log, False)))
    entity_table.mirror_entities(default_graph_context(), [ROW])
    (sql, values), = log
    assert "name_norm" in sql
    assert values == [("v1", "Алексей Лихачёв", "Person", "d", 3, "алексей лихачев",
                       "aleksei lihacev")]


def test_mirror_falls_back_to_the_old_columns_before_the_migration(monkeypatch):
    log = []
    conn = _Conn(log, True)
    import src.storage.pg_sync_pool as sp
    monkeypatch.setattr(sp, "get_pg_sync_pool", lambda: _pool(conn))
    entity_table.mirror_entities(default_graph_context(), [ROW])
    (sql, values), = log
    assert conn.rolled_back and "name_norm" not in sql
    assert values == [("v1", "Алексей Лихачёв", "Person", "d", 3)]


def test_mirror_runs_in_the_graph_schema(monkeypatch):
    log = []
    conn = _Conn(log, False)
    import src.storage.pg_sync_pool as sp
    monkeypatch.setattr(sp, "get_pg_sync_pool", lambda: _pool(conn))
    graph = new_graph_context("acme")
    entity_table.mirror_entities(graph, [ROW])
    (stmt,) = conn.executed
    assert graph.pg_schema in stmt.as_string(None)
    assert len(log) == 1
