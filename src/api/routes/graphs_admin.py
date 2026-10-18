"""Graph lifecycle admin API (spec §3): explicit create / list / patch /
delete.  Graphs are never created implicitly (amendment 2026-10-18).

Every endpoint needs the ``admin`` action and acts only on graphs of the
key's own tenant.  Repository filters come from :func:`authz.tenant_filter`
and never from ``key.tenant_id`` directly, so ``AUTHZ_MODE=off`` really is
an emergency lever: with it, nothing here filters or refuses."""

from __future__ import annotations

from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from pydantic import BaseModel, Field
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from src.api.auth import require_api_key
from src.api.graph_dep import GRAPH_NOT_FOUND_DETAIL
from src.config import settings
from src.tenancy import authz, graph_repo
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.authz import Action
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

# One body for every conflict on POST: "ready", "provisioning", "deleting"
# and "someone else holds this slug" must be indistinguishable, or the body
# of a conflict on one's OWN graph becomes the oracle that tells the two
# apart.  The real status goes to the log instead.
GRAPH_UNAVAILABLE_DETAIL = "graph id is not available"


class CreateGraphBody(BaseModel):
    id: str
    owner: str = Field(min_length=1)
    nebula_partition_num: int = Field(default=10, ge=1, le=1000)


class PatchGraphBody(BaseModel):
    owner: str | None = Field(default=None, min_length=1)
    max_inflight: int | None = Field(default=None, ge=1)


def _authorize(key: ApiKeyRecord, graph_id: str, graph_tenant: str | None) -> None:
    """Admin decision for one graph; refusals follow spec §5.

    ``unknown``/``tenant`` answer 404 with the same body a missing graph
    gets: a 403 here would confirm that the graph exists."""
    decision = authz.guard(key, graph_id, graph_tenant, Action.ADMIN)
    if decision.allowed:
        return
    if decision.reason in ("scope", "graph"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{Action.ADMIN} not allowed for this key")
    raise HTTPException(status.HTTP_404_NOT_FOUND, GRAPH_NOT_FOUND_DETAIL)


def _authorize_collection(key: ApiKeyRecord) -> None:
    """Scope-only decision for ``GET ""`` — the one route with no graph.

    A narrowing to graph ids has nothing to apply to on a collection, so it
    is dropped here; the rows themselves are cut down by tenant below.  The
    check still goes through ``guard`` so that ``off`` disables it too."""
    _authorize(replace(key, graph_ids=None), "*", key.tenant_id)


def _row_tenant(row: dict | None) -> str | None:
    """Owning tenant of a registry row, fail-CLOSED.

    ``.get``, not ``row["tenant_id"]``: a row from before the migration
    would otherwise raise KeyError and answer 500.  None means "unknown",
    which :func:`_authorize` turns into a 404."""
    return row.get("tenant_id") if row else None


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
async def create_graph(body: CreateGraphBody, key: ApiKeyRecord = Depends(require_api_key)) -> dict:
    # The graph does not exist yet, so it is born in the key's own tenant —
    # which is also why the tenant is never taken from the body.
    _authorize(key, body.id, key.tenant_id)
    try:
        outcome = await graph_repo.create_or_resume(
            body.id,
            body.owner,
            body.nebula_partition_num,
            tenant_id=key.tenant_id,
            tenant_filter=authz.tenant_filter(key),
        )
    except InvalidGraphId as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    if outcome.kind == "conflict":
        logger.info(
            f"graph create conflict id={body.id} status={outcome.status} "
            f"key_owner={key.owner} tenant={key.tenant_id}"
        )
        raise HTTPException(status.HTTP_409_CONFLICT, GRAPH_UNAVAILABLE_DETAIL)
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
async def list_graphs(key: ApiKeyRecord = Depends(require_api_key)) -> list[dict]:
    _authorize_collection(key)
    rows = await graph_repo.list_rows(tenant_id=authz.tenant_filter(key))
    if settings.authz.mode == "log":
        # Unfiltered on purpose in `log`; one summary line says what
        # `enforce` would have hidden.  Reviewed during the dark launch.
        foreign = sum(1 for r in rows if r.get("tenant_id") != key.tenant_id)
        if foreign:
            logger.warning(
                f"authz would-deny list key_owner={key.owner} tenant={key.tenant_id} "
                f"foreign_rows={foreign}"
            )
    return rows


@router.get("/{graph_id}")
async def get_graph(graph_id: str, key: ApiKeyRecord = Depends(require_api_key)) -> dict:
    row = await graph_repo.get_row(graph_id)
    _authorize(key, graph_id, _row_tenant(row))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, GRAPH_NOT_FOUND_DETAIL)
    return row


@router.patch("/{graph_id}")
async def patch_graph(
    graph_id: str, body: PatchGraphBody, key: ApiKeyRecord = Depends(require_api_key)
) -> dict:
    _authorize(key, graph_id, _row_tenant(await graph_repo.get_row(graph_id)))
    row = await graph_repo.patch_row(
        graph_id,
        owner=body.owner,
        max_inflight=body.max_inflight,
        tenant_id=authz.tenant_filter(key),
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, GRAPH_NOT_FOUND_DETAIL)
    return row


@router.delete("/{graph_id}", status_code=status.HTTP_202_ACCEPTED)
async def delete_graph(
    graph_id: str, confirm: str = Query(...), key: ApiKeyRecord = Depends(require_api_key)
) -> dict:
    if graph_id == DEFAULT_GRAPH_ID:
        raise HTTPException(status.HTTP_409_CONFLICT, "the default graph cannot be deleted")
    if confirm != graph_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "confirm must equal the graph id")
    # Authorize BEFORE mark_deleting: a foreign graph must not be moved to
    # `deleting` and then refused.
    _authorize(key, graph_id, _row_tenant(await graph_repo.get_row(graph_id)))
    # The provisioning guard lives inside mark_deleting (atomic with the write).
    prev = await graph_repo.mark_deleting(graph_id, tenant_id=authz.tenant_filter(key))
    if prev is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, GRAPH_NOT_FOUND_DETAIL)
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
