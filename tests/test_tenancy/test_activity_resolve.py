import pytest
from temporalio.exceptions import ApplicationError

import src.tenancy.activity as ta
from src.tenancy.context import new_graph_context
from src.tenancy.registry import GraphNotFound, GraphNotReady


class _Reg:
    def __init__(self, result):
        self.result = result

    async def get(self, gid):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def test_resolves_ready_graph(monkeypatch):
    monkeypatch.setattr(ta, "get_graph_registry", lambda: _Reg(new_graph_context("acme")))
    assert (await ta.resolve_graph_for_activity("acme")).id == "acme"


@pytest.mark.parametrize("exc", [GraphNotFound("x"), GraphNotReady("x", "deleting")])
async def test_unavailable_graph_is_non_retryable(monkeypatch, exc):
    monkeypatch.setattr(ta, "get_graph_registry", lambda: _Reg(exc))
    with pytest.raises(ApplicationError) as ei:
        await ta.resolve_graph_for_activity("x")
    assert ei.value.non_retryable is True
    assert ei.value.type == "GraphUnavailable"
