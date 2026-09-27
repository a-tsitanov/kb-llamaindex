"""``documents_for_communities`` activity — map community ids to the
source documents their member entities were extracted from.

Graph path: (:Community {level:0}) <-IN_COMMUNITY- members → ``first_doc_id``
(see ``_docs_for_communities_nebula``).  The community hop is pinned to
level 0: member links exist at every hierarchy level, but community ``id``
is unique only per level, so the lookup must be scoped to one level to
avoid collisions.  Fail-open: a missing store or any query error → empty
list (the answer is never blocked on document provenance).
"""

from __future__ import annotations

import asyncio
from typing import Any

from temporalio import activity

from src.tenancy.activity import resolve_graph_for_activity
from src.tenancy.context import GraphContext
from src.workflow.contracts import (
    DocumentsForCommunitiesParams,
    DocumentsForCommunitiesResult,
)


def _docs_for_communities_nebula(store: Any, ids: list[str]) -> list[dict]:
    """Nebula source-doc attribution for level-0 communities. Chunks are NOT
    nebula graph nodes, so a ``(:Chunk)-[:MENTIONS]->(entity)`` hop is
    unavailable. APPROXIMATION: community → member entities (IN_COMMUNITY,
    reverse) → each member's ``first_doc_id`` (the E1 first-seen doc). This is
    coarser than an all-chunk-docs result — it captures the doc each
    member was FIRST seen in, not every doc that mentions it — but gives real
    provenance under nebula. Returns rows shaped ``{doc_id}``;
    the caller de-dups."""
    from src.graph.community_writeback import community_vid
    from src.graph.nebula_store import _chunks

    member_vids: list[str] = []
    for cid in ids:
        vid = community_vid(str(cid), 0)
        edges = store.structured_query(
            f'GO FROM "{vid}" OVER `IN_COMMUNITY` REVERSELY YIELD src(edge) AS ent'
        )
        member_vids.extend(
            e.get("ent") for e in (edges or []) if isinstance(e, dict) and e.get("ent")
        )
    member_vids = list(dict.fromkeys(member_vids))
    if not member_vids:
        return []
    out: list[dict] = []
    for chunk in _chunks(member_vids, 256):
        quoted = ", ".join('"' + v + '"' for v in chunk)
        rows = store.structured_query(
            f"FETCH PROP ON `Entity` {quoted} YIELD `Entity`.first_doc_id AS doc_id"
        )
        out.extend({"doc_id": (r or {}).get("doc_id")} for r in (rows or []))
    return out


def _get_store(graph: GraphContext) -> Any | None:
    """Graph store or None when unreachable (indirected for monkeypatch)."""
    try:
        from src.graph.store import build_graph_store
        return build_graph_store(graph)
    except Exception as exc:
        activity.logger.warning("documents_for_communities: store unavailable: %s", exc)
        return None


@activity.defn
async def documents_for_communities(
    params: DocumentsForCommunitiesParams,
) -> DocumentsForCommunitiesResult:
    activity.heartbeat({"stage": "documents_for_communities",
                        "n_communities": len(params.community_ids)})
    if not params.community_ids:
        return DocumentsForCommunitiesResult(doc_ids=[])
    graph = await resolve_graph_for_activity(params.graph_id)
    store = _get_store(graph)
    if store is None:
        return DocumentsForCommunitiesResult(doc_ids=[])
    try:
        rows = await asyncio.to_thread(
            _docs_for_communities_nebula, store, list(params.community_ids),
        )
    except Exception as exc:  # fail-open
        activity.logger.warning("documents_for_communities  err=%s", exc)
        return DocumentsForCommunitiesResult(doc_ids=[])

    doc_ids: list[str] = []
    for r in rows or []:
        d = (r or {}).get("doc_id")
        if d and d not in doc_ids:
            doc_ids.append(str(d))
    return DocumentsForCommunitiesResult(doc_ids=doc_ids)
