"""MonitorSweepWorkflow — интеграционный тест на time-skipping сервере.

После вывода дуги `:Alert` у воркфлоу один шаг: свип. Тест держит
именно это — лишняя активность в расписании означала бы, что удалённая
дуга вернулась через воркфлоу.
"""

from __future__ import annotations

import uuid

import pytest
from temporalio import activity
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from src.analytics.contracts import WatchSweepResult
from src.watch.workflow import MonitorSweepWorkflow


@activity.defn(name="sweep_watch")
async def _sweep_stub() -> WatchSweepResult:
    return WatchSweepResult(events=5, by_kind={"new_mention": 4, "risk_rise": 1})


@pytest.mark.asyncio
async def test_monitor_sweep_workflow_returns_tally() -> None:
    try:
        env = await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter,
        )
    except Exception as exc:  # pragma: no cover — infra-dependent
        pytest.skip(f"temporal test server unavailable: {exc}")

    async with (
        env,
        Worker(
            env.client,
            task_queue="t-mon",
            workflows=[MonitorSweepWorkflow],
            activities=[_sweep_stub],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ),
    ):
        out = await env.client.execute_workflow(
            MonitorSweepWorkflow.run,
            id=f"mon-{uuid.uuid4().hex}",
            task_queue="t-mon",
        )

    assert out.watch_events == 5
    assert out.by_kind == {"new_mention": 4, "risk_rise": 1}
    assert out.error == ""
