import uuid
from datetime import timedelta

import pytest
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from src.workflow.graph_lifecycle.contracts import DeleteGraphIn, GraphLifecycleIn
from src.workflow.graph_lifecycle.workflows import (
    DeleteGraphWorkflow,
    ProvisionGraphWorkflow,
    delete_workflow_id,
    provision_workflow_id,
)

LOG: list = []
INFO: dict = {}  # activity name -> (task_queue, heartbeat_timeout, start_to_close, expect)


@pytest.fixture(autouse=True)
def _lifecycle_queue(monkeypatch):
    # Lifecycle steps are pinned to graph_lifecycle_task_queue; serve it here.
    # Patch the settings object the workflow module holds: other tests
    # importlib.reload(src.config), which rebinds src.config.settings, so
    # patching the module-level name would miss and the steps would queue
    # on a real name nobody polls (test hangs forever).
    from src.workflow.graph_lifecycle import workflows as wf_mod

    monkeypatch.setattr(wf_mod.settings.temporal, "graph_lifecycle_task_queue", "t-life")


def _stub(name, fail=False):
    @activity.defn(name=name)
    async def _a(inp):
        # untyped param: the pydantic converter hands the stub a plain dict
        LOG.append((name, inp.get("status") if isinstance(inp, dict) else None))
        info = activity.info()
        INFO[name] = (info.task_queue, info.heartbeat_timeout, info.start_to_close_timeout,
                      inp.get("expect") if isinstance(inp, dict) else None)
        if fail:
            raise ApplicationError(f"{name} broke", type="ProvisionIncomplete", non_retryable=True)
        return 0
    return _a


def _acts(fail_step=None):
    names = ["provision_nebula", "provision_milvus", "provision_pg", "set_graph_status",
             "terminate_graph_ingests", "drop_nebula", "drop_milvus", "drop_pg",
             "purge_minio", "delete_graph_row"]
    return [_stub(n, fail=(n == fail_step)) for n in names]


async def _run(wf, arg, acts):
    try:
        env = await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"temporal test server unavailable: {exc}")
    async with env, Worker(env.client, task_queue="t-life", workflows=[wf], activities=acts,
                           workflow_runner=UnsandboxedWorkflowRunner()):
        return await env.client.execute_workflow(
            wf.run, arg, id=f"t-{uuid.uuid4().hex}", task_queue="t-life",
            # fail fast instead of hanging if a step lands on an unpolled queue
            execution_timeout=timedelta(hours=1),
        )


def test_workflow_ids():
    assert provision_workflow_id("acme") == "lifecycle-provision-acme"
    assert delete_workflow_id("acme") == "lifecycle-delete-acme"


async def test_provision_happy_path_marks_ready():
    LOG.clear()
    out = await _run(ProvisionGraphWorkflow, GraphLifecycleIn(graph_id="acme"), _acts())
    assert out.status == "ready"
    assert [n for n, _ in LOG] == ["provision_nebula", "provision_milvus", "provision_pg",
                                   "set_graph_status"]
    assert LOG[-1] == ("set_graph_status", "ready")


async def test_provision_failure_marks_failed():
    LOG.clear()
    out = await _run(ProvisionGraphWorkflow, GraphLifecycleIn(graph_id="acme"),
                     _acts(fail_step="provision_milvus"))
    assert out.status == "failed" and "provision_milvus broke" in out.error
    assert LOG[-1] == ("set_graph_status", "failed")
    assert "provision_pg" not in [n for n, _ in LOG]


async def test_delete_order():
    LOG.clear()
    out = await _run(DeleteGraphWorkflow, DeleteGraphIn(graph_id="acme"), _acts())
    assert out.status == "deleted"
    assert [n for n, _ in LOG] == ["terminate_graph_ingests", "drop_nebula", "drop_milvus",
                                   "drop_pg", "purge_minio", "delete_graph_row"]


async def test_delete_failure_marks_failed_and_keeps_row():
    LOG.clear()
    out = await _run(DeleteGraphWorkflow, DeleteGraphIn(graph_id="acme"), _acts(fail_step="drop_pg"))
    assert out.status == "failed"
    assert ("set_graph_status", "failed") in LOG
    assert "delete_graph_row" not in [n for n, _ in LOG]


def test_registered_on_graph_build_pool():
    from src.workflow import worker
    from src.workflow.graph_lifecycle.activities import LIFECYCLE_ACTIVITIES

    wfs = worker.workflows_for_group("graph_build")
    assert ProvisionGraphWorkflow in wfs and DeleteGraphWorkflow in wfs
    assert all(a in worker.GRAPH_BUILD_POOL_ACTIVITIES for a in LIFECYCLE_ACTIVITIES)


async def test_steps_run_on_lifecycle_queue_and_only_heartbeaters_get_heartbeat_timeout():
    from datetime import timedelta

    LOG.clear(), INFO.clear()
    await _run(DeleteGraphWorkflow, DeleteGraphIn(graph_id="acme", registry_settle_s=0,
                                                  drain_grace_s=0), _acts())
    assert {q for q, *_ in INFO.values()} == {"t-life"}
    # silent to_thread bodies must not be killed by a heartbeat timeout
    for name in ("drop_nebula", "drop_milvus", "drop_pg", "delete_graph_row"):
        assert not INFO[name][1], name
    assert INFO["terminate_graph_ingests"][1] == timedelta(minutes=2)
    assert INFO["purge_minio"][1] == timedelta(minutes=2)
    assert INFO["purge_minio"][2] > timedelta(minutes=5)


async def test_status_writes_are_conditional():
    INFO.clear()
    await _run(ProvisionGraphWorkflow, GraphLifecycleIn(graph_id="acme"), _acts())
    assert INFO["set_graph_status"][3] == "provisioning"  # never overwrite `deleting` with ready
    INFO.clear()
    await _run(DeleteGraphWorkflow, DeleteGraphIn(graph_id="acme"), _acts(fail_step="drop_pg"))
    assert INFO["set_graph_status"][3] == "deleting"


def test_lifecycle_activities_have_own_worker():
    import inspect

    from src.workflow import worker

    src = inspect.getsource(worker._side_workers)
    assert "graph_lifecycle_task_queue" in src and "LIFECYCLE_ACTIVITIES" in src
    assert "graph_lifecycle_activity_concurrency" in src
    assert "_side_workers(client, group)" in inspect.getsource(worker._run_one)
