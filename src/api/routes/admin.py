"""Admin operations: trigger wiki/monitor sweeps and monitor watchlist."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from temporalio.common import WorkflowIDReusePolicy

from src.api.auth import require_api_key
from src.api.graph_dep import resolve_graph_admin
from src.config import settings
from src.graph.alerts import mark_watched
from src.graph.store import build_graph_store
from src.graph.wiki_graph_ops import build_wiki_graph_ops
from src.tenancy.context import GraphContext
from src.workflow.client import get_temporal_client
from src.workflow.monitor.workflow import MonitorSweepWorkflow
from src.workflow.wiki.wiki_sweep import WikiSweepWorkflow

router = APIRouter(
    prefix="/admin/wiki", tags=["admin"], dependencies=[Depends(require_api_key)],
)


@router.post("/rebuild")
async def wiki_rebuild(
    all: bool = False, graph: GraphContext = Depends(resolve_graph_admin),
) -> dict:
    if not graph.is_default:
        # D6: the wiki is a single corpus-wide artifact of the default graph.
        raise HTTPException(
            status.HTTP_409_CONFLICT, "wiki is available only for the default graph",
        )
    if not settings.wiki.enabled:
        return {"status": "disabled"}
    if all:
        build_wiki_graph_ops(build_graph_store(graph)).mark_all_dirty()
    client = await get_temporal_client()
    handle = await client.start_workflow(
        WikiSweepWorkflow.run,
        id="wiki-sweep-manual",
        task_queue=settings.wiki.task_queue,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
    )
    return {"status": "started", "workflow_id": handle.id}


def _require_default_graph_for_monitor(graph: GraphContext) -> None:
    # R-P4: monitoring (sweep + watchlist) is default-graph-only in Plan A —
    # MonitorSweepWorkflow is zero-arg with a fixed id and sweeps `default`.
    if not graph.is_default:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "monitor is available only for the default graph",
        )


monitor_router = APIRouter(
    prefix="/admin/monitor", tags=["admin"], dependencies=[Depends(require_api_key)],
)


@monitor_router.post("/sweep")
async def monitor_sweep(graph: GraphContext = Depends(resolve_graph_admin)) -> dict:
    # MonitorSweepWorkflow is default-only in Plan A (zero-arg run, fixed id).
    _require_default_graph_for_monitor(graph)
    if not settings.monitor.enabled:
        return {"status": "disabled"}
    client = await get_temporal_client()
    handle = await client.start_workflow(
        MonitorSweepWorkflow.run,
        id="monitor-sweep-manual",
        task_queue=settings.monitor.task_queue,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
    )
    return {"status": "started", "workflow_id": handle.id}


@monitor_router.post("/watch")
async def monitor_watch(
    names: list[str], watched: bool = True,
    graph: GraphContext = Depends(resolve_graph_admin),
) -> dict:
    # Intentionally NOT gated on settings.monitor.enabled (unlike /sweep): the
    # watchlist is the input the sweep consumes, so operators pre-seed it while
    # monitoring is still dark, then flip MONITOR_ENABLED on. `names` binds to
    # the JSON body (a string array); `watched` is a query param.
    _require_default_graph_for_monitor(graph)
    mark_watched(build_graph_store(graph), names, watched)
    return {"status": "ok", "count": len(names), "watched": watched}
