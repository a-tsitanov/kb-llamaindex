"""Реестр приёма ``IntakeRepository`` — проверка эмитируемого SQL.

Соединения нет: ``graph_connection`` подменяется фейком, который копит
пары (текст запроса, параметры).  Шаг S5 — чистый перенос SQL из
``AsyncPostgres``, поэтому тесты сверяют именно текст и привязку
значений, а не поведение Postgres.

Шаг S8 расщепил запись: приём пишет в ``documents``, статус обработки —
в ``doc_processing``, а читатели сводят их обратно выражением
эффективного статуса.  Тесты ниже сторожат ровно эту границу.
"""

from __future__ import annotations

import datetime as dt
import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest

from src.intake import repository as repo_mod
from src.intake.repository import DOC_STATUSES, DocumentRow, IntakeRepository
from src.tenancy.context import default_graph_context

# ── фейковые курсор и соединение ─────────────────────────────────────


class _Cur:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self.sql: list[tuple[str, Any]] = []
        self._rows = rows if rows is not None else []

    async def execute(self, q, params=None) -> None:
        self.sql.append((str(q), params))

    async def fetchall(self):
        return self._rows

    async def fetchone(self):
        return self._rows[0] if self._rows else None


class _Conn:
    def __init__(self, cur: _Cur) -> None:
        self.cur, self.commits = cur, 0

    def cursor(self, row_factory=None):
        @asynccontextmanager
        async def cm():
            yield self.cur

        return cm()

    async def commit(self) -> None:
        self.commits += 1


def _patch_conn(monkeypatch, rows: list[Any] | None = None) -> _Conn:
    conn = _Conn(_Cur(rows))

    @asynccontextmanager
    async def graph_connection(graph, timeout=None):
        yield conn

    monkeypatch.setattr(repo_mod, "graph_connection", graph_connection)
    return conn


@pytest.fixture
def pg() -> IntakeRepository:
    return IntakeRepository(graph=default_graph_context())


def _doc_row(**over) -> dict[str, Any]:
    """Строка выборки ``get``: ``d.*`` плюс эффективные ``eff_*``.

    Колонки ``status``/``error``/``summary`` в выборке остаются (``d.*``), но
    читатель берёт ``eff_*`` — их считает SQL, а не ``from_dict``.
    """
    now = dt.datetime(2026, 10, 19, 12, 0, 0)
    return {
        "id": uuid.UUID("11111111-1111-1111-1111-111111111111"),
        "path": "s3://kb-uploads/d1/a.txt",
        "department": "", "doc_type": "txt",
        "status": "pending", "error": "", "summary": "",
        "intake_status": "accepted", "intake_reason": "",
        "eff_status": "completed", "eff_error": "", "eff_summary": "s",
        "created_at": now, "updated_at": now,
        **over,
    }


# ── accept_document ──────────────────────────────────────────────────


async def test_accept_writes_both_tables_in_one_transaction(monkeypatch, pg) -> None:
    """Приём — один акт: строка документа и строка его обработки
    создаются на ОДНОМ соединении и фиксируются ОДНИМ commit'ом."""
    conn = _patch_conn(monkeypatch)
    doc_id = uuid.uuid4()
    await pg.accept_document(doc_id, "s3://b/k.txt", doc_type="txt")

    assert len(conn.cur.sql) == 2 and conn.commits == 1
    doc_sql, doc_params = conn.cur.sql[0]
    proc_sql, proc_params = conn.cur.sql[1]
    assert doc_sql.startswith("INSERT INTO documents (")
    assert "original_path" not in doc_sql
    # Колонка status не называется вовсе: живой статус теперь в
    # doc_processing, а documents.status остаётся при своём DEFAULT (I8).
    assert "status" not in doc_sql
    assert doc_sql.count("%s") == 10 and len(doc_params) == 10
    assert doc_params[0] == str(doc_id) and doc_params[1] == "s3://b/k.txt"
    # Колонки приёма названы и без значений: nullable плюс source_kind со
    # своим 'upload' — ровно то, что писал бы DEFAULT.
    assert doc_params[-3:] == (None, None, "upload")
    assert proc_sql.startswith("INSERT INTO doc_processing (doc_id)")
    assert proc_params == (str(doc_id),)


