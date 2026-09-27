from scripts import setup_db
from src.tenancy.context import default_graph_context, new_graph_context


class _Cur:
    def __init__(self):
        self.sql = []

    def execute(self, q, params=None):
        self.sql.append(q.as_string(None) if hasattr(q, "as_string") else str(q))


def test_graph_ddl_contains_every_graph_table_and_no_global_one():
    joined = "\n".join(setup_db.GRAPH_DDL)
    for t in (
        "documents", "ingest_metrics", "fact_supersede", "stat_indicator",
        "stat_observation", "er_verdict", "entity",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {t}" in joined, t
    for t in ("bot_user", "bot_request", "graphs", "api_keys"):
        assert t not in joined


def test_migrate_new_graph_creates_schema_and_scopes_ddl():
    cur = _Cur()
    setup_db.migrate_graph_schema(cur, new_graph_context("acme"))
    assert cur.sql[0] == 'CREATE SCHEMA IF NOT EXISTS "g_acme"'
    assert cur.sql[1] == 'SET search_path TO "g_acme", public'
    assert cur.sql[2 : 2 + len(setup_db.GRAPH_DDL)] == setup_db.GRAPH_DDL
    assert cur.sql[-1] == "RESET search_path"


def test_migrate_default_graph_does_not_create_public():
    cur = _Cur()
    setup_db.migrate_graph_schema(cur, default_graph_context())
    assert not any(s.startswith("CREATE SCHEMA") for s in cur.sql)
    assert cur.sql[0] == 'SET search_path TO "public", public'
