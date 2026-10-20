"""Tests that the monitor group is registered in the worker module.

Module-level inspection only — no Temporal server connection, no network.
"""

from __future__ import annotations

from src.watch.activities import MONITOR_ACTIVITIES, detect_alerts
from src.watch.workflow import MonitorSweepWorkflow
from src.workflow import worker as w


def test_monitor_in_worker_groups():
    assert "monitor" in w.WORKER_GROUPS


def test_detect_alerts_in_monitor_activities():
    assert detect_alerts in MONITOR_ACTIVITIES


def test_monitor_sweep_workflow_importable():
    assert MonitorSweepWorkflow is not None


def test_sweep_watch_in_monitor_activities():
    from src.watch.activities import sweep_watch

    assert sweep_watch in MONITOR_ACTIVITIES


def test_sweep_runs_every_five_minutes_by_default():
    from src.config import MonitorSettings

    assert MonitorSettings.model_fields["sweep_interval_minutes"].default == 5
