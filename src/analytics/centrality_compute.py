"""In-worker centrality (igraph) over the exported __Entity__ graph.

Mirrors src/graph/community_leiden.py: stream the graph out via the
GraphEdgeExport seam, build a weighted undirected igraph, and compute the
centrality metric in this worker process — off Neo4j's GDS heap, and usable
under nebula which has no in-graph compute. Selected when
``settings.graph.backend == "nebula"`` (see analytics/materialize.py).

Fail-open: any error → ``{}`` (the same sentinel discipline as
community_graphscope — a non-empty score dict is never mistaken for a
failure, so a fail-open never wipes existing materialized scores).
"""
from __future__ import annotations

import asyncio
import multiprocessing
from typing import Any

from loguru import logger

_METRICS = ("pagerank", "betweenness", "eigenvector")


def _compute_child(conn: Any, edges: list, names: list) -> None:
    try:
        conn.send((True, {m: compute_centrality(edges, names, m) for m in _METRICS}))
    except BaseException as exc:
        conn.send((False, f"{type(exc).__name__}: {exc}"))
    finally:
        conn.close()


async def compute_all_isolated(store: Any) -> dict[str, dict[str, float]]:
    """Export in a thread and compute in a cancellable, independent process."""
    from src.graph.community_leiden import extract_entity_edges

    edges, names = await asyncio.to_thread(extract_entity_edges, store)
    ctx = multiprocessing.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_compute_child, args=(sender, edges, names), daemon=True)
    try:
        process.start()
        sender.close()
        while True:
            if receiver.poll():
                ok, result = await asyncio.to_thread(receiver.recv)
                if not ok:
                    raise RuntimeError(f"centrality subprocess failed: {result}")
                return result
            if not process.is_alive():
                raise RuntimeError(f"centrality subprocess exited with code {process.exitcode}")
            await asyncio.sleep(0.1)
    finally:
        sender.close()
        receiver.close()
        if process.pid is not None:
            if process.is_alive():
                process.terminate()
            await asyncio.to_thread(process.join, 5)
            if process.is_alive():
                process.kill()
                await asyncio.to_thread(process.join)


def compute_centrality(
    edges: list[tuple[str, str, float]],
    node_names: list[str],
    metric: str,
) -> dict[str, float]:
    """Return ``{entity_name -> score}`` for ``metric`` over the weighted
    undirected graph. Empty graph or any error → ``{}`` (fail-open)."""
    if metric not in _METRICS:
        raise ValueError(f"unknown centrality metric: {metric!r}")
    try:
        # reuse community_leiden's exact graph-build (dedup names + endpoints,
        # weighted, simplified) so centrality and community see the same graph.
        from src.graph.community_leiden import build_graph

        g, names = build_graph(edges, node_names)
        if g.vcount() == 0:
            return {}
        weights = g.es["weight"] if "weight" in g.es.attributes() else None
        if metric == "pagerank":
            scores = g.pagerank(weights=weights, directed=False)
        elif metric == "betweenness":
            scores = g.betweenness(weights=weights, directed=False)
        else:  # eigenvector
            scores = g.eigenvector_centrality(weights=weights, directed=False)
        return {names[i]: float(scores[i]) for i in range(len(names))}
    except Exception as exc:  # fail-open, never wipe existing scores
        logger.warning("centrality_compute({m}) failed (non-fatal): {e}", m=metric, e=exc)
        return {}


def compute_all(
    store: Any, *, batch_size: int = 50_000,
) -> dict[str, dict[str, float]]:
    """Stream the graph once, compute every metric. Returns
    ``{metric -> {name -> score}}`` ({} per metric on failure)."""
    from src.graph.community_leiden import extract_entity_edges

    try:
        edges, names = extract_entity_edges(store, batch_size=batch_size)
    except Exception as exc:  # fail-open
        logger.warning("centrality_compute: edge export failed (non-fatal): {e}", e=exc)
        return {m: {} for m in _METRICS}
    return {m: compute_centrality(edges, names, m) for m in _METRICS}
