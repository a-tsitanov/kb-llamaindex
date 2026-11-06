"""Nightly graph-maintenance Temporal Schedules (community build, analytics)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from temporalio.client import ScheduleAlreadyRunningError, ScheduleOverlapPolicy, ScheduleState
from temporalio.service import RPCError, RPCStatusCode

from scripts import setup_graph_schedules as setup
from src.workflow import graph_schedules as gs


@pytest.fixture
def crons(monkeypatch):
    def _set(community="", analytics=""):
        monkeypatch.setattr(gs.settings.temporal, "community_schedule_cron", community)
        monkeypatch.setattr(gs.settings.temporal, "analytics_schedule_cron", analytics)
    return _set


def test_no_cron_no_schedule(crons):
    crons()
    assert gs.graph_schedules() == {gs.COMMUNITY_SCHEDULE_ID: None, gs.ANALYTICS_SCHEDULE_ID: None}


def test_cron_builds_skip_overlap_schedule_on_graph_build_queue(crons):
    crons(community="0 2 * * *", analytics="0 7 * * *")
    out = gs.graph_schedules()
    c, a = out[gs.COMMUNITY_SCHEDULE_ID], out[gs.ANALYTICS_SCHEDULE_ID]
    assert c.spec.cron_expressions == ["0 2 * * *"]
    assert a.spec.cron_expressions == ["0 7 * * *"]
    for s in (c, a):
        assert s.policy.overlap == ScheduleOverlapPolicy.SKIP
        assert s.action.task_queue == gs.settings.temporal.graph_build_task_queue
    assert c.action.workflow == "CommunityBuildWorkflow"
    assert a.action.workflow == "AnalyticsMaterializeWorkflow"
    assert c.action.args[0] == gs.community_build_params()


def test_community_params_follow_config(monkeypatch):
    monkeypatch.setattr(gs.settings.temporal, "community_min_size", 5)
    monkeypatch.setattr(gs.settings.temporal, "community_leiden_gamma", 1.5)
    p = gs.community_build_params()
    assert (p.min_size, p.gamma, p.level) == (5, 1.5, 0)


class _Handle:
    def __init__(self, client, sid):
        self.client, self.sid = client, sid

    async def delete(self):
        if self.sid not in self.client.existing:
            raise RPCError("not found", RPCStatusCode.NOT_FOUND, b"")
        self.client.existing.discard(self.sid)

    async def update(self, fn):
        old = SimpleNamespace(description=SimpleNamespace(schedule=SimpleNamespace(state=self.client.state)))
        self.client.updated.append((self.sid, fn(old).schedule.state))


class _Client:
    def __init__(self, existing=()):
        self.existing, self.created, self.updated = set(existing), [], []
        self.state = ScheduleState(paused=True, note="operator pause")

    def get_schedule_handle(self, sid):
        return _Handle(self, sid)

    async def create_schedule(self, sid, schedule):
        if sid in self.existing:
            raise ScheduleAlreadyRunningError()
        self.existing.add(sid)
        self.created.append(sid)


async def test_apply_creates_updates_and_deletes(crons):
    crons(community="0 2 * * *")
    client = _Client(existing={gs.ANALYTICS_SCHEDULE_ID})
    assert await setup.apply(client) == {gs.COMMUNITY_SCHEDULE_ID: "created",
                                         gs.ANALYTICS_SCHEDULE_ID: "deleted"}
    assert await setup.apply(client) == {gs.COMMUNITY_SCHEDULE_ID: "updated",
                                         gs.ANALYTICS_SCHEDULE_ID: "absent"}
    assert client.updated[0][1].paused is True
    assert client.updated[0][1].note == "operator pause"


async def test_create_failure_is_not_treated_as_existing(crons):
    crons(community="0 2 * * *")
    client = _Client()

    async def fail(*args):
        raise RuntimeError("network failure")

    client.create_schedule = fail
    with pytest.raises(RuntimeError, match="network failure"):
        await setup.apply(client)
    assert not client.updated


def test_scheduled_graph_is_default(crons):
    crons(community="0 2 * * *", analytics="0 7 * * *")
    schedules = gs.graph_schedules()
    assert schedules[gs.COMMUNITY_SCHEDULE_ID].action.args[0].graph_id == "default"
    assert schedules[gs.ANALYTICS_SCHEDULE_ID].action.args[0].graph_id == "default"
    assert gs.community_build_params("alpha").graph_id == "alpha"
