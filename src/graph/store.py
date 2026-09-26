"""Graph store factory — NebulaGraph is the only backend."""

from __future__ import annotations

from src.graph import nebula_store
from src.graph.nebula_store import NebulaGraphStore


def build_graph_store() -> NebulaGraphStore:
    """Return the process-global NebulaGraph store."""
    # Resolved through the module attribute (not a from-import binding) so a
    # patched ``nebula_store.build_nebula_graph_store`` is honoured.
    return nebula_store.build_nebula_graph_store()
