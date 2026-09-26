"""Analytics "aggregations" graph ops (read-only, fail-soft
counts/histograms/top-N reads).

Each method preserves the fail-soft behaviour of
``analytics/store_query.py::run_rows`` (``try/except Exception -> []``, same
warning log) — the seam replaces the raw ``run_rows(store, cypher, params)``
call inside each primitive, not the fail-soft wrapper itself.

``NebulaAggregationsGraphOps`` implements the reads in nGQL per
``docs/superpowers/nebula-analytics-ngql-rules-2026-07-11.md``: plain
``MATCH``+aggregation (nebula 3.8's openCypher subset supports this
natively, unlike ``connections``'s VID point-lookups which needed
GO/FETCH). Values are inline-quoted via ``_q``/list-literal (nebula binds
no params). Every method is fail-soft via ``_nebula_fail_soft``.
"""
from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, Protocol, get_args

from loguru import logger

from src.analytics.ids import ID_TYPES
from src.graph.schema import EntityType

# The kb_analyze planner emits entity types in lowercase ('organization'), but
# nebula stores canonical-case labels ('Organization') and the nGQL filter
# compares exact case → an exact 'organization' match returns [] (kb_analyze
# came back empty under nebula). Map any casing back to the schema's canonical
# EntityType value; CamelCase types ('EventOrAction') survive — a plain
# .capitalize() would mangle them.
_CANONICAL_LABEL = {t.lower(): t for t in get_args(EntityType)}


def _canonical_label(type_: str) -> str:
    """Normalise a caller-supplied entity type to its canonical EntityType
    casing; unknown types pass through unchanged."""
    return _CANONICAL_LABEL.get((type_ or "").strip().lower(), type_)


class AggregationsGraphOps(Protocol):
    def count_entities(self, type: str | None, exclude_identifiers: bool) -> list[dict]: ...

    def count_relationships(
        self, rel_type: str | None, polarity: str | None
    ) -> list[dict]: ...

    def distribution_by_type(self, exclude_identifiers: bool) -> list[dict]: ...

    def distribution_by_relation_type(self) -> list[dict]: ...

    def distribution_by_polarity(self, rel_type: str | None) -> list[dict]: ...

    def top_entities_by_mentions(
        self, type: str | None, top_n: int, exclude_identifiers: bool
    ) -> list[dict]: ...

    def top_entities_by_degree(self, type: str | None, top_n: int) -> list[dict]: ...


def _nebula_fail_soft(method: Callable[..., list[dict]]) -> Callable[..., list[dict]]:
    """``run_rows``-style ``try/except -> []``
    (same warning log) at the method level."""

    @functools.wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> list[dict]:
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:  # fail-soft, like store_query.run_rows
            logger.warning("analytics query failed: {e}", e=exc)
            return []

    return wrapper


def _list_literal(items: list[str]) -> str:
    """nGQL list literal for a ``NOT IN``/``IN`` filter (inline-quoted, no
    param_map — mirrors ``_q``)."""
    from src.graph.nebula_store import _q

    return "[" + ", ".join(_q(v) for v in items) + "]"


