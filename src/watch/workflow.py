"""Свип наблюдения — одноразовый ``MonitorSweepWorkflow``.

Имя класса сохранено намеренно: по нему работает Temporal-расписание
(``scripts/setup_monitor_schedule.py``), и переименование означало бы
ручную пересборку расписания на каждом стенде.

Содержимое после вывода дуги `:Alert` — один шаг: свип журналов и роста
риска.  Доставка добавляется отдельной активностью (S4 плана P2).
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from src.analytics.contracts import SweepResult, WatchSweepResult

_RETRY = RetryPolicy(
    maximum_attempts=2,
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=30),
)


@workflow.defn
class MonitorSweepWorkflow:
    """Один проход наблюдения: журналы и рост риска → ``watch_event``."""

    @workflow.run
    async def run(self) -> SweepResult:
        watch = await workflow.execute_activity(
            "sweep_watch",
            result_type=WatchSweepResult,
            start_to_close_timeout=timedelta(minutes=4),
            schedule_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=_RETRY,
        )
        return SweepResult(
            watch_events=watch.events,
            by_kind=dict(watch.by_kind),
            error=watch.error,
        )
