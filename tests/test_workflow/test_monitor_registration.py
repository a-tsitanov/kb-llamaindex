"""Tests that the monitor group is registered in the worker module.

Module-level inspection only — no Temporal server connection, no network.
"""

from __future__ import annotations

from src.workflow import worker as w
from src.workflow.monitor.activities import MONITOR_ACTIVITIES, detect_alerts
from src.workflow.monitor.workflow import MonitorSweepWorkflow


def test_monitor_in_worker_groups():
    assert "monitor" in w.WORKER_GROUPS


def test_detect_alerts_in_monitor_activities():
    assert detect_alerts in MONITOR_ACTIVITIES


def test_monitor_sweep_workflow_importable():
    assert MonitorSweepWorkflow is not None


def test_sweep_watch_in_monitor_activities():
    from src.workflow.monitor.activities import sweep_watch

    assert sweep_watch in MONITOR_ACTIVITIES


def test_sweep_runs_every_five_minutes_by_default():
    from src.config import MonitorSettings

    assert MonitorSettings.model_fields["sweep_interval_minutes"].default == 5


def test_watch_email_runs_in_the_monitor_group_and_is_off_by_default():
    from src.config import MonitorSettings
    from src.workflow.monitor.activities import deliver_watch_email

    assert deliver_watch_email in MONITOR_ACTIVITIES
    assert MonitorSettings.model_fields["email_enabled"].default is False


def test_every_monitor_activity_is_a_temporal_activity():
    # A plain function in the list makes the Temporal Worker refuse to start
    # ("missing attributes, was it decorated with @activity.defn?").
    import temporalio.activity

    for fn in MONITOR_ACTIVITIES:
        temporalio.activity._Definition.must_from_callable(fn)
