"""Entity-watch journals written at ingest (``entity_mention``, ``edge_new``).

Pure row builders + one fail-open writer called by ``build_property_graph``
after the graph write. Rows are written for EVERY entity of the document;
which of them anyone watches is the sweep's business
(``src/workflow/monitor/watch_sweep.py``).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from loguru import logger

from src.graph.nebula_store import entity_vid

_EPOCH = date(1970, 1, 1)


def epoch_days_to_date(days: int | None) -> date | None:
    return None if days is None else _EPOCH + timedelta(days=int(days))


def mention_rows(
    entities: list[Any], *, doc_id: str, doc_date: date | None, backfill: bool,
) -> list[dict[str, Any]]:
    """One row per distinct entity (first occurrence wins)."""
    rows: dict[str, dict[str, Any]] = {}
    for e in entities:
        name = getattr(e, "name", "") or ""
        if not name:
            continue
        vid = entity_vid(name)
        if vid in rows:
            continue
        props = getattr(e, "properties", {}) or {}
        rows[vid] = {
            "entity_vid": vid, "doc_id": doc_id, "entity_name": name,
            "label": getattr(e, "label", "") or "", "doc_date": doc_date,
            "mention_count": int(props.get("mention_count") or 0),
            "backfill": backfill,
        }
    return list(rows.values())


def edge_rows(
    relations: list[Any], created: Any, entities: list[Any], *,
    doc_id: str, doc_date: date | None, backfill: bool,
) -> list[dict[str, Any]]:
    """Rows for the relations whose (src_vid, tgt_vid) pair the graph write
    just created. ``created`` is what ``upsert_relations`` returned; anything
    but a list (non-nebula store) means "unknown" and yields nothing."""
    if not isinstance(created, list) or not created:
        return []
    new = set(created)
    labels = {
        entity_vid(getattr(e, "name", "") or ""): getattr(e, "label", "") or ""
        for e in entities
    }
    rows: list[dict[str, Any]] = []
    for r in relations:
        src_name = str(getattr(r, "source_id", "") or "")
        tgt_name = str(getattr(r, "target_id", "") or "")
        key = (entity_vid(src_name), entity_vid(tgt_name))
        if key not in new:
            continue
        new.discard(key)  # first relation for a pair wins
        rows.append({
            "src_vid": key[0], "src_name": src_name, "src_label": labels.get(key[0], ""),
            "tgt_vid": key[1], "tgt_name": tgt_name, "tgt_label": labels.get(key[1], ""),
            "rel": getattr(r, "label", "") or "", "doc_id": doc_id, "doc_date": doc_date,
            "backfill": backfill,
        })
    return rows


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True


async def record_watch_journals(
    repo: Any, entities: list[Any], relations: list[Any], created: Any, *,
    doc_id: str, doc_date_epoch: int | None, backfill: bool,
) -> None:
    """Write both journals. Never raises: a journal is a side record and must
    not fail the ingest of the document it describes."""
    if not _is_uuid(doc_id):
        return
    doc_date = epoch_days_to_date(doc_date_epoch)
    try:
        await repo.record_mentions(
            mention_rows(entities, doc_id=doc_id, doc_date=doc_date, backfill=backfill),
        )
        await repo.record_new_edges(
            edge_rows(relations, created, entities, doc_id=doc_id, doc_date=doc_date,
                      backfill=backfill),
        )
    except Exception as exc:
        logger.warning("entity-watch journal skipped (non-fatal) doc={d}: {e}", d=doc_id, e=exc)


__all__ = ["edge_rows", "epoch_days_to_date", "mention_rows", "record_watch_journals"]
