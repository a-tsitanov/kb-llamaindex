from scripts import setup_db
from src.tenancy.context import default_graph_context, new_graph_context


class _Cur:
    """Маркера `intake_split_v1` нет, поэтому одноразовое расщепление
    отрабатывает — утверждения ниже смотрят только на блок GRAPH_DDL и на
    последний оператор, и от добавочных операторов не зависят."""

    def __init__(self):
        self.sql = []

    def execute(self, q, params=None):
        self.sql.append(q.as_string(None) if hasattr(q, "as_string") else str(q))

    def fetchall(self):
        return []

    def fetchone(self):
        return None


def _ddl_without_comments() -> str:
    """GRAPH_DDL без SQL-комментариев.

    Проверка «глобальных таблиц здесь нет» ищет подстроку, а комментарии
    ОБЪЯСНЯЮТ соседние таблицы и законно называют общие — например, почему
    право на доставку проверяется по реестру ключей в `public`. Упоминание
    в комментарии не создаёт таблицу, поэтому сравнивать надо с SQL, а не
    с текстом файла.
    """
    return "\n".join(
        line.split("--", 1)[0]
        for stmt in setup_db.GRAPH_DDL
        for line in stmt.splitlines()
    )


def test_graph_ddl_contains_every_graph_table_and_no_global_one():
    joined = _ddl_without_comments()
    for t in (
        "documents",
        "doc_processing",
        "ingest_metrics",
        "fact_supersede",
        "stat_indicator",
        "stat_observation",
        "er_verdict",
        "entity",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {t}" in joined, t
    for t in ("graphs", "api_keys"):
        assert t not in joined


def test_migrate_new_graph_creates_schema_and_scopes_ddl():
    cur = _Cur()
    setup_db.migrate_graph_schema(cur, new_graph_context("acme"))
    assert cur.sql[0] == 'CREATE SCHEMA IF NOT EXISTS "g_acme"'
    assert cur.sql[1] == 'SET search_path TO "g_acme", extensions'
    assert cur.sql[2 : 2 + len(setup_db.GRAPH_DDL)] == setup_db.GRAPH_DDL
    assert cur.sql[-1] == "RESET search_path"


def test_migrate_default_graph_does_not_create_public():
    cur = _Cur()
    setup_db.migrate_graph_schema(cur, default_graph_context())
    assert not any(s.startswith("CREATE SCHEMA") for s in cur.sql)
    assert cur.sql[0] == 'SET search_path TO "public", extensions'
