"""Graph lifecycle admin API (spec §3): explicit create / list / patch /
delete.  Graphs are never created implicitly (amendment 2026-10-18).  Any
valid API key may call these (amendment 2026-10-17)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from src.api.auth import require_api_key
from src.config import settings
from src.tenancy import graph_repo
from src.tenancy.context import DEFAULT_GRAPH_ID, InvalidGraphId
from src.workflow.client import get_temporal_client
from src.workflow.graph_lifecycle.contracts import DeleteGraphIn, GraphLifecycleIn
from src.workflow.graph_lifecycle.workflows import (
    DeleteGraphWorkflow,
    ProvisionGraphWorkflow,
    delete_workflow_id,
    provision_workflow_id,
)

router = APIRouter(prefix="/admin/graphs", tags=["admin"], dependencies=[Depends(require_api_key)])


class CreateGraphBody(BaseModel):
    id: str
    owner: str = Field(min_length=1)
    nebula_partition_num: int = Field(default=10, ge=1, le=1000)


class PatchGraphBody(BaseModel):
    owner: str | None = Field(default=None, min_length=1)
    max_inflight: int | None = Field(default=None, ge=1)


async def _start(run, arg, wid: str) -> str:
    client = await get_temporal_client()
    handle = await client.start_workflow(
        run,
        arg,
        id=wid,
        task_queue=settings.temporal.graph_build_task_queue,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    return handle.id


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_graph(body: CreateGraphBody) -> dict:
    try:
        outcome = await graph_repo.create_or_resume(body.id, body.owner, body.nebula_partition_num)
    except InvalidGraphId as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    if outcome.kind == "conflict":
        raise HTTPException(status.HTTP_409_CONFLICT, f"graph {body.id!r} is {outcome.status}")
    try:
        wid = await _start(
            ProvisionGraphWorkflow.run,
            GraphLifecycleIn(graph_id=body.id),
            provision_workflow_id(body.id),
        )
    except Exception as exc:
        await graph_repo.set_status(
            body.id, "failed", f"workflow start failed: {exc}", expect="provisioning"
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"provisioning failed to start: {exc}"
        ) from exc
    return {"id": body.id, "status": "provisioning", "workflow_id": wid}


@router.get("")
async def list_graphs() -> list[dict]:
    return await graph_repo.list_rows()


@router.get("/{graph_id}")
async def get_graph(graph_id: str) -> dict:
    row = await graph_repo.get_row(graph_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"graph {graph_id!r} not found")
    return row


@router.patch("/{graph_id}")
async def patch_graph(graph_id: str, body: PatchGraphBody) -> dict:
    row = await graph_repo.patch_row(graph_id, owner=body.owner, max_inflight=body.max_inflight)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"graph {graph_id!r} not found")
    return row


@router.delete("/{graph_id}", status_code=status.HTTP_202_ACCEPTED)
async def delete_graph(graph_id: str, confirm: str = Query(...)) -> dict:
    if graph_id == DEFAULT_GRAPH_ID:
        raise HTTPException(status.HTTP_409_CONFLICT, "the default graph cannot be deleted")
    if confirm != graph_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "confirm must equal the graph id")
    # The provisioning guard lives inside mark_deleting (atomic with the write).
    prev = await graph_repo.mark_deleting(graph_id)
    if prev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"graph {graph_id!r} not found")
    if prev == "provisioning":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"graph {graph_id!r} is provisioning; retry when ready or failed",
        )
    try:
        wid = await _start(
            DeleteGraphWorkflow.run, DeleteGraphIn(graph_id=graph_id), delete_workflow_id(graph_id)
        )
    except Exception as exc:
        await graph_repo.set_status(
            graph_id, "failed", f"delete start failed: {exc}", expect="deleting"
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"delete failed to start: {exc}"
        ) from exc
    return {"id": graph_id, "status": "deleting", "workflow_id": wid}
