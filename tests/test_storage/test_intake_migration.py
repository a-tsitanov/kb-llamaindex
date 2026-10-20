"""Одноразовое расщепление `documents` → `doc_processing` (`intake_split_v1`).

Проверяется то, на чём шаг ломается молча: посхемность маркера (один
глобальный PRIMARY KEY `public.schema_migration.name` против N схем графов),
порядок «маркер последним» и ужесточённый предикат отбора, без которого
повторный прогон воскресил бы отклонённые приёмом документы.

Фейк курсора — по образцу ``tests/test_scripts/test_setup_db_authz.py``: он
запоминает записанные маркеры, поэтому одну и ту же «базу» можно мигрировать
дважды.
"""

from __future__ import annotations

from src.storage import pg_schema
from src.tenancy.context import default_graph_context, new_graph_context


class _Cur:
    """execute пишет ``(sql, params)``; гард маркера отвечает по сценарию."""

    def __init__(self, markers: set[str] | None = None):
        self.sql: list[tuple[str, object]] = []
        self.markers: set[str] = set(markers or ())
        self._rows: list[tuple] = []

    def execute(self, q, params=None):
        stmt = q.as_string(None) if hasattr(q, "as_string") else str(q)
        self.sql.append((stmt, params))
        self._rows = []
        if "public.schema_migration" not in stmt:
            return
        if stmt.lstrip().startswith("SELECT"):
            self._rows = [(1,)] if params and params[0] in self.markers else []
        elif "INSERT" in stmt and params:
            self.markers.add(params[0])

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


def _norm(stmt: str) -> str:
    """Текст оператора в одну строку — утверждения не зависят от переносов."""
    return " ".join(stmt.split())


def _tail(cur: _Cur, *, schema_created: bool = True) -> list[str]:
    """Операторы после блока GRAPH_DDL (включая финальный RESET)."""
    prefix = (1 if schema_created else 0) + 1 + len(pg_schema.GRAPH_DDL)
    return [_norm(s) for s, _ in cur.sql[prefix:]]


def _run(graph, markers: set[str] | None = None) -> _Cur:
    cur = _Cur(markers)
    pg_schema.migrate_graph_schema(cur, graph)
    return cur


def test_runs_when_marker_absent():
    cur = _run(new_graph_context("acme"))
    body = _tail(cur)
    assert body[-1] == "RESET search_path"
    body = body[:-1]
    assert len(body) == 4, body
    assert "SELECT 1 FROM public.schema_migration" in body[0]
    assert body[1].startswith("INSERT INTO doc_processing")
    assert body[2].startswith("UPDATE documents")
    assert body[3].startswith("INSERT INTO public.schema_migration")
    marker_params = [p for s, p in cur.sql if "public.schema_migration" in s]
    assert marker_params == [("intake_split_v1:g_acme",)] * 2


def test_skips_when_marker_present():
    cur = _run(new_graph_context("acme"), {"intake_split_v1:g_acme"})
    body = _tail(cur)
    assert body[-1] == "RESET search_path"
    body = body[:-1]
    assert len(body) == 1 and "SELECT 1 FROM public.schema_migration" in body[0]
    # «UPDATE documents» есть и в самом GRAPH_DDL (бэкфилл source_channel),
    # поэтому смотрим строго на хвост, а не на весь прогон.
    assert not any(s.startswith(("INSERT INTO doc_processing", "UPDATE documents")) for s in body)


def test_marker_is_per_schema():
    """Маркер соседнего графа не глушит миграцию: ключ в имени схемы."""
    cur = _run(default_graph_context(), {"intake_split_v1:g_acme"})
    body = _tail(cur, schema_created=False)
    assert body[1].startswith("INSERT INTO doc_processing")
    assert cur.markers == {"intake_split_v1:g_acme", "intake_split_v1:public"}

    cur = _run(new_graph_context("acme"), {"intake_split_v1:public"})
    assert _tail(cur)[1].startswith("INSERT INTO doc_processing")
    assert cur.markers == {"intake_split_v1:public", "intake_split_v1:g_acme"}


def test_marker_written_last():
    """Соединение в autocommit: маркер, записанный первым, навсегда
    заблокировал бы недоделанную миграцию."""
    cur = _run(new_graph_context("acme"))
    stmts = [_norm(s) for s, _ in cur.sql]
    insert = next(i for i, s in enumerate(stmts) if s.startswith("INSERT INTO doc_processing"))
    update = next(
        i
        for i, s in enumerate(stmts)
        if s.startswith("UPDATE documents") and "intake_status = 'rejected'" in s
    )
    marker = next(
        i for i, s in enumerate(stmts) if s.startswith("INSERT INTO public.schema_migration")
    )
    assert marker > insert and marker > update


def test_backfill_predicate_cannot_resurrect_a_rejected_row():
    """Три условия отбора — единственная защита при повторном прогоне после
    того, как S8/S9 перестали писать в documents.status."""
    cur = _run(new_graph_context("acme"))
    insert = next(s for s in _tail(cur) if s.startswith("INSERT INTO doc_processing"))
    assert "status <> 'skipped'" in insert
    assert "intake_status <> 'rejected'" in insert
    assert "NOT EXISTS (SELECT 1 FROM doc_processing p WHERE p.doc_id = d.id)" in insert


def _reject_update(cur: _Cur) -> str:
    return next(
        s
        for s in _tail(cur)
        if s.startswith("UPDATE documents") and "intake_status = 'rejected'" in s
    )


def test_update_marks_pre_split_skipped_as_rejected():
    update = _reject_update(_run(new_graph_context("acme")))
    assert "WHERE status = 'skipped'" in update
    assert "AND intake_status <> 'rejected'" in update


def test_update_keeps_the_pre_split_rejection_reason():
    """Причина отказа переносится из `documents.error`, литерал — фолбэк.

    До расщепления причину писал туда `mark_skipped`, а строки обработки у
    отклонённого документа нет — значит выражение `eff_error` вырождается в
    `intake_reason`, и голый литерал навсегда подменил бы причину заглушкой
    и в `error`, и в `intake_reason` ответа API.  Инвариант S11:
    «для отклонённого документа status='skipped' и error=<причина отказа>
    ровно как до расщепления».
    """
    update = _reject_update(_run(new_graph_context("acme")))
    assert "intake_reason = COALESCE(NULLIF(error, ''), 'classifier (pre-split)')" in update


def test_second_run_on_same_database_is_a_no_op():
    """Маркер, записанный первым прогоном, глушит второй."""
    graph = new_graph_context("acme")
    cur = _run(graph)
    before = len(cur.sql)
    pg_schema.migrate_graph_schema(cur, graph)
    second = [_norm(s) for s, _ in cur.sql[before:]]
    assert not any(s.startswith("INSERT INTO doc_processing") for s in second)
    assert not any(s.startswith("INSERT INTO public.schema_migration") for s in second)
