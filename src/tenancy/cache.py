"""Per-graph cache keys that survive a graph id being deleted and re-created."""

from __future__ import annotations

from src.tenancy.context import GraphContext


def evict_stale_generations[V](cache: dict[str, V], graph: GraphContext) -> list[V]:
    """Remove entries of older generations of ``graph.id`` (keys
    ``"<id>#<gen>"``) and return them so the caller can close resources."""
    prefix = f"{graph.id}#"
    stale = [k for k in cache if k.startswith(prefix) and k != graph.cache_key]
    return [cache.pop(k) for k in stale]
