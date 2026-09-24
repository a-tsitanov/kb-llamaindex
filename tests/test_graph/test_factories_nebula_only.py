"""Every graph-ops factory returns the Nebula implementation; no Neo4j class remains."""
from __future__ import annotations

import importlib

import pytest

FACTORIES = [
    ("src.graph.analytics_graph_ops", "build_analytics_graph_ops"),
    ("src.graph.signals_graph_ops", "build_signals_graph_ops"),
    ("src.graph.er_graph_ops", "build_er_graph_ops"),
    ("src.graph.events_graph_ops", "build_events_graph_ops"),
    ("src.graph.events_llm_graph_ops", "build_events_llm_graph_ops"),
    ("src.graph.wiki_graph_ops", "build_wiki_graph_ops"),
    ("src.graph.communities_graph_ops", "build_communities_graph_ops"),
    ("src.graph.domain_graph_ops", "build_domain_graph_ops"),
    ("src.graph.dynamics_graph_ops", "build_dynamics_graph_ops"),
    ("src.graph.aggregations_graph_ops", "build_aggregations_graph_ops"),
    ("src.graph.rollups_graph_ops", "build_rollups_graph_ops"),
    ("src.graph.centrality_graph_ops", "build_centrality_graph_ops"),
    ("src.graph.quality_graph_ops", "build_quality_graph_ops"),
    ("src.graph.graph_edge_export", "build_graph_edge_export"),
    ("src.graph.community_read", "build_community_read"),
    ("src.graph.community_writeback", "build_community_writeback"),
    ("src.graph.community_summarize", "build_community_summarize"),
    ("src.graph.alert_store", "build_alert_store"),
]


@pytest.mark.parametrize(("mod", "fn"), FACTORIES)
def test_factory_returns_nebula_impl(mod, fn, monkeypatch):
    from src.config import settings

    # build_er_graph_ops wraps the graph ops in a Postgres verdict-cache
    # composite by default; select the graph-only path so the returned
    # object IS the graph-ops class (the composite is checked separately).
    monkeypatch.setattr(settings.agent, "er_verdict_cache_backend", "graph")
    m = importlib.import_module(mod)
    obj = getattr(m, fn)(object())
    assert type(obj).__name__.startswith("Nebula"), type(obj).__name__


@pytest.mark.parametrize(("mod", "_fn"), FACTORIES)
def test_no_neo4j_class_left(mod, _fn):
    m = importlib.import_module(mod)
    assert not [n for n in vars(m) if n.startswith("Neo4j")]


def test_vector_stores_are_milvus(monkeypatch):
    from src.graph import community_vector_store_milvus as cm
    from src.graph import entity_vector_store_milvus as em
    from src.graph.community_vector_store import build_community_report_vector_store
    from src.graph.entity_vector_store import build_entity_vector_store

    monkeypatch.setattr(cm.MilvusCommunityReportVectorStore, "__init__", lambda self: None)
    monkeypatch.setattr(em.MilvusEntityVectorStore, "__init__", lambda self: None)
    assert type(build_community_report_vector_store(object())).__name__ == "MilvusCommunityReportVectorStore"
    assert type(build_entity_vector_store(object())).__name__ == "MilvusEntityVectorStore"


def test_er_composite_wraps_nebula_graph_ops(monkeypatch):
    from src.config import settings
    from src.graph import er_graph_ops as eg

    monkeypatch.setattr(settings.agent, "er_verdict_cache_backend", "postgres")
    ops = eg.build_er_graph_ops(object())
    assert isinstance(ops, eg._CompositeERGraphOps)
    assert isinstance(ops._cache, eg.PostgresERVerdictCache)
    assert isinstance(ops._graph, eg.NebulaERGraphOps)
