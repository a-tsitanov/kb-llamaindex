"""Отчёт по каналу: данные, по которым человек решает, какое доверие ему дать.

Только чтение.  ``measured`` в ответе ничего не меняет сам — это улика, а
доверие, выставленное оператором (``set``), — решение.  Поэтому в ``trust``
они лежат отдельными ключами и не сводятся в одно число.

Запросы идут в Postgres напрямую из фидера (спека §9) на ОДНОМ соединении,
как ``IntakeRepository.intake_stats``: реестр приёма (``documents``,
``doc_processing``), журналы наблюдения (``entity_mention``, ``edge_new``),
журнал вытеснения фактов (``fact_supersede``).  ``src.graph`` не
импортируется (граница контуров): журнал вытеснения читается SQL-ом.

Документы канала ищутся по ВСЕМ его слагам (``source_slug``): ``@username``
меняется, ``peer_id`` — нет, а ``documents.source_channel`` хранит слаг на
момент приёма БЕЗ ``@`` (``tg_ingest`` и ``message_to_doc`` делают
``lstrip('@')``).  Слаги в реестре могут быть с ``@``, а регистр у записи
в реестре и у ``documents.source_channel`` может расходиться (фидер ищет
канал через ``casefold``), поэтому сравнение идёт по ``lower()`` с обеих
сторон, а в параметр уходят слаги в нижнем регистре и без ``@``.
"""

from __future__ import annotations

from typing import Any

from psycopg.rows import dict_row

from src.intake.sources.channel_key import normalize_slug
from src.storage.pg_scope import graph_connection
from src.tenancy.context import GraphContext

# Те же правила статуса, что в сводке приёма: documents.status у новой строки
# навсегда DEFAULT 'pending', читать его нельзя (I8).
_STATUS = (
    "COALESCE(p.status, CASE WHEN d.intake_status = 'rejected' "
    "THEN 'skipped' WHEN d.intake_status = 'duplicate' "
    "THEN 'duplicate' ELSE d.status END)"
)
_WINDOW = "d.created_at >= NOW() - make_interval(days => %s)"
# Правило ключа — `channel_key.normalize_slug` (без «@», в нижнем регистре);
# это его SQL-копия, и вторая — `ltrim(lower(s.slug), '@')` в repository.py.
# Менять правило в одном месте нельзя: поправьте Python и обе копии.
_MINE = "ltrim(lower(d.source_channel), '@') = ANY(%s)"


def _forms(slugs: list[str]) -> list[str]:
    """Слаги для ``ltrim(lower(d.source_channel), '@') = ANY(%s)``: без ``@``, в нижнем регистре."""
    return sorted({normalize_slug(s) for s in slugs} - {""})


def _ratio(a: int, b: int) -> float:
    return round(a / b, 6) if b else 0.0


