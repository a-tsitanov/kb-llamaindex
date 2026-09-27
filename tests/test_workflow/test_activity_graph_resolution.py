"""Task 8: storage activities resolve their GraphContext from the input's
``graph_id`` (via the registry), and an unavailable graph fails the activity
non-retryably — even inside activities that are otherwise fail-soft."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from temporalio.exceptions import ApplicationError

import src.tenancy.activity as ta
from src.analytics.contracts import CentralityIn, DeliverIn, MonitorIn
from src.tenancy.registry import GraphNotFound
from src.workflow.contracts import DocumentsForCommunitiesParams, MarkDirtyIn


class _MissingRegistry:
    async def get(self, gid):
        raise GraphNotFound(gid)


@pytest.fixture
def missing_graph(monkeypatch):
    monkeypatch.setattr(ta, "get_graph_registry", lambda: _MissingRegistry())


async def test_mark_entities_dirty_uses_input_graph(monkeypatch):
    import src.workflow.activities.mark_dirty as md

    seen = []
    monkeypatch.setattr(md.settings.wiki, "enabled", True, raising=False)
    monkeypatch.setattr(md, "build_graph_store", lambda g: seen.append(g) or object())
    monkeypatch.setattr(md, "mark_dirty", lambda store, names: None)
    monkeypatch.setattr(md, "activity", MagicMock())
    n = await md.mark_entities_dirty(MarkDirtyIn(entity_names=["A"], graph_id="acme"))
    assert n == 1
    assert [g.id for g in seen] == ["acme"]


async def test_documents_for_communities_uses_input_graph(monkeypatch):
    import src.workflow.search.activities.documents as mod

    seen = []
    monkeypatch.setattr(mod, "activity", MagicMock())
    monkeypatch.setattr(mod, "_get_store", lambda g: seen.append(g))
    await mod.documents_for_communities(
        DocumentsForCommunitiesParams(community_ids=["1"], graph_id="acme"))
    assert [g.id for g in seen] == ["acme"]


async def test_detect_alerts_unavailable_graph_is_not_swallowed(missing_graph):
    from src.workflow.monitor import activities as ma

    with pytest.raises(ApplicationError) as ei:
        await ma.detect_alerts(MonitorIn(graph_id="gone"))
    assert ei.value.non_retryable is True
    assert ei.value.type == "GraphUnavailable"


async def test_deliver_alerts_unavailable_graph_is_not_swallowed(missing_graph, monkeypatch):
    from src.workflow.monitor import activities as ma

    monkeypatch.setattr(ma.settings.monitor, "webhook_url", "http://hook", raising=False)
    with pytest.raises(ApplicationError) as ei:
        await ma.deliver_alerts(DeliverIn(graph_id="gone"))
    assert ei.value.non_retryable is True


async def test_materialize_centrality_unavailable_graph_is_not_swallowed(missing_graph):
    from src.workflow.analytics import materialize_activities as mz

    with pytest.raises(ApplicationError) as ei:
        await mz.materialize_centrality(CentralityIn(graph_id="gone"))
    assert ei.value.non_retryable is True


async def test_wiki_select_dirty_resolves_the_default_graph(monkeypatch):
    import src.graph.store as gs
    import src.graph.wiki_dirty as wd
    from src.workflow.wiki import wiki_sweep

    seen_ids = []

    class _Reg:
        async def get(self, gid):
            seen_ids.append(gid)
            from src.tenancy.context import default_graph_context
            return default_graph_context()

    monkeypatch.setattr(ta, "get_graph_registry", lambda: _Reg())
    monkeypatch.setattr(gs, "build_graph_store", lambda g: g)
    monkeypatch.setattr(wd, "select_dirty", lambda store, limit: [store.id])
    assert await wiki_sweep.select_dirty_entities(5) == ["default"]
    assert seen_ids == ["default"]
