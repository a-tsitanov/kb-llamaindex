"""Свип наблюдения — одноразовый ``MonitorSweepWorkflow``.

Имя класса сохранено намеренно: по нему работает Temporal-расписание
(``scripts/setup_monitor_schedule.py``), и переименование означало бы
ручную пересборку расписания на каждом стенде.

Два шага: свип (журналы и рост риска → события) и доставка
(события → адресаты подписок).  Порядок обязателен — рассылка должна
видеть события этого прохода, иначе отставала бы на период расписания.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from src.analytics.contracts import (
        SweepResult,
        WatchDeliverResult,
        WatchSweepResult,
    )

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
        # Доставка — отдельная активность и идёт ПОСЛЕ свипа: события
        # этого прохода должны успеть появиться, иначе рассылка всегда
        # отставала бы на один период расписания.
        deliver = await workflow.execute_activity(
            "deliver_watch",
            result_type=WatchDeliverResult,
            # Последовательная рассылка: в пределе deliver_batch ×
            # webhook_timeout_s (по умолчанию 100 × 5 с), плюс запас.
            start_to_close_timeout=timedelta(minutes=12),
            schedule_to_close_timeout=timedelta(minutes=25),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=_RETRY,
        )
        return SweepResult(
            watch_events=watch.events,
            by_kind=dict(watch.by_kind),
            delivered=deliver.delivered,
            failed=deliver.failed,
            suppressed=deliver.suppressed,
            refused=deliver.refused,
            error="; ".join(e for e in (watch.error, deliver.error) if e),
        )
