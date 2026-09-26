"""Analytics "dynamics" graph ops (temporal validity reads,
read-only, fail-soft): relationship_timeline / polarity_evolution / whats_changed.

topic_trend / entity_activity are NOT here — they traverse (:Chunk), which isn't a
nebula graph node, so they degrade to [] via run_rows fail-soft (no nebula-specific
logic to add).

``NebulaDynamicsGraphOps`` implements the reads in nGQL now that RELATED.valid_from/valid_to are STRING (see nebula_schema): near-
verbatim MATCH with ``substr``, ``r.rel_type`` (the original relation type,
stored as a property), and string range compares on the ISO validity window.

Divergence (documented): whats_changed's third match branch — edges with NO
validity window, surfaced by the E1 first-seen ``created_at`` fallback — cannot
fire under nebula because RELATED has no ``created_at`` column yet (deferred REL
first-seen). So nebula whats_changed surfaces only edges with a validity window in
range (the 'appeared'/'ended' cases), never the 'first_seen' case.
"""
from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, Protocol

from loguru import logger


class DynamicsGraphOps(Protocol):
    def relationship_timeline(self, name: str, rel_type: str | None) -> list[dict]: ...

    def polarity_evolution(self, name: str | None, rel_type: str | None) -> list[dict]: ...

    def whats_changed(
        self,
        date_from: str,
        date_to: str,
        entity: str | None,
        from_epoch: int | None,
        to_epoch: int | None,
        top_n: int,
    ) -> list[dict]: ...


def _nebula_fail_soft(method: Callable[..., list[dict]]) -> Callable[..., list[dict]]:
    @functools.wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> list[dict]:
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:  # fail-soft, like store_query.run_rows
            logger.warning("analytics query failed: {e}", e=exc)
            return []

    return wrapper


class NebulaDynamicsGraphOps:
    def __init__(self, store: Any):
        self._store = store

    def _exec(self, stmt: str) -> list[dict]:
        return list(self._store.structured_query(stmt) or [])

    @_nebula_fail_soft
    def relationship_timeline(self, name: str, rel_type: str | None) -> list[dict]:
        from src.graph.nebula_store import _q

        rel_clause = f" AND r.rel_type == {_q(rel_type)}" if rel_type else ""
        stmt = (
            f"MATCH (e:`Entity`)-[r:`RELATED`]-(n:`Entity`) "
            f"WHERE e.`Entity`.name == {_q(name)} AND r.valid_from != ''{rel_clause} "
            "RETURN substr(r.valid_from,0,7) AS period, r.rel_type AS rel, "
            "n.`Entity`.name AS name, r.polarity AS polarity "
            "ORDER BY period;"
        )
        return self._exec(stmt)

    @_nebula_fail_soft
    def polarity_evolution(self, name: str | None, rel_type: str | None) -> list[dict]:
        from src.graph.nebula_store import _q

        clauses = ["r.valid_from != ''"]
        if name:
            clauses.append(f"e.`Entity`.name == {_q(name)}")
        if rel_type:
            clauses.append(f"r.rel_type == {_q(rel_type)}")
        where = " AND ".join(clauses)
        stmt = (
            f"MATCH (e:`Entity`)-[r:`RELATED`]-(:`Entity`) WHERE {where} "
            "RETURN substr(r.valid_from,0,7) AS period, r.polarity AS polarity, "
            "count(*) AS n ORDER BY period;"
        )
        return self._exec(stmt)

    @_nebula_fail_soft
    def whats_changed(
        self,
        date_from: str,
        date_to: str,
        entity: str | None,
        from_epoch: int | None,
        to_epoch: int | None,
        top_n: int,
    ) -> list[dict]:
        from src.graph.nebula_store import _q

        # The created_at-fallback branch (windowless edges surfaced by first-seen)
        # can't fire: RELATED has no created_at under nebula (deferred REL
        # first-seen). Match only edges whose validity window overlaps [from,to];
        # classify appeared/ended + sort in Python (nebula ORDER BY can't take
        # coalesce, and CASE stays simpler in Python).
        clauses = ["r.rel_type != 'LIKELY_LINK'"]
        if entity:
            clauses.append(f"e.`Entity`.name == {_q(entity)}")
        f, t = _q(date_from), _q(date_to)
        clauses.append(
            f"((r.valid_from >= {f} AND r.valid_from <= {t}) "
            f"OR (r.valid_to >= {f} AND r.valid_to <= {t}))"
        )
        where = " AND ".join(clauses)
        stmt = (
            f"MATCH (e:`Entity`)-[r:`RELATED`]-(n:`Entity`) WHERE {where} "
            "RETURN e.`Entity`.name AS name, r.rel_type AS rel, n.`Entity`.name AS other, "
            "r.polarity AS polarity, r.valid_from AS valid_from, r.valid_to AS valid_to;"
        )
        rows = self._exec(stmt)
        out = []
        for row in rows:
            vf = row.get("valid_from") or ""
            vt = row.get("valid_to") or ""
            if date_from <= vf <= date_to:
                change = "appeared"
            elif date_from <= vt <= date_to:
                change = "ended"
            else:
                continue  # only window-overlapping edges reach here
            out.append({
                "name": row.get("name"),
                "rel": row.get("rel"),
                "other": row.get("other"),
                "polarity": row.get("polarity"),
                "valid_from": vf,
                "valid_to": vt,
                "created_at": None,  # absent on nebula RELATED (row-shape parity)
                "change": change,
            })
        out.sort(key=lambda r: r["valid_from"] or r["valid_to"])
        return out[:top_n]


def build_dynamics_graph_ops(store: Any) -> DynamicsGraphOps:
    return NebulaDynamicsGraphOps(store)