async def test_accept_adds_original_path_when_given(monkeypatch, pg) -> None:
    conn = _patch_conn(monkeypatch)
    await pg.accept_document(
        uuid.uuid4(), "s3://b/k.txt", original_path="s3://b/orig/k.docx",
    )

    sql, params = conn.cur.sql[0]
    assert "original_path" in sql
    assert sql.count("%s") == 11 and params[-1] == "s3://b/orig/k.docx"


async def test_accept_always_names_intake_columns(monkeypatch, pg) -> None:
    """Колонки приёма в списке всегда — число ``%s`` не зависит от того,
    какие необязательные аргументы передали."""
    conn = _patch_conn(monkeypatch)
    first = uuid.uuid4()
    await pg.accept_document(
        uuid.uuid4(), "s3://b/k.txt",
        content_sha256="a" * 64, duplicate_of=first, source_kind="upload",
    )

    sql, params = conn.cur.sql[0]
    assert "content_sha256" in sql and "duplicate_of" in sql
    assert "source_kind" in sql
    # original_path не передавали — его в списке колонок нет.
    assert "original_path" not in sql
    assert sql.count("%s") == 10 and len(params) == 10
    # Хеш у версии не пишется — см. test_accept_nulls_sha_on_version_row.
    assert params[-3:] == (None, str(first), "upload")
    # intake_status не называется: его DEFAULT 'accepted' — ровно тот
    # вердикт, с которым документ принимают.
    assert "intake_status" not in sql


async def test_accept_nulls_sha_on_version_row(monkeypatch, pg) -> None:
    """Хеш принадлежит КАНОНИЧЕСКОЙ строке: у версии в колонке NULL.

    Инвариант держится здесь, в единственной точке записи, а не у
    вызывающих: маршрут передаёт один и тот же ``accept_kwargs`` и для
    канонической строки, и для версии, и для повтора после гонки.

    Без этого версия попадала бы в предикат частичного уникального индекса
    сразу после ``ON DELETE SET NULL``: удаление канонического документа с
    ДВУМЯ версиями обнуляет обе ссылки одним UPDATE'ом, и обе строки
    одновременно входят в индекс с одинаковым хешем — DELETE падает
    нарушением уникальности вместо того, чтобы пройти.
    """
    conn = _patch_conn(monkeypatch)
    sha, first = "a" * 64, uuid.uuid4()
    await pg.accept_document(
        uuid.uuid4(), "s3://b/k.txt", content_sha256=sha, duplicate_of=first,
    )
    _, version_params = conn.cur.sql[0]
    assert version_params[-3:-1] == (None, str(first))

    # Та же заливка без ссылки на оригинал — хеш записан: иначе дедуп
    # перестал бы находить вообще что-либо.
    conn = _patch_conn(monkeypatch)
    await pg.accept_document(uuid.uuid4(), "s3://b/k.txt", content_sha256=sha)
    _, canon_params = conn.cur.sql[0]
    assert canon_params[-3:-1] == (sha, None)


# ── find_by_sha ──────────────────────────────────────────────────────


async def test_find_by_sha_selects_canonical_row(monkeypatch, pg) -> None:
    """Предикат повторяет частичный уникальный индекс documents_sha_idx:
    один непустой хеш — одна строка.

    Условия по ``duplicate_of`` в запросе нет и быть не должно: хеш есть
    только у канонической строки, поэтому выборка не может вернуть версию,
    а второй копии правила в SQL не появляется.
    """
    first = uuid.uuid4()
    conn = _patch_conn(
        monkeypatch, rows=[(first, "accepted", "s3://kb-uploads/x/t.txt")],
    )
    found = await pg.find_by_sha("b" * 64)
    # Путь канонической строки нужен наблюдению перепоста: оно ссылается на
    # ТОТ ЖЕ объект в MinIO, второй копии тела не появляется.
    assert (found.id, found.intake_status) == (first, "accepted")
    assert found.path == "s3://kb-uploads/x/t.txt"

    sql, params = conn.cur.sql[0]
    assert "SELECT id, intake_status, path FROM documents" in sql
    assert "content_sha256 = %s" in sql
    where = sql.split("WHERE", 1)[1]
    assert "duplicate_of" not in where
    # Отклонённый документ из выборки НЕ исключается: он остаётся владельцем
    # хеша, и 409 отдаёт его вердикт вместо второго такого же отказа.
    assert "intake_status" not in where
    assert params == ("b" * 64,)


async def test_find_by_sha_returns_none_for_unknown_body(monkeypatch, pg) -> None:
    _patch_conn(monkeypatch, rows=[])
    assert await pg.find_by_sha("c" * 64) is None