async def channel_report(
    graph: GraphContext, peer_id: int, *, days: int = 30,
) -> dict[str, Any]:
    """Отчёт по каналу ``peer_id`` за ``days`` дней.

    Ключи: ``volume``, ``fate``, ``origin``, ``reposts_of``,
    ``contradictions``, ``graph_yield``, ``coverage``, ``trust``.

    ``graph_yield.new_edges_per_doc`` считается по ``edge_new`` — журналу
    рёбер, ВПЕРВЫЕ увидевших свет (UNIQUE по паре вершин: повторная
    встреча ребра журнал не пополняет).  Поэтому число честное лишь как
    «новое знание от канала»: ребро, которое в графе уже было, новым
    знанием канала не является, и в это число оно не входит.  Отсюда
    пометка ``first_seen_only: True`` рядом с ним.

    Пустой канал (нет слагов или документов) даёт нули, не ``None``.
    ``trust.set`` — единственное место, где ``None`` осмыслен: «как у группы».
    ``None`` и когда строки ``source`` нет вовсе, и когда ``trust`` в ней не
    выставлен: отчёт эти два случая не различает.

    ``reposts_of`` внутренне соединяет строку-владельца (``duplicate_of``):
    перепост с осиротевшим владельцем в список не попадёт, и сумма там может
    быть меньше ``origin.repost``.

    ``entities_per_doc`` делится на все документы-владельцы, в том числе не
    дошедшие до графа (``failed``/``skipped``), поэтому отношение занижено.
    """
    async with graph_connection(graph) as conn, conn.cursor(row_factory=dict_row) as cur:
        # (1) Слаги пира за всю историю.
        await cur.execute(
            "SELECT slug FROM source_slug WHERE peer_id = %s", (peer_id,),
        )
        slugs = _forms([r["slug"] for r in await cur.fetchall()])
        # (2) Выставленное оператором доверие (NULL = как у группы).
        await cur.execute("SELECT trust FROM source WHERE peer_id = %s", (peer_id,))
        src = await cur.fetchone()
        # (3) Объём, судьба и происхождение одной выборкой.  Перепост —
        # строка-наблюдение (intake_status='duplicate'), у остальных тело
        # принесено первым.
        origin = "CASE WHEN d.intake_status = 'duplicate' THEN 'repost' ELSE 'owner' END"
        await cur.execute(
            f"SELECT {origin} AS origin, {_STATUS} AS status, COUNT(*) AS n "
            "FROM documents d LEFT JOIN doc_processing p ON p.doc_id = d.id "
            # GROUP BY по номерам: имя «status» совпало бы с колонкой documents.
            f"WHERE {_MINE} AND {_WINDOW} GROUP BY 1, 2",
            (slugs, days),
        )
        fate_rows = await cur.fetchall()
        # (4) Покрытие датами.
        await cur.execute(
            "SELECT MIN(d.doc_date) AS earliest, MAX(d.doc_date) AS latest, "
            "COUNT(*) FILTER (WHERE d.doc_date IS NULL) AS without_doc_date "
            f"FROM documents d WHERE {_MINE} AND {_WINDOW}",
            (slugs, days),
        )
        cov = await cur.fetchone() or {}
        # (5) Чьи тела канал перепостил: владелец → его канал.
        await cur.execute(
            "SELECT lower(o.source_channel) AS channel, COUNT(*) AS n "
            "FROM documents d JOIN documents o ON o.id = d.duplicate_of "
            f"WHERE d.intake_status = 'duplicate' AND {_MINE} AND {_WINDOW} "
            "GROUP BY lower(o.source_channel) "
            "ORDER BY n DESC, lower(o.source_channel) LIMIT 10",
            (slugs, days),
        )
        reposts = await cur.fetchall()
        # (6) Вытеснения фактов в обе стороны, двумя отдельными выборками.
        # Окно — по возрасту ДОКУМЕНТА канала (d.created_at), как у всех
        # остальных чисел отчёта, а не по s.decided_at: иначе числитель
        # displacement_rate и его знаменатель считали бы разные периоды.
        # «Вытеснил» — документ канала новый (s.new_doc_id) и перебил
        # сохранённый факт; «вытеснен» — документ канала сохранённый
        # (s.stored_doc_id) и его перебили.  Раздельные соединения не
        # считают событие внутри одного канала дважды в одном направлении.
        # doc_id в журнале — TEXT; пустой '' (DEFAULT) ничему не равен.
        sup_sql = (
            "SELECT COUNT(*) AS n FROM fact_supersede s JOIN documents d "
            "ON d.id::text = s.{col} "
            f"WHERE {_MINE} AND {_WINDOW}"
        )
        await cur.execute(sup_sql.format(col="new_doc_id"), (slugs, days))
        won_row = await cur.fetchone() or {}
        await cur.execute(sup_sql.format(col="stored_doc_id"), (slugs, days))
        lost_row = await cur.fetchone() or {}
        # (7) Отдача графу: сущности и впервые увиденные рёбра по документам.
        await cur.execute(
            "SELECT "
            "(SELECT COUNT(*) FROM entity_mention m JOIN documents d ON d.id = m.doc_id "
            f" WHERE {_MINE} AND {_WINDOW}) AS entities, "
            "(SELECT COUNT(*) FROM edge_new e JOIN documents d ON d.id = e.doc_id "
            f" WHERE {_MINE} AND {_WINDOW}) AS new_edges",
            (slugs, days, slugs, days),
        )
        yld = await cur.fetchone() or {}

    by_status: dict[str, int] = {}
    owners = reposts_n = 0
    for r in fate_rows:
        n = int(r["n"])
        if r["origin"] == "repost":
            reposts_n += n
        else:
            owners += n
            by_status[r["status"]] = by_status.get(r["status"], 0) + n
    rows = owners + reposts_n
    won = int(won_row.get("n") or 0)
    lost = int(lost_row.get("n") or 0)
    trust_set = src["trust"] if src else None
    return {
        "days": days,
        "slugs": slugs,
        "volume": {"rows": rows, "documents": owners},
        "fate": by_status,
        "origin": {"owner": owners, "repost": reposts_n},
        "reposts_of": [
            {"channel": r["channel"], "count": int(r["n"])} for r in reposts
        ],
        "contradictions": {
            "displaced_others": won,
            "displaced_by_others": lost,
            "total": won + lost,
        },
        "graph_yield": {
            "entities_per_doc": _ratio(int(yld.get("entities") or 0), owners),
            "new_edges_per_doc": _ratio(int(yld.get("new_edges") or 0), owners),
            "first_seen_only": True,
        },
        "coverage": {
            "earliest_doc_date": cov.get("earliest"),
            "latest_doc_date": cov.get("latest"),
            "without_doc_date": int(cov.get("without_doc_date") or 0),
        },
        "trust": {
            "set": trust_set,
            "measured": {
                "repost_share": _ratio(reposts_n, rows),
                "displacement_rate": _ratio(won + lost, owners),
            },
        },
    }
