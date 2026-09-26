"""Dirty-flag bookkeeping for the wiki editor (Nebula ``Entity`` props).

Routes through the ``WikiGraphOps`` seam (``src/graph/wiki_graph_ops.py``),
which issues nGQL against the Nebula store."""
from __future__ import annotations

from src.graph.wiki_graph_ops import build_wiki_graph_ops


def mark_dirty(store, names: list[str]) -> None:
    build_wiki_graph_ops(store).mark_dirty(names)


def select_dirty(store, limit: int) -> list[str]:
    return build_wiki_graph_ops(store).select_dirty(limit)


def clear_dirty(store, name: str, digest: str) -> None:
    build_wiki_graph_ops(store).clear_dirty(name, digest)
