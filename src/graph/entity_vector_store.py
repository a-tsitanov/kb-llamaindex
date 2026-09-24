# src/graph/entity_vector_store.py
"""Vector store for ER candidate-kNN (Milvus-backed).

The ER candidate lookup (`entity_resolution._load_candidates_via_store`)
finds the k nearest stored CANONICAL entities to each new entity.
NebulaGraph has no in-graph vector index, so it goes to a Milvus
collection, which returns candidates WITH their embeddings (ER's
`_candidate_pairs` cosines every item).
"""

from __future__ import annotations

from typing import Any, Protocol, TypedDict, runtime_checkable


class EntityCandidate(TypedDict):
    name: str
    label: str
    embedding: list[float]
    mention_count: int
    description: str


@runtime_checkable
class EntityVectorStore(Protocol):
    def knn(self, query_vec: list[float], k: int) -> list[EntityCandidate]: ...
    def upsert(self, entities: list[EntityCandidate]) -> None: ...


def build_entity_vector_store(graph_store: Any) -> EntityVectorStore:
    from src.graph.entity_vector_store_milvus import MilvusEntityVectorStore

    return MilvusEntityVectorStore()
