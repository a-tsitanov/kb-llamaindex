"""Entity-watch sweep: journals past a cursor -> events for watched entities.

Pure detectors (row dicts in, event dicts out) + ``run_watch_sweep``, which
drives them over ``WatchRepository``. Design:
``docs/superpowers/specs/2026-10-15-entity-watch-design.md``.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Callable
from typing import Any, get_args

from src.graph.nebula_store import entity_vid
from src.ingestion.identifiers import IdentifierType

# The other end of a new edge with one of these labels is an identifier of
# the watched entity (a phone, an address), not a new acquaintance.
IDENTIFIER_LABELS: frozenset[str] = frozenset(get_args(IdentifierType)) - {
    "DocumentDate", "Amount",
}
# Edges to these say nothing new about the watched entity: the document's own
# node and dates repeat new_mention, abstract nodes are extraction noise.
IGNORED_LABELS: frozenset[str] = frozenset({
    "DocumentDate", "Document", "Concept", "Metric", "Other",
})
EVENT_LABELS: frozenset[str] = frozenset({"EventOrAction"})


def _uuid_or_none(value: Any) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        return None


def _dedup(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for e in events:
        seen.setdefault(e["dedup_key"], e)
    return list(seen.values())


def detect_mentions(rows: list[dict[str, Any]], watched: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        vid = r.get("entity_vid")
        if vid not in watched or r.get("backfill"):
            continue
        doc = str(r.get("doc_id") or "")
        n = int(r.get("mention_count") or 0)
        out.append({
            "entity_vid": vid, "entity_name": r.get("entity_name") or watched[vid],
            "kind": "new_mention", "doc_id": _uuid_or_none(doc), "doc_date": r.get("doc_date"),
            "detail": {"mention_count": n, "label": r.get("label", "")},
            "why": f"упоминается в документе ({n} раз)" if n else "упоминается в документе",
            "source_table": "entity_mention", "source_id": r.get("id"),
            "dedup_key": f"new_mention:{vid}:{doc}",
        })
    return _dedup(out)


def detect_edges(rows: list[dict[str, Any]], watched: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        if r.get("backfill"):
            continue
        ends = (
            # (watched side, its name, other side, other name, other label, direction)
            (r.get("src_vid"), r.get("src_name"), r.get("tgt_vid"), r.get("tgt_name"),
             r.get("tgt_label", ""), "out"),
            (r.get("tgt_vid"), r.get("tgt_name"), r.get("src_vid"), r.get("src_name"),
             r.get("src_label", ""), "in"),
        )
        for vid, name, other, other_name, other_label, direction in ends:
            if vid not in watched or vid == other or other_label in IGNORED_LABELS:
                continue
            if other_label in IDENTIFIER_LABELS:
                kind = "new_identifier"
            elif other_label in EVENT_LABELS:
                kind = "new_event"
            else:
                kind = "new_connection"
            rel = r.get("rel", "")
            out.append({
                "entity_vid": vid, "entity_name": name or watched[vid], "kind": kind,
                "doc_id": _uuid_or_none(r.get("doc_id")), "doc_date": r.get("doc_date"),
                "detail": {"other": other_name, "other_vid": other, "other_label": other_label,
                           "rel": rel, "direction": direction},
                "why": f"связь {rel} впервые появилась в документе",
                "source_table": "edge_new", "source_id": r.get("id"),
                "dedup_key": f"{kind}:{vid}:{other}",
            })
    return _dedup(out)


def detect_contradictions(rows: list[dict[str, Any]], watched: dict[str, str]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        for name in (r.get("src"), r.get("tgt")):
            vid = entity_vid(name or "")
            if not name or vid not in watched:
                continue
            out.append({
                "entity_vid": vid, "entity_name": name, "kind": "contradiction",
                "doc_id": _uuid_or_none(r.get("new_doc_id")), "doc_date": None,
                "detail": {k: r.get(k) for k in (
                    "src", "rel", "tgt", "stored_polarity", "new_polarity",
                    "stored_trust", "new_trust", "stored_doc_id", "winner")},
                "why": "новый документ противоречит прежнему факту",
                "source_table": "fact_supersede", "source_id": r.get("id"),
                "dedup_key": f"contradiction:{vid}:{r.get('id')}",
            })
    return _dedup(out)


def detect_risk_rise(
    rows: list[dict[str, Any]], watched: dict[str, str], *, delta: float,
) -> list[dict[str, Any]]:
    """Рост риска у наблюдаемой сущности — событие, а не узел графа.

    Единственный детектор БЕЗ журнала: предыдущее значение лежит на узле
    (`risk_score_prev`), а не в таблице, поэтому курсор ему не нужен и
    строки приходят из графового чтения (``src/watch/activities.py``).

    Политика повтора записана в ключе дедупа — счёт округляется до двух
    знаков: дальнейший рост даёт новое событие, та же величина не даёт
    ничего.  Без округления каждый пересчёт аналитики, сдвинувший счёт в
    пятом знаке, выглядел бы новой новостью.
    """
    out = []
    for r in rows:
        vid = r.get("vid")
        if vid not in watched:
            continue
        score = float(r.get("score") or 0.0)
        prev = float(r.get("prev") or 0.0)
        if score - prev < delta:
            continue
        out.append({
            "entity_vid": vid, "entity_name": r.get("name") or watched[vid],
            "kind": "risk_rise", "doc_id": None, "doc_date": None,
            "detail": {"score": round(score, 3), "prev": round(prev, 3),
                       "delta": round(score - prev, 3)},
            "why": f"риск вырос на {round(score - prev, 2)} (до {round(score, 2)})",
            "source_table": "entity.risk_score", "source_id": None,
            "dedup_key": f"risk_rise:{vid}:{score:.2f}",
        })
    return _dedup(out)


DETECTORS: dict[str, Callable[[list[dict[str, Any]], dict[str, str]], list[dict[str, Any]]]] = {
    "entity_mention": detect_mentions,
    "edge_new": detect_edges,
    "fact_supersede": detect_contradictions,
}


async def run_watch_sweep(repo: Any, *, batch: int = 1000, max_batches: int = 50) -> dict[str, int]:
    """One pass over every journal past its cursor. Returns detected events
    by kind (the dedup key may still drop some at insert)."""
    watched = await repo.watched()
    counts: Counter[str] = Counter()
    for journal, detect in DETECTORS.items():
        for _ in range(max_batches):
            last = await repo.cursor(journal)
            rows = await repo.read_journal(journal, after_id=last, limit=batch)
            if not rows:
                break
            events = detect(rows, watched) if watched else []
            # The cursor moves even when nobody watches: a later subscription
            # starts from "now", never from history.
            await repo.save_events(journal, events, last_id=max(int(r["id"]) for r in rows))
            counts.update(e["kind"] for e in events)
            if len(rows) < batch:
                break
    return dict(counts)


__all__ = [
    "DETECTORS", "EVENT_LABELS", "IDENTIFIER_LABELS", "IGNORED_LABELS", "detect_contradictions", "detect_edges",
    "detect_mentions", "detect_risk_rise", "run_watch_sweep",
]
