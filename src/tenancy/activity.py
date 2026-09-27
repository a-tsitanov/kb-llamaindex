"""Resolve an activity's graph; unknown/non-ready graphs fail the activity for good."""

from __future__ import annotations

from temporalio.exceptions import ApplicationError

from src.tenancy.context import GraphContext
from src.tenancy.registry import GraphNotFound, GraphNotReady, get_graph_registry


async def resolve_graph_for_activity(graph_id: str) -> GraphContext:
    try:
        return await get_graph_registry().get(graph_id)
    except (GraphNotFound, GraphNotReady) as exc:
        raise ApplicationError(str(exc), type="GraphUnavailable", non_retryable=True) from exc
