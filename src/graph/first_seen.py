"""E1 — emulate ON CREATE stamping (created_at/first_doc_id) post-upsert.

The entity/relationship MERGE lives inside llama_index, so we cannot set
ON CREATE there. Instead, after upsert, stamp only elements that have no
created_at yet, scoped to this ingest's elements. This means: a node
created this pass gets stamped now; a re-mentioned old node keeps its
original stamp (elements that predate enabling E1 are stamped on their
next mention — there is no backfill script for NebulaGraph).

Per-entity ``UPDATE VERTEX ... WHEN created_at == 0`` and per-edge
``UPDATE EDGE ON `RELATED` ... WHEN created_at == 0`` (atomic, first-write-
wins). RELATED carries created_at/first_doc_id columns (see nebula_schema),
and upsert_relations read-back-preserves them across re-upserts.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from src.graph.nebula_store import _q, entity_vid


def stamp_first_seen(
    store: Any,
    *,
    entity_names: list[str],
    relations: list[tuple[str, str, str]],
    ingest_epoch: int,
    doc_id: str,
) -> None:
    """Stamp created_at/first_doc_id on newly-created graph elements.

    Sets the fields ONLY on elements that have no created_at yet, so
    existing elements (re-mentioned in a later document) keep their
    original first_seen stamp. Best-effort/fail-open — a stamping failure
    never blocks ingest.

    Args:
        store: A Nebula graph store that exposes ``structured_query(stmt)``.
        entity_names: Display names of the entities upserted in this pass.
        relations: Triples ``(src_name, label, tgt_name)`` for relations upserted.
        ingest_epoch: Days since 1970-01-01 (UTC) — use ``today_epoch_days()``.
        doc_id: Identifier of the source document (best-effort provenance).
    """
    if not entity_names and not relations:
        return

    try:
        _stamp_first_seen_nebula(
            store,
            entity_names=entity_names,
            relations=relations,
            ingest_epoch=ingest_epoch,
            doc_id=doc_id,
        )
    except Exception as exc:
        logger.warning("stamp_first_seen failed (non-fatal): {e}", e=exc)


def _stamp_first_seen_nebula(
    store: Any,
    *,
    entity_names: list[str],
    relations: list[tuple[str, str, str]],
    ingest_epoch: int,
    doc_id: str,
) -> None:
    for name in entity_names:
        vid = entity_vid(name)
        stmt = (
            f'UPDATE VERTEX ON `Entity` "{vid}" '
            f"SET created_at = {int(ingest_epoch)}, first_doc_id = {_q(doc_id)} "
            "WHEN created_at == 0;"
        )
        store.structured_query(stmt)

    for src, _label, tgt in relations:
        # Rank 0 (upsert_relations writes the default rank); WHEN created_at == 0
        # keeps first-seen semantics (a re-mentioned edge keeps its stamp). Per-
        # edge try/except: UPDATE EDGE raises if the edge is missing (e.g. an
        # ER-merged-away endpoint), which must not abort the rest — mirrors the
        # per-name resilience in the wiki mark_dirty path.
        stmt = (
            f'UPDATE EDGE ON `RELATED` "{entity_vid(src)}" -> "{entity_vid(tgt)}"@0 '
            f"SET created_at = {int(ingest_epoch)}, first_doc_id = {_q(doc_id)} "
            "WHEN created_at == 0;"
        )
        try:
            store.structured_query(stmt)
        except Exception as exc:  # one missing edge must not stop the rest
            logger.debug("stamp_first_seen: nebula rel stamp skipped ({e})", e=exc)


__all__ = ["stamp_first_seen"]
