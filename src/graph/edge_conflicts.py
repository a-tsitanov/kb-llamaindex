"""Trust-based fact-conflict resolution at graph-write time.

The problem this closes: ingest merges each document's extraction on its own
(`merge_kg_extraction`) and then upserts the result, and an upsert OVERWRITES
the stored edge's `polarity` / validity window (nebula keys edges by
(src, dst, rank=0); the neo4j path MERGEs on (src, type, tgt)).  A later, less
credible document therefore silently flipped a fact asserted by a more credible
one — last writer wins, no trace.  That is also why the `quality.contradictions`
primitive rarely fires: the two opposite-polarity edges it looks for cannot
coexist, one has already clobbered the other.

Policy (see `src/analytics/source_trust.py` for where the numbers come from):

  * No stored edge, or same polarity ⇒ nothing to resolve, write as usual.
  * Opposite polarity ⇒ the higher-trust source keeps the belief.  Ties go to
    the newer write (recency), which is the pre-existing behaviour.
  * The loser never blocks the rest of the write: when the stored belief wins,
    only `polarity` (and the trust that backs it) is held back — description,
    weight, keywords, chunks and validity still refresh from the new document.
  * Every conflict is returned as an `EdgeConflict` so the caller can log it to
    `fact_supersede` (Postgres) — that log, not the edge, is the audit trail.
    `superseded_at` on the winning edge marks the ingest day the previous belief
    was retired (0 = never contradicted).

Fail-open by construction: any read-back failure resolves to "no stored edges
known", which reproduces the old last-writer-wins behaviour instead of dropping
the batch.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from src.config import settings
from src.graph.nebula_store import _q, entity_vid

# Read-back templates. Both return the stored belief and what backs it.
_LOAD_RELS_NEO4J = (
    "UNWIND $pairs AS p "
    "MATCH (a:__Entity__ {name: p.src})-[r]->(b:__Entity__ {name: p.tgt}) "
    "WHERE type(r) = p.label "
    "RETURN p.src AS src, p.tgt AS tgt, type(r) AS label, "
    "r.polarity AS polarity, r.source_trust AS source_trust, "
    "r.first_doc_id AS first_doc_id"
)


@dataclass(frozen=True)
class StoredEdge:
    """The belief a stored edge currently carries."""

    polarity: str = ""
    source_trust: float = 0.0
    first_doc_id: str = ""


@dataclass(frozen=True)
class EdgeConflict:
    """One resolved (or rejected) contradiction, ready for the audit log."""

    src: str
    tgt: str
    rel: str
    stored_polarity: str
    new_polarity: str
    stored_trust: float
    new_trust: float
    stored_doc_id: str
    new_doc_id: str
    winner: str  # "stored" | "new"


def decide(
    *, stored_polarity: str, stored_trust: float, new_polarity: str, new_trust: float
) -> str:
    """Pure policy: who keeps the belief — ``"stored"`` or ``"new"``.

    Only an explicit polarity disagreement is a conflict; a missing polarity on
    either side is treated as "no claim", so the new write proceeds.
    """
    if not stored_polarity or not new_polarity:
        return "new"
    if stored_polarity == new_polarity:
        return "new"
    return "new" if new_trust >= stored_trust else "stored"


def _load_stored_nebula(store: Any, pairs: list[tuple[str, str]]) -> dict:
    # Nebula collapses every label of a pair onto one rank-0 `RELATED` edge, so
    # the key is (src, tgt) — the incoming label is not part of the identity.
    edge_list = ", ".join(f"{_q(entity_vid(s))}->{_q(entity_vid(t))}" for s, t in pairs)
    rows = store.structured_query(
        f"FETCH PROP ON `RELATED` {edge_list} YIELD "
        "src(edge) AS s, dst(edge) AS d, "
        "`RELATED`.polarity AS polarity, `RELATED`.source_trust AS source_trust, "
        "`RELATED`.first_doc_id AS first_doc_id;"
    )
    vid_key = {(entity_vid(s), entity_vid(t)): (s, t) for s, t in pairs}
    out: dict = {}
    for row in rows:
        key = vid_key.get((row.get("s"), row.get("d")))
        if key is None:
            continue
        out[key] = StoredEdge(
            polarity=str(row.get("polarity") or ""),
            source_trust=float(row.get("source_trust") or 0.0),
            first_doc_id=str(row.get("first_doc_id") or ""),
        )
    return out


def _load_stored_neo4j(store: Any, triples: list[tuple[str, str, str]]) -> dict:
    rows = store.structured_query(
        _LOAD_RELS_NEO4J,
        param_map={"pairs": [{"src": s, "tgt": t, "label": lbl} for s, t, lbl in triples]},
    )
    out: dict = {}
    for row in rows:
        out[(row.get("src"), row.get("tgt"), row.get("label"))] = StoredEdge(
            polarity=str(row.get("polarity") or ""),
            source_trust=float(row.get("source_trust") or 0.0),
            first_doc_id=str(row.get("first_doc_id") or ""),
        )
    return out


def load_stored_edges(store: Any, relations: list[Any]) -> dict:
    """Stored belief per edge key, keyed as the active backend identifies edges.

    Fail-open: an unreadable graph yields ``{}`` (= "nothing stored"), which
    keeps ingest on the pre-existing last-writer-wins path.
    """
    if not relations:
        return {}
    try:
        if settings.graph.backend == "nebula":
            pairs = sorted({(_src(r), _tgt(r)) for r in relations})
            return _load_stored_nebula(store, pairs)
        triples = sorted({(_src(r), _tgt(r), _label(r)) for r in relations})
        return _load_stored_neo4j(store, triples)
    except Exception as exc:
        logger.warning(
            "edge-conflict read-back failed (no trust resolution this round): {e}",
            e=repr(exc),
        )
        return {}


def _src(r: Any) -> str:
    # `Relation.source_id` IS the entity display name (EntityNode.id == name),
    # which is what nebula's vid hash and the neo4j name match both expect.
    return str(getattr(r, "source_id", "") or "")


def _tgt(r: Any) -> str:
    return str(getattr(r, "target_id", "") or "")


def _label(r: Any) -> str:
    return str(getattr(r, "label", "") or "")


def _key(r: Any) -> tuple:
    if settings.graph.backend == "nebula":
        return (_src(r), _tgt(r))
    return (_src(r), _tgt(r), _label(r))


def resolve_edge_conflicts(
    relations: list[Any],
    stored: dict,
    *,
    doc_trust: float,
    doc_id: str,
    ingest_epoch: int,
) -> tuple[list[Any], list[EdgeConflict]]:
    """Stamp trust on every relation and apply the conflict policy.

    Mutates each relation's ``properties`` in place (they are freshly built by
    `merge_kg_extraction`, not shared) and returns ``(relations, conflicts)``.
    The relation list is returned unshortened — a losing write is held back at
    the `polarity` field, never by dropping the edge, so co-occurrence weight
    and descriptions still refresh.
    """
    conflicts: list[EdgeConflict] = []
    for rel in relations:
        props = getattr(rel, "properties", None)
        if props is None:
            continue
        new_polarity = str(props.get("polarity") or "")
        props["source_trust"] = float(doc_trust)
        props.setdefault("superseded_at", 0)

        prev = stored.get(_key(rel))
        if prev is None:
            continue
        winner = decide(
            stored_polarity=prev.polarity,
            stored_trust=prev.source_trust,
            new_polarity=new_polarity,
            new_trust=doc_trust,
        )
        if prev.polarity == new_polarity or not prev.polarity or not new_polarity:
            # No disagreement — keep the higher trust on the edge so a later
            # low-trust write still faces the strongest source seen so far.
            props["source_trust"] = max(float(doc_trust), prev.source_trust)
            continue

        if winner == "stored":
            props["polarity"] = prev.polarity
            props["source_trust"] = prev.source_trust
        else:
            props["superseded_at"] = int(ingest_epoch)
        conflicts.append(
            EdgeConflict(
                src=_src(rel), tgt=_tgt(rel), rel=_label(rel),
                stored_polarity=prev.polarity, new_polarity=new_polarity,
                stored_trust=prev.source_trust, new_trust=float(doc_trust),
                stored_doc_id=prev.first_doc_id, new_doc_id=doc_id,
                winner=winner,
            )
        )
    if conflicts:
        logger.info(
            "edge conflicts resolved  doc={d}  total={n}  stored_won={s}",
            d=doc_id, n=len(conflicts),
            s=sum(1 for c in conflicts if c.winner == "stored"),
        )
    return relations, conflicts


__all__ = [
    "EdgeConflict",
    "StoredEdge",
    "decide",
    "load_stored_edges",
    "resolve_edge_conflicts",
]
