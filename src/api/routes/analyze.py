"""`POST /api/v1/analyze` — plan → compute → synthesize analytical Q&A."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from temporalio.common import WorkflowIDReusePolicy

from src.analytics.contracts import AnalyzeParams
from src.api.graph_dep import resolve_graph
from src.config import settings
from src.models.analyze import AnalyzeRequest, AnalyzeResponse
from src.tenancy.context import GraphContext, graph_scoped_id
from src.workflow.analytics.workflow import AnalyticalQueryWorkflow
from src.workflow.client import get_temporal_client

router = APIRouter(tags=["analytics"])


def _to_params(req: AnalyzeRequest, *, graph_id: str) -> AnalyzeParams:
    """Map AnalyzeRequest → AnalyzeParams."""
    # request-level date filtering deferred (no Wave-0 primitive consumes request bounds; planner sets per-primitive dates).
    return AnalyzeParams(query=req.query, top_n=req.top_n, graph_id=graph_id)


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="Plan→compute→synthesize analytical Q&A over the knowledge graph",
)
async def analyze(
    req: AnalyzeRequest, graph: GraphContext = Depends(resolve_graph),
) -> AnalyzeResponse:
    request_id = uuid.uuid4().hex
    try:
        client = await get_temporal_client()
        params = _to_params(req, graph_id=graph.id)
        handle = await client.start_workflow(
            AnalyticalQueryWorkflow.run,
            params,
            id=graph_scoped_id("analyze", params.graph_id, request_id),
            task_queue=settings.temporal.search_task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )
        outcome = await handle.result()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analyze failed: {exc}",
        ) from exc
    return AnalyzeResponse(
        query=outcome.query,
        answer=outcome.answer,
        provenance=outcome.provenance,
        latency_ms=outcome.latency_ms,
    )
