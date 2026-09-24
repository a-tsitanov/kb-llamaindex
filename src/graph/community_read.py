"""Community READ (map-phase summary fetch).

`NebulaCommunityRead` implements the read in nGQL. Only the lexical map-phase read lives here; semantic
selection (report_vec) and hierarchy descent are deferred (report_vec is
not on the nebula vertex — Milvus owns it), as is doc<->community linkage
(chunks are not nebula graph nodes).
"""
from __future__ import annotations

from typing import Any, Protocol


class CommunityRead(Protocol):
    def read_summaries(self, *, level: int) -> list[dict]: ...


class NebulaCommunityRead:
    """nGQL community READ (map-phase). Reads the ``id`` PROPERTY (written
    by BUILD) as ``community_id`` — NOT ``id(vertex)``/VID. Values are
    inline-quoted (nebula binds no params)."""

    def __init__(self, store: Any):
        self._store = store

    def _exec(self, stmt: str) -> list[dict]:
        return list(self._store.structured_query(stmt) or [])

    def read_summaries(self, *, level: int) -> list[dict]:
        from src.graph.nebula_store import _q

        vid_rows = self._exec(
            f"LOOKUP ON `Community` WHERE `Community`.level == {int(level)} "
            "YIELD id(vertex) AS vid;"
        )
        vids = [r["vid"] for r in vid_rows if r.get("vid")]
        if not vids:
            return []
        listed = ", ".join(_q(v) for v in vids)
        rows = self._exec(
            f"FETCH PROP ON `Community` {listed} YIELD "
            "`Community`.id AS community_id, `Community`.level AS level, "
            "`Community`.summary AS summary, `Community`.member_count AS member_count;"
        )
        kept = [r for r in rows if (r.get("summary") or "").strip()]
        kept.sort(key=lambda r: (-(r.get("member_count") or 0), r.get("community_id") or ""))
        return [
            {
                "community_id": r.get("community_id"),
                "level": r.get("level"),
                "summary": r.get("summary"),
                "member_count": r.get("member_count") or 0,
            }
            for r in kept
        ]


def build_community_read(store: Any) -> CommunityRead:
    return NebulaCommunityRead(store)