class NebulaAggregationsGraphOps:
    """nGQL aggregations graph ops: plain ``MATCH``+aggregation (nebula
    3.8's openCypher subset supports aggregation directly in ``MATCH`` —
    see the rules doc).
    Values are inline-quoted (nebula binds no params — ``_q`` from
    ``nebula_store``). Every method is fail-soft via ``_nebula_fail_soft``."""

    def __init__(self, store: Any):
        self._store = store

    def _exec(self, stmt: str) -> list[dict]:
        return list(self._store.structured_query(stmt) or [])

    @_nebula_fail_soft
    def count_entities(self, type: str | None, exclude_identifiers: bool) -> list[dict]:
        from src.graph.nebula_store import _q

        clauses = []
        if type:
            clauses.append(f"e.`Entity`.label == {_q(_canonical_label(type))}")
        if exclude_identifiers:
            clauses.append(f"e.`Entity`.label NOT IN {_list_literal(ID_TYPES)}")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        stmt = f"MATCH (e:`Entity`){where} RETURN count(e) AS n;"
        return self._exec(stmt)

    @_nebula_fail_soft
    def count_relationships(
        self, rel_type: str | None, polarity: str | None
    ) -> list[dict]:
        # Unfiltered: a direct edge count works (no WHERE, so no index needed).
        if rel_type is None and polarity is None:
            stmt = "MATCH (:`Entity`)-[r:`RELATED`]->(:`Entity`) RETURN count(r) AS n;"
            return self._exec(stmt)
        # Filtered: nebula rejects an edge-property WHERE on an unanchored full
        # edge scan ("IndexNotFound — No valid index found"), so scan the
        # rel_type/polarity of every edge and count matches client-side. Scale
        # note: O(E) — a filtered edge-count index is a Tier-B concern; this
        # stays correct-but-unindexed, like the rest of the graph-wide analytics.
        stmt = (
            "MATCH (:`Entity`)-[r:`RELATED`]->(:`Entity`) "
            "RETURN r.rel_type AS rel_type, r.polarity AS polarity;"
        )
        rows = self._exec(stmt)
        n = sum(
            1
            for row in rows
            if (rel_type is None or row.get("rel_type") == rel_type)
            and (polarity is None or row.get("polarity") == polarity)
        )
        return [{"n": n}]

    @_nebula_fail_soft
    def distribution_by_type(self, exclude_identifiers: bool) -> list[dict]:
        where = ""
        if exclude_identifiers:
            where = f" WHERE e.`Entity`.label NOT IN {_list_literal(ID_TYPES)}"
        stmt = (
            f"MATCH (e:`Entity`){where} "
            "RETURN e.`Entity`.label AS type, count(*) AS n ORDER BY n DESC;"
        )
        return self._exec(stmt)

    @_nebula_fail_soft
    def distribution_by_relation_type(self) -> list[dict]:
        stmt = (
            "MATCH (:`Entity`)-[r:`RELATED`]->(:`Entity`) "
            "RETURN r.rel_type AS rel, count(*) AS n ORDER BY n DESC;"
        )
        return self._exec(stmt)

    @_nebula_fail_soft
    def distribution_by_polarity(self, rel_type: str | None) -> list[dict]:
        # Unfiltered: group-by-polarity works on the anonymous-endpoint scan.
        if not rel_type:
            stmt = (
                "MATCH (:`Entity`)-[r:`RELATED`]->(:`Entity`) "
                "RETURN r.polarity AS polarity, count(*) AS n ORDER BY n DESC;"
            )
            return self._exec(stmt)
        # Filtered: an edge-property WHERE on the anonymous-endpoint scan
        # IndexNotFounds (same as count_relationships) — scan rel_type/polarity
        # and group client-side. O(E), Tier-B index deferred.
        rows = self._exec(
            "MATCH (:`Entity`)-[r:`RELATED`]->(:`Entity`) "
            "RETURN r.rel_type AS rel_type, r.polarity AS polarity;"
        )
        counts: dict[Any, int] = {}
        for row in rows:
            if row.get("rel_type") == rel_type:
                pol = row.get("polarity")
                counts[pol] = counts.get(pol, 0) + 1
        out = [{"polarity": pol, "n": n} for pol, n in counts.items()]
        out.sort(key=lambda r: r["n"], reverse=True)
        return out

    @_nebula_fail_soft
    def top_entities_by_mentions(
        self, type: str | None, top_n: int, exclude_identifiers: bool
    ) -> list[dict]:
        from src.graph.nebula_store import _q

        clauses = []
        if type:
            clauses.append(f"e.`Entity`.label == {_q(_canonical_label(type))}")
        if exclude_identifiers:
            clauses.append(f"e.`Entity`.label NOT IN {_list_literal(ID_TYPES)}")
        clauses.append("e.`Entity`.mention_count IS NOT NULL")
        where = f" WHERE {' AND '.join(clauses)}"
        stmt = (
            f"MATCH (e:`Entity`){where} "
            "RETURN e.`Entity`.name AS name, e.`Entity`.mention_count AS mentions "
            f"ORDER BY mentions DESC LIMIT {int(top_n)};"
        )
        return self._exec(stmt)

    @_nebula_fail_soft
    def top_entities_by_degree(self, type: str | None, top_n: int) -> list[dict]:
        from src.graph.nebula_store import _q

        # nebula rejects a WHERE inside OPTIONAL MATCH ("Where clause in optional
        # match is not supported"), so use a plain MATCH with the non-negated
        # filter. Consequence: entities with zero
        # non-negated edges are dropped — immaterial for top-N-by-degree (a
        # zero-degree entity never ranks).
        clauses = []
        if type:
            clauses.append(f"e.`Entity`.label == {_q(_canonical_label(type))}")
        clauses.append("(r.polarity IS NULL OR r.polarity != 'negated')")
        where = " WHERE " + " AND ".join(clauses)
        stmt = (
            f"MATCH (e:`Entity`)-[r:`RELATED`]-(:`Entity`){where} "
            "RETURN e.`Entity`.name AS name, count(r) AS degree "
            f"ORDER BY degree DESC LIMIT {int(top_n)};"
        )
        return self._exec(stmt)


def build_aggregations_graph_ops(store: Any) -> AggregationsGraphOps:
    return NebulaAggregationsGraphOps(store)