# ── reject ───────────────────────────────────────────────────────────


async def test_reject_updates_intake_and_deletes_processing(monkeypatch, pg) -> None:
    """Отказ приёма — тоже один акт: вердикт в ``documents`` и УДАЛЕНИЕ
    строки обработки, на одном соединении и под один commit.

    Именно удаление, а не терминальный статус: домен ``doc_processing``
    намеренно не содержит 'skipped', и UPDATE туда упал бы на CHECK.
    """
    conn = _patch_conn(monkeypatch)
    doc_id = uuid.uuid4()
    await pg.reject(doc_id, "classifier: not relevant")

    assert len(conn.cur.sql) == 2 and conn.commits == 1
    upd_sql, upd_params = conn.cur.sql[0]
    del_sql, del_params = conn.cur.sql[1]
    # Порядок важен для читателя, а не для БД: сначала появляется вердикт,
    # по которому строку и опознают как отклонённую, и только потом
    # исчезает строка обработки.
    assert "UPDATE documents" in upd_sql
    assert "intake_status = 'rejected'" in upd_sql
    assert "intake_reason = %s" in upd_sql and "WHERE id = %s" in upd_sql
    assert upd_params == ("classifier: not relevant", str(doc_id))
    assert "DELETE FROM doc_processing" in del_sql
    assert del_params == (str(doc_id),)


async def test_reject_never_writes_skipped_into_processing(monkeypatch, pg) -> None:
    # Гард против «починки» отказа обычным update_status'ом: 'skipped' —
    # отчётное имя вердикта приёма, а не значение статуса обработки.
    conn = _patch_conn(monkeypatch)
    await pg.reject(uuid.uuid4(), "classifier: not relevant")
    assert "skipped" not in " ".join(q for q, _ in conn.cur.sql)


# ── list_id_path ─────────────────────────────────────────────────────


async def test_list_id_path_selects_id_and_path(monkeypatch, pg) -> None:
    did = uuid.uuid4()
    conn = _patch_conn(monkeypatch, rows=[(did, "/tmp/a.txt")])
    assert await pg.list_id_path() == [(str(did), "/tmp/a.txt")]
    assert conn.cur.sql[0][0] == "SELECT id, path FROM documents"


# ── get ──────────────────────────────────────────────────────────────


async def test_get_computes_effective_values_in_sql(monkeypatch, pg) -> None:
    """Две таблицы сводит SQL — тем же выражением, что у агрегатов.

    Все три случая (есть строка обработки / отказ приёма её удалил /
    дорасщеплённая строка) считает одно ``EFFECTIVE_STATUS``, поэтому
    второй копии правила в ``from_dict`` нет.  Псевдонимы ``eff_*``
    обязательны: status/error/summary есть в обеих таблицах, и dict_row
    схлопнул бы каждую пару в один ключ.
    """
    row = _doc_row(eff_status="completed", eff_summary="p")
    conn = _patch_conn(monkeypatch, rows=[row])
    doc = await pg.get(row["id"])

    sql, params = conn.cur.sql[0]
    assert "FROM documents d" in sql
    assert "LEFT JOIN doc_processing p ON p.doc_id = d.id" in sql
    assert f"{repo_mod.EFFECTIVE_STATUS} AS eff_status" in sql
    assert "COALESCE(NULLIF(p.error, ''), d.intake_reason) AS eff_error" in sql
    assert "COALESCE(p.summary, '') AS eff_summary" in sql
    assert "WHERE d.id = %s" in sql
    assert params == (str(row["id"]),)
    assert isinstance(doc, DocumentRow)
    assert doc.path == row["path"] and doc.status == "completed"
    # summary — из строки обработки, а не из одноимённой колонки documents
    # (там у принятого документа навсегда остаётся DEFAULT).
    assert doc.summary == "p"
    # Колонки original_path в выборке не было → None, без KeyError.
    assert doc.original_path is None


async def test_get_of_pending_doc(monkeypatch, pg) -> None:
    row = _doc_row(eff_status="pending", eff_error="", eff_summary="")
    _patch_conn(monkeypatch, rows=[row])
    doc = await pg.get(row["id"])
    assert doc is not None
    assert doc.status == "pending" and doc.intake_status == "accepted"
    assert doc.error == "" and doc.summary == ""


