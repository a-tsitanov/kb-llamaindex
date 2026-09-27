# src/graph/community_vector_store.py
"""Vector store for semantic community-report selection (Milvus-backed).

NebulaGraph has no in-graph vector index, so the kNN goes to a Milvus
collection. Mirrors src/graph/entity_vector_store.py (the er_vec slice)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, TypedDict, runtime_checkable

if TYPE_CHECKING:
    from src.tenancy.context import GraphContext


class CommunityRef(TypedDict):
    community_id: str
    level: int
    summary: str


class CommunityReport(TypedDict):
    community_id: str
    level: int
    summary: str
    embedding: list[float]


@runtime_checkable
class CommunityReportVectorStore(Protocol):
    def knn(self, query_vec: list[float], *, level: int, limit: int) -> list[CommunityRef]: ...
    def upsert(self, reports: list[CommunityReport]) -> None: ...


def build_community_report_vector_store(graph: GraphContext) -> CommunityReportVectorStore:
    from src.graph.community_vector_store_milvus import MilvusCommunityReportVectorStore

    return MilvusCommunityReportVectorStore(collection=graph.report_vec_collection)
