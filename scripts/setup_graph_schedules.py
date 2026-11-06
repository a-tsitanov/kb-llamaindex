"""Idempotently create / update / delete the Temporal Schedules for nightly
graph maintenance (community build, analytics materialize) from
TEMPORAL_COMMUNITY_SCHEDULE_CRON / TEMPORAL_ANALYTICS_SCHEDULE_CRON.
An empty cron deletes that schedule.

Run: uv run python -m scripts.setup_graph_schedules
"""

from __future__ import annotations

import asyncio
from dataclasses import replace

from loguru import logger
from temporalio.client import Client, ScheduleAlreadyRunningError, ScheduleUpdate
from temporalio.service import RPCError, RPCStatusCode

from src.workflow.client import get_temporal_client
from src.workflow.graph_schedules import graph_schedules


async def apply(client: Client) -> dict[str, str]:
    """Bring every graph schedule in line with config; returns id -> action."""
    done = {}
    for sid, schedule in graph_schedules().items():
        handle = client.get_schedule_handle(sid)
        if schedule is None:
            try:
                await handle.delete()
                done[sid] = "deleted"
            except RPCError as e:
                if e.status != RPCStatusCode.NOT_FOUND:
                    raise
                done[sid] = "absent"
            continue
        try:
            await client.create_schedule(sid, schedule)
            done[sid] = "created"
        except ScheduleAlreadyRunningError:
            await handle.update(
                lambda current, s=schedule: ScheduleUpdate(
                    schedule=replace(s, state=current.description.schedule.state),
                )
            )
            done[sid] = "updated"
    return done


async def _main() -> None:
    for sid, action in (await apply(await get_temporal_client())).items():
        logger.info("graph schedule {sid}: {action}", sid=sid, action=action)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