async def test_get_of_rejected_doc(monkeypatch, pg) -> None:
    """Вердикт приёма — отдельное измерение рядом с эффективным статусом:
    'skipped' считает SQL, а ``intake_status``/``intake_reason`` приезжают
    колонками documents и объясняют, ЧЬЁ это решение."""
    row = _doc_row(eff_status="skipped", eff_error="classifier: not relevant",
                   eff_summary="", intake_status="rejected",
                   intake_reason="classifier: not relevant")
    _patch_conn(monkeypatch, rows=[row])
    doc = await pg.get(row["id"])
    assert doc is not None
    assert doc.status == "skipped"
    assert doc.error == "classifier: not relevant"
    assert doc.intake_status == "rejected"
    assert doc.intake_reason == "classifier: not relevant"


async def test_get_returns_none_when_absent(monkeypatch, pg) -> None:
    _patch_conn(monkeypatch, rows=[])
    assert await pg.get(uuid.uuid4()) is None


# ── status_counts_by ─────────────────────────────────────────────────


async def test_status_counts_by_rejects_bad_dimension(monkeypatch, pg) -> None:
    conn = _patch_conn(monkeypatch)
    with pytest.raises(ValueError, match="bad dimension"):
        await pg.status_counts_by("source_channel; DROP TABLE documents")
    assert conn.cur.sql == []


async def test_status_counts_by_fills_every_status_key_plus_total(
    monkeypatch, pg,
) -> None:
    conn = _patch_conn(monkeypatch, rows=[
        ("alpha", "completed", True, 3), ("alpha", "failed", True, 1),
        ("beta", "pending", True, 7),
    ])
    rows = await pg.status_counts_by("source_channel")

    sql, params = conn.cur.sql[0]
    assert "FROM documents" in sql and "source_channel AS key" in sql
    assert "source_channel <> ''" in sql and params == []
    # Сортировка по total убыв.: beta(7) впереди alpha(4).
    assert [r["key"] for r in rows] == ["beta", "alpha"]
    assert rows[1]["total"] == 4 and rows[1]["completed"] == 3
    for r in rows:
        assert set(r) == {"key", "total", *DOC_STATUSES, "versions"}
        assert r["versions"] == {}


async def test_status_counts_keeps_skipped_key(monkeypatch, pg) -> None:
    """'skipped' остаётся отчётным именем отклонённого приёмом документа:
    StatRow требует этот ключ, и без него /stats/messages отдал бы 500 на
    валидации ответа (те же колонки у message_stats и схемы MCP)."""
    conn = _patch_conn(monkeypatch, rows=[("alpha", "skipped", True, 2)])
    rows = await pg.status_counts_by("source_channel")

    sql, _ = conn.cur.sql[0]
    assert "LEFT JOIN doc_processing p ON p.doc_id = d.id" in sql
    assert "COALESCE(p.status, CASE WHEN d.intake_status = 'rejected'" in sql
    assert "THEN 'skipped' WHEN d.intake_status = 'duplicate'" in sql
    assert "THEN 'duplicate' ELSE d.status END)" in sql
    # GROUP BY повторяет ВЫРАЖЕНИЕ, а не псевдоним: неоднозначное имя в
    # GROUP BY Postgres разрешает в пользу ВХОДНОЙ колонки, то есть
    # `GROUP BY status` молча сгруппировал бы по d.status.
    assert "COALESCE(p.status" in sql.split("GROUP BY", 1)[1]
    assert rows[0]["skipped"] == 2 and rows[0]["total"] == 2
    assert set(rows[0]) == {"key", "total", *DOC_STATUSES, "versions"}


async def test_status_counts_keeps_versions_out_of_total(monkeypatch, pg) -> None:
    """Версия не документ: в `total` и в разбивку она не попадает…"""
    conn = _patch_conn(monkeypatch, rows=[
        ("alpha", "completed", True, 3), ("alpha", "failed", False, 2),
    ])
    rows = await pg.status_counts_by("source_channel")

    assert rows[0]["total"] == 3 and rows[0]["completed"] == 3
    assert rows[0]["failed"] == 0
    # Признак каноничности считает SQL — выражением, а не псевдонимом.
    sql, _ = conn.cur.sql[0]
    assert "(d.duplicate_of IS NULL) AS canonical" in sql
    assert "(d.duplicate_of IS NULL)" in sql.split("GROUP BY", 1)[1]
    # …но и не фильтруется в WHERE: иначе её исход виден не был бы нигде.
    assert "duplicate_of" not in sql.split("WHERE", 1)[1].split("GROUP BY", 1)[0]


