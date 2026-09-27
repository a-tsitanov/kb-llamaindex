"""Read-only graph-analysis admin endpoints (Track 7b).

Thin glue over ``src.graph.analysis`` — runs igraph/nGQL analysis on the
live Nebula entity graph for operators.  Read-only, API-key gated, and
fail-soft (the analysis layer returns safe empties rather than raising),
so a query hiccup yields an empty result + a worker log, not a 500.

The graph store is built once per graph (cached by ``graph.id``) — these are low-frequency admin
calls, not the query hot path.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.auth import require_api_key
from src.config import settings
from src.graph import analysis
from src.tenancy.context import GraphContext, graph_scoped_id, transitional_default_graph

router = APIRouter(prefix="/admin/graph", tags=["admin"])


# Graph stores keyed by ``graph.id``.  ``_store`` is sync (no await between
# the lookup and the insert), so the event loop cannot interleave two builds.
_stores: dict[str, Any] = {}


def _store(graph: GraphContext) -> Any:
    store = _stores.get(graph.id)
    if store is None:
        from src.graph.store import build_graph_store

        store = _stores[graph.id] = build_graph_store(graph)
    return store


@router.post("/stats", dependencies=[Depends(require_api_key)])
async def graph_stats() -> dict:
    """Operational snapshot: entity/relationship counts, degree
    distribution, duplicate-name groups, community count.

    An unmeasurable field is `null` with the reason under `errors` — it
    is never reported as 0."""
    return await analysis.graph_stats(_store(transitional_default_graph()))


@router.post("/refresh-stats", dependencies=[Depends(require_api_key)])
async def graph_refresh_stats() -> dict:
    """Recompute Nebula's tag/edge counts (`SUBMIT JOB STATS`).

    `/admin/graph/stats` serves those counts rather than scanning — the
    scans cannot run on this space — so they are only as fresh as the
    last job. This is the refresh, wired into `scripts/graph_refresh.sh`.
    Takes about a second and does not spike memory: the work happens in
    storaged, not as a graphd query."""
    return await analysis.refresh_nebula_stats(_store(transitional_default_graph()))


@router.post("/pagerank", dependencies=[Depends(require_api_key)])
async def graph_pagerank(top_n: int = 20) -> dict:
    """Top-N most central entities by weighted PageRank."""
    return {"top": await analysis.pagerank(
        _store(transitional_default_graph()), top_n=top_n,
    )}


@router.post("/personalized-pagerank", dependencies=[Depends(require_api_key)])
async def graph_personalized_pagerank(
    seeds: list[str],
    top_n: int = 20,
) -> dict:
    """Top-N entities by PageRank biased toward the given seed entities
    (relevance/centrality *relative to* the seeds)."""
    return {
        "top": await analysis.personalized_pagerank(
            _store(transitional_default_graph()),
            seeds,
            top_n=top_n,
        )
    }


@router.post("/components", dependencies=[Depends(require_api_key)])
async def graph_components() -> dict:
    """Weakly-connected-component count + size distribution."""
    return await analysis.components(_store(transitional_default_graph()))


@router.post("/shortest-path", dependencies=[Depends(require_api_key)])
async def graph_shortest_path(
    source: str,
    target: str,
    max_hops: int = 6,
) -> dict:
    """Shortest path between two entities by exact name."""
    return await analysis.shortest_path(
        _store(transitional_default_graph()),
        source,
        target,
        max_hops=max_hops,
    )


@router.post(
    "/materialize",
    dependencies=[Depends(require_api_key)],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger offline analytics materialization (GDS centrality + link-prediction + risk)",
)
async def materialize() -> dict[str, str]:
    """Fire-and-forget: start AnalyticsMaterializeWorkflow on the graph-build queue."""
    from temporalio.common import WorkflowIDReusePolicy

    from src.analytics.contracts import MaterializeParams
    from src.workflow.analytics.materialize_workflow import AnalyticsMaterializeWorkflow
    from src.workflow.client import get_temporal_client

    request_id = uuid.uuid4().hex
    try:
        client = await get_temporal_client()
        params = MaterializeParams()
        handle = await client.start_workflow(
            AnalyticsMaterializeWorkflow.run,
            params,
            id=graph_scoped_id("analytics-materialize", params.graph_id, request_id),
            task_queue=settings.temporal.graph_build_task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
        return {"workflow_id": handle.id, "status": "started"}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"materialize failed to start: {exc}",
        ) from exc
