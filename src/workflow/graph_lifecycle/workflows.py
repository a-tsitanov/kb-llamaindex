"""Graph provisioning / deletion workflows (spec §3).

Provision: nebula space → milvus collections → PG schema → `ready`;
any step exhausting its retries → `failed` (+ error).  A repeated
`POST /admin/graphs` on a `failed` graph starts this again (steps are
idempotent).  Delete: wait for every process to see `deleting`, terminate
the graph's in-flight ingests, let their activities drain, drop storage,
delete the registry row; a failure leaves the row `failed` for a retry."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from src.config import settings
    from src.workflow.graph_lifecycle.contracts import (
        DeleteGraphIn,
        GraphLifecycleIn,
        LifecycleResult,
        SetStatusIn,
    )

_RETRY = RetryPolicy(
    maximum_attempts=5, initial_interval=timedelta(seconds=2), maximum_interval=timedelta(seconds=30),
)
_STEP = timedelta(minutes=5)
# Only these steps heartbeat; the others are bounded by start_to_close alone
# (a heartbeat timeout on a silent to_thread body would kill healthy work).
_HEARTBEAT = timedelta(minutes=2)
_HEARTBEATING = frozenset({"terminate_graph_ingests", "purge_minio"})
# purge_minio heartbeats per batch, so a large prefix may take longer.
_STEP_OVERRIDES = {"purge_minio": timedelta(hours=2)}


def provision_workflow_id(graph_id: str) -> str:
    return f"lifecycle-provision-{graph_id}"


def delete_workflow_id(graph_id: str) -> str:
    return f"lifecycle-delete-{graph_id}"


async def _step(name: str, arg) -> None:
    # Own activity queue: lifecycle steps must not wait behind long community
    # builds / analytics materializations for kb-graph-build's slots.
    await workflow.execute_activity(
        name, arg,
        task_queue=settings.temporal.graph_lifecycle_task_queue,
        start_to_close_timeout=_STEP_OVERRIDES.get(name, _STEP),
        heartbeat_timeout=_HEARTBEAT if name in _HEARTBEATING else None,
        retry_policy=_RETRY,
    )


def _cause(exc: ActivityError) -> str:
    return str(exc.cause or exc)


@workflow.defn
class ProvisionGraphWorkflow:
    @workflow.run
    async def run(self, inp: GraphLifecycleIn) -> LifecycleResult:
        try:
            for name in ("provision_nebula", "provision_milvus", "provision_pg"):
                await _step(name, inp)
        except ActivityError as exc:
            err = _cause(exc)
            await _step("set_graph_status", SetStatusIn(
                graph_id=inp.graph_id, status="failed", error=err, expect="provisioning",
            ))
            return LifecycleResult(graph_id=inp.graph_id, status="failed", error=err)
        # Conditional: never re-publish a row a concurrent delete already took.
        await _step("set_graph_status", SetStatusIn(
            graph_id=inp.graph_id, status="ready", expect="provisioning",
        ))
        return LifecycleResult(graph_id=inp.graph_id, status="ready")


@workflow.defn
class DeleteGraphWorkflow:
    @workflow.run
    async def run(self, inp: DeleteGraphIn) -> LifecycleResult:
        gid = GraphLifecycleIn(graph_id=inp.graph_id)
        await workflow.sleep(timedelta(seconds=inp.registry_settle_s))
        try:
            await _step("terminate_graph_ingests", gid)
            await workflow.sleep(timedelta(seconds=inp.drain_grace_s))
            for name in ("drop_nebula", "drop_milvus", "drop_pg", "purge_minio"):
                await _step(name, gid)
        except ActivityError as exc:
            err = _cause(exc)
            await _step("set_graph_status", SetStatusIn(
                graph_id=inp.graph_id, status="failed", error=err, expect="deleting",
            ))
            return LifecycleResult(graph_id=inp.graph_id, status="failed", error=err)
        await _step("delete_graph_row", gid)
        return LifecycleResult(graph_id=inp.graph_id, status="deleted")
