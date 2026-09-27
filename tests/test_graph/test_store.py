"""Graph-store factory: NebulaGraph is the only backend."""
from __future__ import annotations


def test_build_graph_store_is_nebula(monkeypatch):
    import src.graph.nebula_store as ns
    from src.graph import store
    from src.tenancy.context import default_graph_context

    sentinel = object()
    graph = default_graph_context()
    seen = []
    monkeypatch.setattr(
        ns, "build_nebula_graph_store", lambda g: (seen.append(g), sentinel)[1]
    )
    assert store.build_graph_store(graph) is sentinel
    assert seen == [graph]


def test_settings_have_no_neo4j_or_graph_section():
    from src.config import settings

    assert not hasattr(settings, "neo4j")
    assert not hasattr(settings, "graph")
