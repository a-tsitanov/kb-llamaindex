"""EntityVectorStore factory: always the Milvus impl (DB-free)."""
from __future__ import annotations

import src.graph.entity_vector_store as evs


def test_factory_returns_milvus(monkeypatch):
    # Patch the class (which the factory lazily imports) to a sentinel so
    # the factory is verified DB-free — the real MilvusEntityVectorStore
    # constructor connects a MilvusClient eagerly.
    import src.graph.entity_vector_store_milvus as evsm
    sentinel = object()
    monkeypatch.setattr(evsm, "MilvusEntityVectorStore", lambda *a, **k: sentinel)
    assert evs.build_entity_vector_store(object()) is sentinel
