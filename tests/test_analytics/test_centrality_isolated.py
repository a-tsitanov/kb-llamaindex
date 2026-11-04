import asyncio
import multiprocessing

import pytest

from src.analytics.centrality_compute import compute_all_isolated
from src.graph import community_leiden


@pytest.mark.asyncio
async def test_isolated_computation_returns_scores(monkeypatch):
    monkeypatch.setattr(community_leiden, "extract_entity_edges", lambda store: (
        [("a", "b", 1.0), ("b", "c", 1.0)], ["a", "b", "c"]
    ))
    result = await compute_all_isolated(object())
    assert result["betweenness"]["b"] > result["betweenness"]["a"]
    assert set(result) == {"pagerank", "betweenness", "eigenvector"}


@pytest.mark.asyncio
async def test_cancellation_stops_computation(monkeypatch):
    names = [str(i) for i in range(15000)]
    edges = [(names[i], names[i + 1], 1.0) for i in range(len(names) - 1)]
    monkeypatch.setattr(community_leiden, "extract_entity_edges", lambda store: (edges, names))
    before = {p.pid for p in multiprocessing.active_children()}
    task = asyncio.create_task(compute_all_isolated(object()))
    for _ in range(100):
        await asyncio.sleep(0.05)
        children = [p for p in multiprocessing.active_children() if p.pid not in before]
        if children:
            break
    else:
        pytest.fail("centrality process did not start")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert all(not p.is_alive() for p in children)
