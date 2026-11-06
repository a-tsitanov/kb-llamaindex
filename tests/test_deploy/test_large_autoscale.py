import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def controller(monkeypatch):
    monkeypatch.setenv("LITELLM_MASTER_KEY", "test-only")
    path = Path(__file__).parents[2] / "deploy/offline/llm-large-autoscale/autoscale.py"
    spec = importlib.util.spec_from_file_location("large_autoscale", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reduces_under_pressure_and_recovers_gradually(controller):
    assert controller.next_cap(12, 2, 0) == 9
    assert controller.next_cap(9, 0, 4) == 10
    assert controller.next_cap(2, 2, 0) == 2
    assert controller.next_cap(12, 0, 4) == 12
    assert controller.next_cap(1, 0, 4) == 2
    assert controller.next_cap(1, 2, 0) == 1


def test_incomplete_metrics_fail_closed(controller, monkeypatch):
    monkeypatch.setattr(controller, "_http", lambda *args: b'vllm:num_requests_running{x="a"} 1\n')
    with pytest.raises(ValueError, match="incomplete"):
        controller.read_vllm()


def test_metrics_across_engines(controller, monkeypatch):
    payload = b'''vllm:num_requests_running{x="a"} 2
vllm:num_requests_running{x="b"} 3
vllm:num_requests_waiting{x="a"} 1
vllm:kv_cache_usage_perc{x="a"} 0.5
vllm:kv_cache_usage_perc{x="b"} 0.7
'''
    monkeypatch.setattr(controller, "_http", lambda *args: payload)
    assert controller.read_vllm() == (5, 1, 0.7)
