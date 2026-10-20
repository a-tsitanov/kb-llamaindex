"""Unit tests for the pure helpers in scripts/wipe_db.py.

The I/O wipe functions (Postgres/Milvus/Neo4j/MediaWiki/Temporal) need live
infra and are exercised by running the script; here we only cover the pure
page-selection helper, which decides what MediaWiki content gets deleted.
"""
from __future__ import annotations

from scripts.wipe_db import _WIKI_KEEP, _pages_to_delete


def test_pages_to_delete_excludes_keep_list():
    allpages = [{"title": "Main Page"}, {"title": "ООО Альфа"},
                {"title": "Сергей Волков"}]
    assert _pages_to_delete(allpages) == ["ООО Альфа", "Сергей Волков"]


def test_pages_to_delete_keeps_main_page_by_default():
    assert "Main Page" in _WIKI_KEEP
    assert _pages_to_delete([{"title": "Main Page"}]) == []


def test_pages_to_delete_custom_keep():
    allpages = [{"title": "A"}, {"title": "B"}, {"title": "C"}]
    assert _pages_to_delete(allpages, keep={"B"}) == ["A", "C"]


def test_pages_to_delete_empty():
    assert _pages_to_delete([]) == []


def test_wipe_clears_watch_journals_and_events_but_keeps_subscriptions():
    from scripts.wipe_db import _PG_TABLES

    for t in ("entity_mention", "edge_new", "watch_event", "watch_seen",
              "monitor_cursor", "risk_snapshot"):
        assert t in _PG_TABLES
    assert "watch" not in _PG_TABLES


def test_truncates_doc_processing_and_cascades(monkeypatch):
    """Расщепление записи завело у ``documents`` ссылающуюся таблицу.

    ``TRUNCATE TABLE documents`` после этого — ошибка FeatureNotSupported
    (Postgres отказывает по самому НАЛИЧИЮ внешнего ключа, а не по строкам),
    а цикл wipe'а ловит только UndefinedTable, то есть падал бы весь wipe.
    Проверяем оба условия починки: дочерняя таблица чистится раньше
    родительской и у каждого оператора есть CASCADE.
    """
    import psycopg

    from scripts import wipe_db

    seen: list[str] = []

    class _Cur:
        def execute(self, sql, *args):
            seen.append(sql)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class _Conn:
        def cursor(self):
            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(psycopg, "connect", lambda *a, **kw: _Conn())
    wipe_db.wipe_postgres()

    assert seen, "ни одного TRUNCATE не выполнено"
    assert all(s.endswith(" CASCADE") for s in seen), seen
    tables = [
        s.removeprefix("TRUNCATE TABLE ").removesuffix(" CASCADE") for s in seen
    ]
    assert tables == list(wipe_db._PG_TABLES)
    assert "doc_processing" in tables
    assert tables.index("doc_processing") < tables.index("documents")