async def test_status_counts_reports_version_outcomes(monkeypatch, pg) -> None:
    """…а виден в добавочном ``versions``.

    Версия идёт в пайплайн наравне с документом (политика
    ``on_duplicate=version``, её шлёт документированный реингест
    ``scripts/tg_ingest.py --reingest``), поэтому её `failed` — ровно тот
    ответ, за которым оператор и реингестил канал.  До этого поля он не был
    виден ни в одной из трёх поверхностей отчётности.
    """
    conn = _patch_conn(monkeypatch, rows=[
        ("alpha", "completed", True, 1),
        ("alpha", "failed", False, 2),
        ("alpha", "completed", False, 1),
        # Канал, у которого в окне ТОЛЬКО версии: канон залит раньше `since`.
        ("beta", "failed", False, 5),
    ])
    rows = {r["key"]: r for r in await pg.status_counts_by("source_channel")}

    assert rows["alpha"]["versions"] == {"failed": 2, "completed": 1}
    assert rows["alpha"]["total"] == 1
    assert rows["beta"]["versions"] == {"failed": 5}
    assert rows["beta"]["total"] == 0
    # Нули в versions не печатаются: у подавляющего большинства ключей
    # версий нет вовсе, и {статус: 0} был бы шумом в каждой строке.
    assert "pending" not in rows["alpha"]["versions"]
    assert conn.cur.sql  # запрос был один, второго round-trip'а нет
    assert len(conn.cur.sql) == 1


async def test_status_counts_by_binds_since_and_until(monkeypatch, pg) -> None:
    conn = _patch_conn(monkeypatch)
    since, until = dt.date(2026, 1, 1), dt.date(2026, 2, 1)
    await pg.status_counts_by("source_group", since=since, until=until)

    sql, params = conn.cur.sql[0]
    assert "created_at >= %s" in sql and "created_at < %s" in sql
    assert params == [since, until]


# ── timeline_counts ──────────────────────────────────────────────────


async def test_timeline_counts_rejects_bad_date_field(monkeypatch, pg) -> None:
    conn = _patch_conn(monkeypatch)
    with pytest.raises(ValueError, match="bad date_field"):
        await pg.timeline_counts(date_field="updated_at")
    assert conn.cur.sql == []


async def test_timeline_counts_rejects_bad_group_by(monkeypatch, pg) -> None:
    conn = _patch_conn(monkeypatch)
    with pytest.raises(ValueError, match="bad group_by"):
        await pg.timeline_counts(group_by="source_channel")
    assert conn.cur.sql == []


async def test_timeline_counts_without_group_by(monkeypatch, pg) -> None:
    day = dt.date(2026, 10, 19)
    conn = _patch_conn(monkeypatch, rows=[(day, 5)])
    assert await pg.timeline_counts() == [{"day": day, "count": 5}]

    sql, params = conn.cur.sql[0]
    assert "date_trunc('day', created_at)::date AS day" in sql
    assert "FROM documents" in sql and "created_at IS NOT NULL" in sql
    assert "AS key" not in sql and params == []


async def test_timeline_counts_sql_touches_only_documents(monkeypatch, pg) -> None:
    # Все колонки ленты живут в documents — join'ить обработку незачем.
    conn = _patch_conn(monkeypatch)
    await pg.timeline_counts()
    assert "doc_processing" not in conn.cur.sql[0][0]


async def test_timeline_counts_excludes_versions_but_counts_sightings(
    monkeypatch, pg,
) -> None:
    """Версия и наблюдение — разные вещи, и лента их различает.

    Версия (политика ``version``) — вторая копия того же сообщения, она не
    добавляет дню ещё одного сообщения.  Наблюдение
    (``intake_status='duplicate'``) — ОТДЕЛЬНОЕ сообщение отдельного канала,
    у которого просто уже известное тело; без него канал, живущий
    перепостами, показывал бы в ленте ноль.
    """
    conn = _patch_conn(monkeypatch)
    await pg.timeline_counts()
    where = conn.cur.sql[0][0].split("WHERE", 1)[1]
    assert "duplicate_of IS NULL OR intake_status = 'duplicate'" in where


