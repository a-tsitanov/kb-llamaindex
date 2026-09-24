"""CommunityReportVectorStore factory: always the Milvus impl (DB-free)."""
from __future__ import annotations

import src.graph.community_vector_store as cvs


def test_factory_returns_milvus(monkeypatch):
    # Patch the class (which the factory lazily imports) to a sentinel so
    # the factory is verified DB-free — the real
    # MilvusCommunityReportVectorStore constructor connects a MilvusClient
    # eagerly.
    import src.graph.community_vector_store_milvus as cvsm
    sentinel = object()
    monkeypatch.setattr(cvsm, "MilvusCommunityReportVectorStore", lambda *a, **k: sentinel)
    assert cvs.build_community_report_vector_store(object()) is sentinel
