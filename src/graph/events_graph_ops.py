"""Analytics "events" graph ops (E1 first-seen "what's new", read-only,
fail-soft). ``NebulaEventsGraphOps`` (now that
RELATED carries created_at/first_doc_id — REL first-seen):
- ``new_entities`` — MATCH on ``Entity.created_at`` (int epoch-days).
- ``entity_new_connections`` — name-anchored MATCH with the edge created_at filter.
- ``new_edges`` — a full RELATED scan (nebula IndexNotFounds an edge-property
  WHERE on an unanchored scan) then Python filter/sort/limit by created_at. O(E)
  — an edge created_at index is a Tier-B concern.
Every method is fail-soft.
"""
from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, Protocol

from loguru import logger


class EventsGraphOps(Protocol):
    def new_entities(self, since: int, top_n: int) -> list[dict]: ...

    def new_edges(self, since: int, top_n: int) -> list[dict]: ...

    def entity_new_connections(self, name: str, since: int, top_n: int) -> list[dict]: ...


def _nebula_fail_soft(method: Callable[..., list[dict]]) -> Callable[..., list[dict]]:
    @functools.wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> list[dict]:
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:  # fail-soft, like store_query.run_rows
            logger.warning("analytics query failed: {e}", e=exc)
            return []

    return wrapper


class NebulaEventsGraphOps:
    def __init__(self, store: Any):
        self._store = store

    def _exec(self, stmt: str) -> list[dict]:
        return list(self._store.structured_query(stmt) or [])

    @_nebula_fail_soft
    def new_entities(self, since: int, top_n: int) -> list[dict]:
        stmt = (
            f"MATCH (e:`Entity`) WHERE e.`Entity`.created_at >= {int(since)} "
            "RETURN e.`Entity`.name AS name, e.`Entity`.label AS type, "
            "e.`Entity`.created_at AS created_at, e.`Entity`.first_doc_id AS first_doc_id "
            f"ORDER BY created_at DESC LIMIT {int(top_n)};"
        )
        return self._exec(stmt)

    @_nebula_fail_soft
    def new_edges(self, since: int, top_n: int) -> list[dict]:
        # An edge-property WHERE on an unanchored full edge scan IndexNotFounds,
        # so scan every RELATED edge and filter/sort/limit by created_at in
        # Python. O(E) — an edge created_at index is a Tier-B concern.
        rows = self._exec(
            "MATCH (a:`Entity`)-[r:`RELATED`]->(b:`Entity`) "
            "RETURN a.`Entity`.name AS src, r.rel_type AS rel, b.`Entity`.name AS tgt, "
            "r.created_at AS created_at, r.first_doc_id AS first_doc_id;"
        )
        fresh = [r for r in rows if int(r.get("created_at") or 0) >= since]
        fresh.sort(key=lambda r: int(r.get("created_at") or 0), reverse=True)
        return fresh[:top_n]

    @_nebula_fail_soft
    def entity_new_connections(self, name: str, since: int, top_n: int) -> list[dict]:
        from src.graph.nebula_store import _q

        # Name-anchored, so the edge created_at filter runs on the expansion.
        stmt = (
            f"MATCH (e:`Entity`)-[r:`RELATED`]-(n:`Entity`) "
            f"WHERE e.`Entity`.name == {_q(name)} AND r.created_at >= {int(since)} "
            "RETURN r.rel_type AS rel, n.`Entity`.name AS other, "
            "r.created_at AS created_at, r.first_doc_id AS first_doc_id "
            f"ORDER BY created_at DESC LIMIT {int(top_n)};"
        )
        return self._exec(stmt)


def build_events_graph_ops(store: Any) -> EventsGraphOps:
    return NebulaEventsGraphOps(store)
