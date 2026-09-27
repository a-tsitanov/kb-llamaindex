"""mark_entities_dirty — flag an ingest's entities (and relation endpoints)
for wiki re-write. Best-effort: never raises out (caller ignores failures)."""
from __future__ import annotations

import asyncio

from temporalio import activity

from src.config import settings
from src.graph.store import build_graph_store
from src.graph.wiki_dirty import mark_dirty
from src.tenancy.activity import resolve_graph_for_activity
from src.workflow.contracts import MarkDirtyIn


def _dirty_names(payload: MarkDirtyIn) -> set[str]:
    return set(payload.entity_names) | set(payload.relation_endpoints)


@activity.defn
async def mark_entities_dirty(payload: MarkDirtyIn) -> int:
    if not settings.wiki.enabled:
        return 0
    names = sorted(_dirty_names(payload))
    if not names:
        return 0
    graph = await resolve_graph_for_activity(payload.graph_id)
    store = build_graph_store(graph)
    await asyncio.to_thread(mark_dirty, store, names)  # sync graph-store call — off loop
    activity.logger.info("mark_entities_dirty  count=%d", len(names))
    return len(names)
