import pytest

from src.storage import pg_schema
from src.tenancy.context import default_graph_context, new_graph_context


class _Cur:
    """``marker=True`` — строка ``intake_split_v1:<схема>`` уже лежит в
    ``public.schema_migration``, и одноразовое расщепление пропускается;
    ``marker=False`` — отрабатывает целиком.  Без разделения ответов гард
    читал бы кортежи имён таблиц как «уже применено» и тест оставался бы
    зелёным при неработающем коде (подробности — в
    ``tests/test_storage/test_intake_migration.py``)."""

    def __init__(self, existing=(), *, marker=True):
        self.sql, self._existing, self._marker = [], list(existing), marker
        self._last = ""

    def execute(self, q, params=None):
        self._last = q.as_string(None) if hasattr(q, "as_string") else str(q)
        self.sql.append((self._last, params))

    def fetchall(self):
        if "public.schema_migration" in self._last:
            return [(1,)] if self._marker else []
        return [(t,) for t in self._existing]

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None


def test_graph_tables_cover_core_tables():
    tables = pg_schema.graph_tables()
    for t in (
        "documents",
        "doc_processing",
        "ingest_metrics",
        "entity",
        "er_verdict",
        "watch",
        "entity_alias",
    ):
        assert t in tables
    assert "graphs" not in tables and "api_keys" not in tables
    assert len(tables) == len(set(tables))


def test_missing_graph_tables_reports_absent():
    all_tables = pg_schema.graph_tables()
    cur = _Cur(existing=[t for t in all_tables if t != "entity"])
    assert pg_schema.missing_graph_tables(cur, new_graph_context("acme")) == ["entity"]
    stmt, params = cur.sql[-1]
    assert "information_schema.tables" in stmt and params == ("g_acme",)


def test_missing_graph_tables_reports_doc_processing():
    """Гейт готовности графа: без таблицы обработки граф не встаёт в ready."""
    all_tables = pg_schema.graph_tables()
    cur = _Cur(existing=[t for t in all_tables if t != "doc_processing"])
    assert pg_schema.missing_graph_tables(cur, new_graph_context("acme")) == ["doc_processing"]


def test_documents_ddl_declares_intake_columns():
    ddl = pg_schema._DOCUMENTS_DDL
    for col in (
        "content_sha256",
        "intake_status",
        "intake_reason",
        "duplicate_of",
        "source_kind",
    ):
        assert col in ddl, col
    assert "documents_intake_status_check" in ddl


def test_sha_index_predicate_does_not_mention_duplicate_of():
    """Членство в ``documents_sha_idx`` не зависит от ``duplicate_of``.

    Иначе ``ON DELETE SET NULL`` у самого ``duplicate_of`` становится
    несовместим с индексом: удаляя канонический документ с ДВУМЯ версиями,
    Postgres обнуляет ссылки одним UPDATE'ом, обе версии одновременно входят
    в предикат с одинаковым хешем и DELETE падает нарушением уникальности.
    Версии из индекса выводит отсутствие хеша (``accept_document`` пишет
    им NULL), а не предикат — тогда осиротение безопасно при любом их числе.
    """
    ddl = pg_schema._DOCUMENTS_DDL
    # Берём ИМЕННО определение индекса: в комментариях выше `duplicate_of`
    # упоминается законно, и поиск по всему тексту был бы вечнозелёным.
    head = "CREATE UNIQUE INDEX documents_sha_idx"
    assert ddl.count(head) == 1
    sha_idx = ddl.split(head, 1)[1].split(";", 1)[0]
    assert "content_sha256 IS NOT NULL" in sha_idx
    assert "duplicate_of" not in sha_idx
    # Прежний индекс (с предикатом по duplicate_of) обязан быть снят: с
    # `IF NOT EXISTS` он остался бы на уже созданных базах как есть.
    assert "DROP INDEX IF EXISTS documents_sha_idx;" in ddl
    # И строки, записанные до инварианта, приводятся к нему — иначе
    # CREATE UNIQUE INDEX упал бы на дубле «канон + его версия».
    assert "UPDATE documents SET content_sha256 = NULL" in ddl


def test_doc_processing_status_domain_excludes_skipped():
    """Отказ классификатора — это intake_status='rejected', не статус обработки."""
    assert "skipped" not in pg_schema._DOC_PROCESSING_DDL


def test_missing_graph_tables_empty_when_complete():
    cur = _Cur(existing=pg_schema.graph_tables())
    assert pg_schema.missing_graph_tables(cur, new_graph_context("acme")) == []


# extra = операторы одноразового расщепления: только гард маркера, когда он
# уже стоит, и гард + два оператора данных + запись маркера, когда нет.
@pytest.mark.parametrize("marker, extra", [(True, 1), (False, 4)])
def test_migrate_creates_schema_then_runs_graph_ddl(marker, extra):
    cur = _Cur(marker=marker)
    pg_schema.migrate_graph_schema(cur, new_graph_context("acme"))
    stmts = [s for s, _ in cur.sql]
    assert stmts[0] == 'CREATE SCHEMA IF NOT EXISTS "g_acme"'
    assert stmts[1] == 'SET search_path TO "g_acme", extensions'
    assert stmts[-1] == "RESET search_path"
    assert len(stmts) == len(pg_schema.GRAPH_DDL) + 3 + extra


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
    assert setup_db._DOC_PROCESSING_DDL is pg_schema._DOC_PROCESSING_DDL
    assert setup_db.migrate_graph_schema is pg_schema.migrate_graph_schema
