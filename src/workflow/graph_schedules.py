"""Temporal Schedules for nightly graph maintenance: community build and
analytics materialize. Replaces the host cron + overlap guard of
agent_v2/scripts/graph_refresh.sh with the scheduler inside Temporal.

Applied by ``scripts/setup_graph_schedules.py``.
"""

from __future__ import annotations

from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from src.analytics.contracts import MaterializeParams
from src.config import settings
from src.workflow.analytics.materialize_workflow import AnalyticsMaterializeWorkflow
from src.workflow.contracts import DetectCommunitiesParams
from src.workflow.search.community_wf import CommunityBuildWorkflow

COMMUNITY_SCHEDULE_ID = "community-build"
ANALYTICS_SCHEDULE_ID = "analytics-materialize"


def community_build_params() -> DetectCommunitiesParams:
    """Build input snapshotted from config (shared with the admin endpoint)."""
    t = settings.temporal
    return DetectCommunitiesParams(
        min_size=t.community_min_size,
        level=0,
        max_levels=settings.agent.community_max_levels,
        gamma=t.community_leiden_gamma,
        concurrency=t.community_leiden_concurrency,
    )


def _schedule(cron: str, run, arg, workflow_id: str) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            run, arg, id=workflow_id, task_queue=settings.temporal.graph_build_task_queue,
        ),
        spec=ScheduleSpec(cron_expressions=[cron]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


def graph_schedules() -> dict[str, Schedule | None]:
    """Schedule per id; ``None`` = cron unset, the schedule must not exist."""
    t = settings.temporal
    return {
        COMMUNITY_SCHEDULE_ID: _schedule(
            t.community_schedule_cron, CommunityBuildWorkflow.run, community_build_params(),
            "community-build-scheduled",
        ) if t.community_schedule_cron.strip() else None,
        ANALYTICS_SCHEDULE_ID: _schedule(
            t.analytics_schedule_cron, AnalyticsMaterializeWorkflow.run, MaterializeParams(),
            "analytics-materialize-scheduled",
        ) if t.analytics_schedule_cron.strip() else None,
    }
