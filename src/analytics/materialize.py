"""Offline analytics compute + write-back into the Nebula graph.

Centrality is computed in-worker via igraph (analytics/centrality_compute.py,
off the edge-export seam) and written back with nGQL UPDATE VERTEX.
Link-prediction has no in-worker port yet — the materialize stage
(``materialize_link_prediction``) is a documented no-op (returns 0)."""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

# Allowlist of centrality metrics — validated BEFORE a metric name is inlined
# into an nGQL write as a column name.
_CENTRALITY_METRICS: frozenset[str] = frozenset({"pagerank", "betweenness", "eigenvector"})


def _run_query(store: Any, cypher: str, params: dict | None = None) -> list[dict]:
    return list(store.structured_query(cypher, param_map=params or {}))


async def write_centrality(store: Any | None, graph_name: str, metric: str) -> int:
    """Compute ``metric`` in-worker and write scores back to Entity vertices.

    ``metric`` must be one of ``{pagerank, betweenness, eigenvector}`` — validated
    against the fixed allowlist BEFORE being inlined into the write-back nGQL.
    ``graph_name`` is unused (was the GDS projection name).
    Returns the number of vertices written, or 0 on None store.
    """
    if store is None:
        return 0
    if metric not in _CENTRALITY_METRICS:
        raise ValueError(f"unknown centrality metric: {metric!r}")
    return await _write_centrality_nebula(store, metric)


# Max chars in ONE nGQL request.  Nebula rejects anything over
# `max_allowed_query_size` (default 4 MiB) with `SyntaxError: Query is too
# large` — the same cap that broke the community write-back.  Batches are
# bounded by RENDERED SIZE, not vertex count.  Module-level so tests can
# monkeypatch it small.
_MAX_STMT_CHARS = 1_000_000


def _centrality_update_stmt(vid: str, per_metric: dict[str, float]) -> str:
    """ONE ``UPDATE VERTEX`` carrying EVERY metric for this vertex.

    Metric names come from the ``_CENTRALITY_METRICS`` allowlist (validated by
    the callers below), so they are safe to inline as column names."""
    sets = ", ".join(f"{k} = {float(v)}" for k, v in per_metric.items())
    return f'UPDATE VERTEX ON `Entity` "{vid}" SET {sets};'


def _flush_centrality_batch(store: Any, stmts: list[str]) -> int:
    """Send ``stmts`` as ONE multi-statement request; on failure retry them one
    at a time.

    Batching is what removes the round-trip per vertex.  The per-statement
    fallback preserves the fail-soft contract: an ER-merged or deleted vertex
    raises ``Storage Error: Vertex or edge not found`` and must not take the
    rest of its batch down with it."""
    if not stmts:
        return 0
    try:
        store.structured_query("\n".join(stmts))
        return len(stmts)
    except Exception:
        written = 0
        for stmt in stmts:
            try:
                store.structured_query(stmt)
                written += 1
            except Exception as exc:  # one missing vertex must not stop the rest
                logger.debug("centrality write skipped: {e}", e=exc)
        return written


def _write_centrality_nebula_all_sync(store: Any, metrics: list[str]) -> int:
    """Compute EVERY metric from ONE export + ONE igraph build, write batched.

    ``compute_all`` computes all three metrics per call, so calling it once per
    metric (the old per-metric loop) recomputed betweenness — the O(V*E)
    dominant cost, measured 1877s at V=78829 against 0.8s for pagerank — once
    per metric and discarded 2/3 of each result.

    Returns the number of VERTICES written (each carries every metric), not
    metric-rows."""
    from src.analytics.centrality_compute import compute_all
    from src.graph.nebula_store import entity_vid

    all_scores = compute_all(store)
    # transpose {metric -> {name -> score}} into {name -> {metric -> score}}
    # so each vertex is touched by exactly one UPDATE.
    per_vertex: dict[str, dict[str, float]] = {}
    for metric in metrics:
        for name, score in (all_scores.get(metric) or {}).items():
            per_vertex.setdefault(name, {})[metric] = score
    if not per_vertex:
        return 0

    written = 0
    batch: list[str] = []
    used = 0
    for name, per_metric in per_vertex.items():
        stmt = _centrality_update_stmt(entity_vid(name), per_metric)
        add = len(stmt) + (1 if batch else 0)       # '\n' joiner
        if batch and used + add > _MAX_STMT_CHARS:
            written += _flush_centrality_batch(store, batch)
            batch, used, add = [], 0, len(stmt)
        batch.append(stmt)
        used += add
    return written + _flush_centrality_batch(store, batch)


async def write_centrality_all(store: Any | None, metrics: list[str]) -> int:
    """Nebula path: every metric from ONE compute, written in batches.

    Prefer this over looping ``write_centrality`` per metric — that loop is
    what made betweenness run once per metric."""
    if store is None:
        return 0
    for metric in metrics:
        if metric not in _CENTRALITY_METRICS:
            raise ValueError(f"unknown centrality metric: {metric!r}")
    return await asyncio.to_thread(
        _write_centrality_nebula_all_sync, store, list(metrics),
    )


async def _write_centrality_nebula(store: Any, metric: str) -> int:
    # Single-metric entry point keeps ONE write implementation.  compute_all
    # still computes all three internally; callers wanting more than one metric
    # must use write_centrality_all so that cost is paid once.
    return await asyncio.to_thread(
        _write_centrality_nebula_all_sync, store, [metric],
    )