async def test_timeline_counts_groups_and_filters_by_key(monkeypatch, pg) -> None:
    day = dt.date(2026, 10, 19)
    conn = _patch_conn(monkeypatch, rows=[(day, "alpha", 2)])
    out = await pg.timeline_counts(
        date_field="doc_date", group_by="channel", channel="alpha",
    )
    assert out == [{"day": day, "key": "alpha", "count": 2}]

    sql, params = conn.cur.sql[0]
    assert "source_channel AS key" in sql and "source_channel = %s" in sql
    assert "date_trunc('day', doc_date)::date AS day" in sql
    assert params == ["alpha"]


# ── update_status (вторая половина расщепления, AsyncPostgres) ───────


async def test_update_status_targets_doc_processing(monkeypatch) -> None:
    """Статус обработки пишется только в doc_processing — и именно
    UPDATE, а не UPSERT: после отказа приёма строки нет, и запоздалая
    активность не должна её воскресить."""
    from src.storage import postgres as pg_mod

    conn = _Conn(_Cur())

    @asynccontextmanager
    async def graph_connection(graph, timeout=None):
        yield conn

    monkeypatch.setattr(pg_mod, "graph_connection", graph_connection)
    doc_id = uuid.uuid4()
    await pg_mod.AsyncPostgres(graph=default_graph_context()).update_status(
        doc_id, status="completed", summary="s",
    )

    sql, params = conn.cur.sql[0]
    assert "UPDATE doc_processing" in sql
    assert "UPDATE documents" not in sql
    assert "INSERT" not in sql and "CONFLICT" not in sql
    assert "WHERE doc_id = %s" in sql
    assert params == ("completed", "", "s", str(doc_id))
    assert conn.commits == 1


# ── наблюдение перепоста (intake_status='duplicate') ─────────────────


async def test_record_sighting_writes_one_row_without_processing(
    monkeypatch, pg,
) -> None:
    """Перепост уже известного тела — одна строка и ничего больше.

    Работы по нему нет (в графе остаётся одна копия тела), поэтому строки
    ``doc_processing`` у наблюдения не появляется — её отсутствие и есть
    признак «в пайплайн не уходило».  Хеш не называется: он собственность
    канонической строки, иначе наблюдение попало бы в частичный уникальный
    индекс ``documents_sha_idx`` и INSERT упал бы на дубле.
    """
    sighting, canon = uuid.uuid4(), uuid.uuid4()
    conn = _patch_conn(monkeypatch)
    await pg.record_duplicate_sighting(
        sighting, canon, "s3://kb-uploads/canon/t.txt",
        doc_type="txt", source_channel="beta", source_group="news",
    )

    assert len(conn.cur.sql) == 1, conn.cur.sql
    sql, params = conn.cur.sql[0]
    assert "INSERT INTO documents" in sql
    assert "doc_processing" not in sql
    assert "content_sha256" not in sql
    assert "intake_status" in sql and "duplicate_of" in sql
    # Идентификаторы едут строками, как в accept_document.
    assert str(sighting) in params and str(canon) in params
    assert "beta" in params and "news" in params
    assert "duplicate" in params
    assert conn.commits == 1


async def test_effective_status_names_duplicate(monkeypatch, pg) -> None:
    """Наблюдение не ``pending``: работы по нему нет и не будет.

    Без этой ветки эффективный статус упал бы на ``documents.status``, где у
    любой новой строки навсегда DEFAULT 'pending' (I8), и наблюдение
    выглядело бы вечно ждущим обработки.
    """
    assert "d.intake_status = 'duplicate' THEN 'duplicate'" in repo_mod.EFFECTIVE_STATUS


async def test_get_of_sighting_reports_duplicate(monkeypatch, pg) -> None:
    canon = uuid.uuid4()
    row = _doc_row(
        intake_status="duplicate", duplicate_of=canon,
        eff_status="duplicate", eff_error="", eff_summary="",
    )
    _patch_conn(monkeypatch, rows=[row])
    doc = await pg.get(row["id"])
    assert doc is not None and doc.status == "duplicate"


async def test_status_counts_puts_sighting_into_versions(monkeypatch, pg) -> None:
    """Наблюдение видно по каналу, но документом не считается."""
    _patch_conn(monkeypatch, rows=[
        ("beta", "completed", True, 2), ("beta", "duplicate", False, 5),
    ])
    rows = await pg.status_counts_by("source_channel")

    assert len(rows) == 1
    assert rows[0]["key"] == "beta"
    assert rows[0]["total"] == 2
    assert rows[0]["completed"] == 2
    assert rows[0]["versions"] == {"duplicate": 5}
