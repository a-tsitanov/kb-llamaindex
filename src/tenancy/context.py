"""Graph identity: the id, its physical storage names, and id validation.

A ``GraphContext`` is the only thing storage code needs to know which graph
it is touching.  Physical names live here (and in the registry row), never in
Temporal payloads."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.config import settings

DEFAULT_GRAPH_ID = "default"
# Tenant every pre-tenancy graph and key is inherited into (spec A7).
DEFAULT_TENANT_ID = "default"
_SLUG = re.compile(r"^[a-z][a-z0-9_]{1,30}$")


class InvalidGraphId(ValueError):
    """Graph id is not a valid slug (it is interpolated into DDL)."""


def validate_graph_id(graph_id: str) -> str:
    if not isinstance(graph_id, str) or not _SLUG.fullmatch(graph_id):
        raise InvalidGraphId(f"invalid graph id: {graph_id!r}")
    return graph_id


@dataclass(frozen=True)
class GraphContext:
    id: str
    nebula_space: str
    nebula_partition_num: int
    chunks_collection: str
    er_vec_collection: str
    report_vec_collection: str
    pg_schema: str
    minio_prefix: str
    # Bumped each time a graph id is (re)created, so per-process caches
    # never hand a re-created graph the dropped one's sessions/handles.
    generation: int = 0
    # Owning tenant, carried from the registry row to the enforcement seams
    # so authorization never needs a second trip to the registry.
    tenant_id: str = DEFAULT_TENANT_ID

    @property
    def is_default(self) -> bool:
        return self.id == DEFAULT_GRAPH_ID

    @property
    def cache_key(self) -> str:
        return f"{self.id}#{self.generation}"


def default_graph_context() -> GraphContext:
    """The pre-multi-graph deployment, under its existing physical names."""
    return GraphContext(
        id=DEFAULT_GRAPH_ID,
        nebula_space="kb",
        nebula_partition_num=100,
        chunks_collection=settings.milvus.collection,
        er_vec_collection="entity_er_vec",
        report_vec_collection="community_report_vec",
        pg_schema="public",
        minio_prefix="",
    )


def transitional_default_graph() -> GraphContext:
    """Call sites not yet wired to a real graph use this; Task 12's guard
    requires zero references in src/ at the end of Plan A."""
    return default_graph_context()


def new_graph_context(
    graph_id: str,
    *,
    nebula_partition_num: int = 10,
    tenant_id: str = DEFAULT_TENANT_ID,
) -> GraphContext:
    validate_graph_id(graph_id)
    if graph_id == DEFAULT_GRAPH_ID:
        raise InvalidGraphId("'default' is reserved")
    return GraphContext(
        id=graph_id,
        nebula_space=f"g_{graph_id}",
        nebula_partition_num=nebula_partition_num,
        chunks_collection=f"g_{graph_id}_chunks",
        er_vec_collection=f"g_{graph_id}_er_vec",
        report_vec_collection=f"g_{graph_id}_report_vec",
        pg_schema=f"g_{graph_id}",
        minio_prefix=f"{graph_id}/",
        tenant_id=tenant_id,
    )


def cli_graph_context(graph_id: str) -> GraphContext:
    """``--graph`` for CLIs/scripts that may run without PG (no registry):
    ``default`` → :func:`default_graph_context`, anything else →
    :func:`new_graph_context` (validated slug, conventional physical names)."""
    if graph_id == DEFAULT_GRAPH_ID:
        return default_graph_context()
    return new_graph_context(graph_id)


def graph_scoped_id(prefix: str, graph_id: str, suffix: str) -> str:
    """Temporal workflow id; `default` keeps its pre-multi-graph id (R-A2)."""
    if graph_id == DEFAULT_GRAPH_ID:
        return f"{prefix}-{suffix}"
    return f"{prefix}-{graph_id}-{suffix}"
