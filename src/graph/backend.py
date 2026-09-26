"""The graph-store surface the app actually uses.

A narrow subset of LlamaIndex's ``PropertyGraphStore`` — the three methods
every graph caller funnels through.  ``src.graph.store.build_graph_store()``
returns the NebulaGraph store, which structurally satisfies this Protocol.
Keeping the seam this small keeps callers independent of the store class.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class KbGraphStore(Protocol):
    def structured_query(
        self, query: str, param_map: dict[str, Any] | None = None
    ) -> list[dict]: ...

    def upsert_nodes(self, nodes: list[Any]) -> None: ...

    def upsert_relations(self, relations: list[Any]) -> None: ...
