"""Analytics "communities" graph ops (read-only, fail-soft):
community_overview + entity_communities. ``personalized_pagerank`` stays in the
primitive (an in-worker igraph compute in ``graph.analysis``, fail-soft to
``[]``).

``NebulaCommunitiesGraphOps``:
- ``community_overview``: MATCH the Community tag by level (community_level_idx),
  aliased ORDER BY member_count.
- ``entity_communities``: GO OVER IN_COMMUNITY from the entity VID, then FETCH the
  Community tag for level/title/summary.
Every method is fail-soft.
"""
from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, Protocol

from loguru import logger


class CommunitiesGraphOps(Protocol):
    def community_overview(self, level: int, top_n: int) -> list[dict]: ...

    def entity_communities(self, name: str) -> list[dict]: ...


def _nebula_fail_soft(method: Callable[..., list[dict]]) -> Callable[..., list[dict]]:
    @functools.wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> list[dict]:
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:  # fail-soft, like store_query.run_rows
            logger.warning("analytics query failed: {e}", e=exc)
            return []

    return wrapper


class NebulaCommunitiesGraphOps:
    def __init__(self, store: Any):
        self._store = store

    def _exec(self, stmt: str) -> list[dict]:
        return list(self._store.structured_query(stmt) or [])

    @_nebula_fail_soft
    def community_overview(self, level: int, top_n: int) -> list[dict]:
        stmt = (
            f"MATCH (c:`Community`) WHERE c.`Community`.level == {int(level)} "
            "RETURN c.`Community`.title AS title, c.`Community`.summary AS summary, "
            "c.`Community`.member_count AS member_count "
            f"ORDER BY member_count DESC LIMIT {int(top_n)};"
        )
        return self._exec(stmt)

    @_nebula_fail_soft
    def entity_communities(self, name: str) -> list[dict]:
        from src.graph.nebula_store import _q, entity_vid

        vid = entity_vid(name)
        edge_rows = self._exec(
            f"GO FROM {_q(vid)} OVER `IN_COMMUNITY` YIELD dst(edge) AS cvid;"
        )
        cvids = [row.get("cvid") for row in edge_rows if row.get("cvid")]
        if not cvids:
            return []
        vid_list = ", ".join(_q(c) for c in cvids)
        prop_rows = self._exec(
            f"FETCH PROP ON `Community` {vid_list} YIELD "
            "`Community`.level AS level, `Community`.title AS title, "
            "`Community`.summary AS summary;"
        )
        return [
            {"level": row.get("level"), "title": row.get("title"), "summary": row.get("summary")}
            for row in prop_rows
        ]


def build_communities_graph_ops(store: Any) -> CommunitiesGraphOps:
    return NebulaCommunitiesGraphOps(store)
