"""EntityVectorStore factory: always the Milvus impl (DB-free)."""
from __future__ import annotations

import src.graph.entity_vector_store as evs
from src.tenancy.context import default_graph_context


def test_factory_returns_milvus(monkeypatch):
    # Patch the class (which the factory lazily imports) to a sentinel so
    # the factory is verified DB-free — the real MilvusEntityVectorStore
    # constructor connects a MilvusClient eagerly.
    import src.graph.entity_vector_store_milvus as evsm
    sentinel = object()
    monkeypatch.setattr(evsm, "MilvusEntityVectorStore", lambda *a, **k: sentinel)
    assert evs.build_entity_vector_store(default_graph_context()) is sentinel
