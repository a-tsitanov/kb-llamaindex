"""Analytics "domain" graph ops (issue/resolution rollup +
communication intensity, read-only, fail-soft).

``NebulaDomainGraphOps`` implements the reads in nGQL per ``docs/superpowers/nebula-analytics-ngql-rules-2026-07-11.md``:
- ``communication_stats``: near-verbatim MATCH (rel_type IN [...], undirected
  ``a.name < b.name`` dedup, count(*) per (a,b,rel) — cluster-verified).
- ``issue_resolution_stats``: the natural query is a two-level aggregation
  (``count(r)`` per issue, then ``count/sum`` over issues) with a WHERE inside
  OPTIONAL MATCH — nebula supports neither, so it runs two simple MATCH queries
  (all Issues; Issues with a non-negated RESOLVED_BY→Resolution) and computes
  total/unresolved in Python.
Every method is fail-soft.
"""
from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, Protocol

from loguru import logger


class DomainGraphOps(Protocol):
    def issue_resolution_stats(self) -> list[dict]: ...

    def communication_stats(self, name: str | None, top_n: int) -> list[dict]: ...


def _nebula_fail_soft(method: Callable[..., list[dict]]) -> Callable[..., list[dict]]:
    @functools.wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> list[dict]:
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:  # fail-soft, like store_query.run_rows
            logger.warning("analytics query failed: {e}", e=exc)
            return []

    return wrapper


class NebulaDomainGraphOps:
    def __init__(self, store: Any):
        self._store = store

    def _exec(self, stmt: str) -> list[dict]:
        return list(self._store.structured_query(stmt) or [])

    @_nebula_fail_soft
    def issue_resolution_stats(self) -> list[dict]:
        # Two-level aggregation + WHERE-in-OPTIONAL are unsupported; run two
        # simple queries and compute total/unresolved in Python (row shape:
        # [{total, unresolved}]).
        total_rows = self._exec(
            "MATCH (i:`Entity`) WHERE i.`Entity`.label == 'Issue' RETURN count(*) AS total;"
        )
        total = int((total_rows[0].get("total") if total_rows else 0) or 0)
        resolved_rows = self._exec(
            "MATCH (i:`Entity`)-[rr:`RELATED`]-(r:`Entity`) "
            "WHERE i.`Entity`.label == 'Issue' AND rr.rel_type == 'RESOLVED_BY' "
            "AND r.`Entity`.label == 'Resolution' "
            "AND (rr.polarity IS NULL OR rr.polarity != 'negated') "
            "RETURN DISTINCT i.`Entity`.name AS name;"
        )
        resolved = len({row.get("name") for row in resolved_rows if row.get("name") is not None})
        unresolved = max(total - resolved, 0)
        return [{"total": total, "unresolved": unresolved}]

    @_nebula_fail_soft
    def communication_stats(self, name: str | None, top_n: int) -> list[dict]:
        from src.graph.nebula_store import _q

        clauses = [
            "r.rel_type IN ['CONTACT', 'RESPONDED_TO']",
            "a.`Entity`.name < b.`Entity`.name",
            "(r.polarity IS NULL OR r.polarity != 'negated')",
        ]
        if name:
            clauses.append(f"(a.`Entity`.name == {_q(name)} OR b.`Entity`.name == {_q(name)})")
        stmt = (
            "MATCH (a:`Entity`)-[r:`RELATED`]-(b:`Entity`) WHERE " + " AND ".join(clauses) + " "
            "RETURN a.`Entity`.name AS a, b.`Entity`.name AS b, r.rel_type AS rel, "
            "count(*) AS interactions "
            f"ORDER BY interactions DESC LIMIT {int(top_n)};"
        )
        return self._exec(stmt)


def build_domain_graph_ops(store: Any) -> DomainGraphOps:
    return NebulaDomainGraphOps(store)
