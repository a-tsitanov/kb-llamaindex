"""Graph edge EXPORT (Leiden read-phase).

``NebulaGraphEdgeExport`` implements the read in nGQL: a keyset ``LOOKUP`` for node names, then
a batched ``GO ... OVER RELATED`` edge scan keyed by VID.
"""
from __future__ import annotations

from typing import Any, Protocol


class GraphEdgeExport(Protocol):
    def stream_names(self, *, batch_size: int) -> list[str]: ...

    def stream_edges(
        self, *, batch_size: int, names: list[str] | None = None,
    ) -> list[tuple[str, str, float]]: ...


class NebulaGraphEdgeExport:
    """nGQL graph edge EXPORT. Node names via keyset ``LOOKUP``; edges via a
    batched ``GO ... OVER RELATED`` scan keyed by VID (``entity_vid``).
    Values are inline-quoted (nebula binds no params)."""

    def __init__(self, store: Any):
        self._store = store

    def _exec(self, stmt: str) -> list[dict]:
        return list(self._store.structured_query(stmt) or [])

    def stream_names(self, *, batch_size: int) -> list[str]:
        from src.graph.nebula_store import _q

        names: list[str] = []
        after = ""
        while True:
            rows = self._exec(
                f"LOOKUP ON `Entity` WHERE `Entity`.name > {_q(after)} "
                "YIELD `Entity`.name AS name | ORDER BY $-.name ASC "
                f"| LIMIT {int(batch_size)};"
            )
            if not rows:
                break
            for row in rows:
                n = row.get("name")
                if n is not None:
                    names.append(str(n))
            last_name = rows[-1].get("name")
            if last_name is None or not (str(last_name) > after):
                break
            after = str(last_name)
            if len(rows) < batch_size:
                break
        return names

    def stream_edges(
        self, *, batch_size: int, names: list[str] | None = None,
    ) -> list[tuple[str, str, float]]:
        from src.graph.nebula_store import _chunks, _q, entity_vid

        # If the caller already streamed the node names (the common case —
        # extract_entity_edges always calls stream_names first), reuse them
        # and SKIP the internal re-scan. Only fall back to our own LOOKUP
        # scan when called standalone with names=None.
        if names is None:
            names = self.stream_names(batch_size=batch_size)
        vid2name = {entity_vid(n): n for n in names}

        edges: list[tuple[str, str, float]] = []
        vids = list(vid2name)
        for chunk in _chunks(vids, batch_size):
            listed = ", ".join(_q(v) for v in chunk)
            rows = self._exec(
                f"GO FROM {listed} OVER `RELATED` YIELD "
                "src(edge) AS s, dst(edge) AS d, `RELATED`.weight AS w;"
            )
            for row in rows:
                s, d = row.get("s"), row.get("d")
                if s in vid2name and d in vid2name:
                    w = row.get("w")
                    edges.append(
                        (vid2name[s], vid2name[d], float(w if w is not None else 1.0)),
                    )
        return edges


def build_graph_edge_export(store: Any) -> GraphEdgeExport:
    return NebulaGraphEdgeExport(store)
