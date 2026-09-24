"""Analytics "signals" graph ops (P2 decision-ready queues, read-only,
fail-soft). ``NebulaSignalsGraphOps``:
- ``recommended_merges``: fetch non-id entity names, group by case/space-
  insensitive display name in Python (nebula MATCH has no toLower/trim).
- ``review_queue``: fetch each Organization's neighbour labels, classify shell
  orgs (deg>0 and every neighbour is an identifier) in Python.
- ``circular_ownership``: var-len ``RELATED*2..6`` with ``all(rel.rel_type ==
  'OWNS')`` (cluster-verified), sort by cycle length in Python.
- ``risk_score`` / ``investigate_next`` → ``[]``: no ``risk_score`` / ``risk_band``
  / ``completeness_score`` columns on the nebula Entity tag (Tier-B risk
  materialize). Already ``[]`` via run_rows fail-soft; made explicit here.
Every method is fail-soft.
"""
from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, Protocol

from loguru import logger

from src.analytics.ids import ID_TYPES

# defensive cap on var-len path enumeration under nebula (neo4j has none; a
# circular-ownership red flag is rare, so this only guards pathological graphs).
_CYCLE_SCAN_CAP = 10000


class SignalsGraphOps(Protocol):
    def risk_score(self, name: str | None, band: str | None, top_n: int) -> list[dict]: ...

    def investigate_next(self, top_n: int) -> list[dict]: ...

    def recommended_merges(self, top_n: int) -> list[dict]: ...

    def review_queue(self, top_n: int) -> list[dict]: ...

    def circular_ownership(self, top_n: int) -> list[dict]: ...


def _nebula_fail_soft(method: Callable[..., list[dict]]) -> Callable[..., list[dict]]:
    @functools.wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> list[dict]:
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:  # fail-soft, like store_query.run_rows
            logger.warning("analytics query failed: {e}", e=exc)
            return []

    return wrapper


def _list_literal(items: list[str]) -> str:
    from src.graph.nebula_store import _q

    return "[" + ", ".join(_q(v) for v in items) + "]"


class NebulaSignalsGraphOps:
    def __init__(self, store: Any):
        self._store = store

    def _exec(self, stmt: str) -> list[dict]:
        return list(self._store.structured_query(stmt) or [])

    @_nebula_fail_soft
    def risk_score(self, name: str | None, band: str | None, top_n: int) -> list[dict]:
        # risk_score/risk_band/risk_components are materialized on Entity by the
        # in-worker risk stage (materialize_activities). Default 0 = unmaterialized.
        from src.graph.nebula_store import _q

        clauses = ["e.`Entity`.risk_score > 0"]
        if name:
            clauses.append(f"e.`Entity`.name == {_q(name)}")
        if band:
            clauses.append(f"e.`Entity`.risk_band == {_q(band)}")
        where = " AND ".join(clauses)
        stmt = (
            f"MATCH (e:`Entity`) WHERE {where} "
            "RETURN e.`Entity`.name AS name, e.`Entity`.risk_score AS score, "
            "e.`Entity`.risk_band AS band, e.`Entity`.risk_components AS components "
            f"ORDER BY score DESC LIMIT {int(top_n)};"
        )
        return self._exec(stmt)

    @_nebula_fail_soft
    def investigate_next(self, top_n: int) -> list[dict]:
        # High risk x low completeness. risk_score/completeness_score materialized.
        stmt = (
            "MATCH (e:`Entity`) WHERE e.`Entity`.risk_score > 0 "
            "RETURN e.`Entity`.name AS name, e.`Entity`.risk_score AS risk, "
            "e.`Entity`.completeness_score AS completeness "
            f"ORDER BY risk DESC, completeness ASC LIMIT {int(top_n)};"
        )
        return self._exec(stmt)

    @_nebula_fail_soft
    def recommended_merges(self, top_n: int) -> list[dict]:
        stmt = (
            f"MATCH (e:`Entity`) WHERE e.`Entity`.label NOT IN {_list_literal(ID_TYPES)} "
            "RETURN e.`Entity`.name AS name;"
        )
        groups: dict[str, list[str]] = {}
        for row in self._exec(stmt):
            name = row.get("name")
            if name is None:
                continue
            groups.setdefault(name.strip().lower(), []).append(name)
        out = [
            {"key": key, "names": names, "count": len(names)}
            for key, names in groups.items()
            if len(names) > 1
        ]
        out.sort(key=lambda r: r["count"], reverse=True)
        return out[:top_n]

    @_nebula_fail_soft
    def review_queue(self, top_n: int) -> list[dict]:
        # Shell orgs: every neighbour is an identifier. Fetch neighbour labels
        # (nebula rejects the sum(CASE ...) + WHERE-in-OPTIONAL) and classify in
        # Python.
        stmt = (
            "MATCH (e:`Entity`) WHERE e.`Entity`.label == 'Organization' "
            "OPTIONAL MATCH (e)-[:`RELATED`]-(n:`Entity`) "
            "RETURN e.`Entity`.name AS name, collect(n.`Entity`.label) AS neighbor_labels;"
        )
        id_set = set(ID_TYPES)
        out = []
        for row in self._exec(stmt):
            labels = [lbl for lbl in (row.get("neighbor_labels") or []) if lbl is not None]
            deg = len(labels)
            id_links = sum(1 for lbl in labels if lbl in id_set)
            if deg > 0 and deg == id_links:
                out.append({"name": row.get("name"), "degree": deg, "flag": "shell_signal"})
        out.sort(key=lambda r: r["degree"], reverse=True)
        return out[:top_n]

    @_nebula_fail_soft
    def circular_ownership(self, top_n: int) -> list[dict]:
        # var-len OWNS cycle (rel_type property, not an edge type); ORDER BY
        # size(cycle) is a computed expr nebula can't sort on, so sort in Python.
        stmt = (
            "MATCH p=(a:`Entity`)-[e:`RELATED`*2..6]->(a) "
            "WHERE all(rel IN e WHERE rel.rel_type == 'OWNS') "
            "RETURN [n IN nodes(p) | n.`Entity`.name] AS cycle "
            f"LIMIT {_CYCLE_SCAN_CAP};"
        )
        rows = [{"cycle": row.get("cycle") or []} for row in self._exec(stmt)]
        rows.sort(key=lambda r: len(r["cycle"]), reverse=True)
        return rows[:top_n]


def build_signals_graph_ops(store: Any) -> SignalsGraphOps:
    return NebulaSignalsGraphOps(store)
