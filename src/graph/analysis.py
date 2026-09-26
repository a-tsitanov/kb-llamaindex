"""Read-only graph analysis (Track 7b).

OFFLINE / admin only — never the query hot path.  Mirrors
``communities.py``: every function is **fail-soft** (a ``None`` store or
ANY query / compute error is logged and yields a safe empty result, never
raised through the caller).  Algorithms (components, personalized PageRank,
shortest path) run in-worker over igraph via the same weighted edge export
Leiden uses; global PageRank reads the materialised ``pagerank`` property.
Exposed via ``/admin/graph/*`` admin endpoints.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from loguru import logger

# ── public analysis functions ────────────────────────────────────────


def _percentile(sorted_vals: list[int], q: float) -> int:
    if not sorted_vals:
        return 0
    idx = round(q * (len(sorted_vals) - 1))
    return int(sorted_vals[max(0, min(idx, len(sorted_vals) - 1))])


_SHOW_STATS_FIELDS = {
    ("Tag", "Entity"): "entities",
    ("Tag", "Community"): "communities",
    ("Edge", "RELATED"): "relationships",
}


def _nebula_stats_computed_at(store: Any) -> str | None:
    """When the newest finished STATS job ran, ISO-ish, or None.

    `SHOW STATS` serves the LAST job's numbers, however old. Reporting
    them without saying when they were computed swaps one lie (a
    fabricated zero) for another (a stale number that looks fresh)."""
    try:
        rows = store.structured_query("SHOW JOBS") or []
    except Exception:
        return None
    stamps = [
        str(r.get("Stop Time"))
        for r in rows
        if isinstance(r, dict)
        and r.get("Command") == "STATS"
        and r.get("Status") == "FINISHED"
    ]
    iso = [m.group(0) for s in stamps if (m := re.search(r"\d{4}-\d{2}-\d{2}T[\d:.]+", s))]
    return max(iso) if iso else None


async def refresh_nebula_stats(store: Any | None) -> dict:
    """Recompute Nebula's own tag/edge counts (`SUBMIT JOB STATS`).

    `graph_stats` reads those counts instead of scanning, so without a
    periodic refresh it reports numbers frozen at whenever a job last ran
    — and nothing in this repo ran one until 2026-08-16, which is why
    `SHOW STATS` answered "please execute `submit job stats' firstly" on
    a space three weeks old. Cheap: measured at ~1 s on 1.5M vertices,
    with no memory spike, because it runs in storaged rather than as a
    graphd query.

    No-op without a store. Fail-soft: returns the error rather than
    raising, like the rest of this module.
    """
    if store is None:
        return {"submitted": False, "reason": "no store"}
    try:
        rows = await asyncio.to_thread(store.structured_query, "SUBMIT JOB STATS")
    except Exception as exc:
        logger.warning("refresh_nebula_stats failed: {e}", e=exc)
        return {"submitted": False, "error": str(exc)[:200]}
    job_id = None
    if rows and isinstance(rows[0], dict):
        job_id = rows[0].get("New Job Id")
    return {"submitted": True, "job_id": job_id}


def _nebula_show_stats(store: Any) -> dict[str, int] | None:
    """Exact counts from Nebula's own `SUBMIT JOB STATS` results.

    Preferred over `MATCH … count(…)` because those are full scans: on
    the production space they fail outright with `GraphMemoryExceeded`
    while this returns in milliseconds. Returns None when no stats job
    has ever run (Nebula answers "please execute `submit job stats'
    firstly") — the caller then falls back to scanning.
    """
    try:
        rows = store.structured_query("SHOW STATS") or []
    except Exception as exc:
        logger.info("graph_stats: SHOW STATS unavailable ({e}) — falling back", e=exc)
        return None
    counts: dict[str, int] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        field = _SHOW_STATS_FIELDS.get((r.get("Type"), r.get("Name")))
        if field is not None and r.get("Count") is not None:
            counts[field] = int(r["Count"])
    return counts or None


def _graph_stats_nebula(store: Any, out: dict) -> dict:
    """nGQL counts + client-side degree percentiles / duplicate grouping — nebula
    has no GDS and no percentileCont.

    Every sub-query is independent, and a failed one leaves its field
    None with the reason in `errors` — NEVER 0. The two are not the same
    thing, and this function used to conflate them: on 2026-08-16 it
    reported "relationships 0, communities 0" on a space that held
    310 989 and 2 302, because the counting scans hit Nebula's memory
    ceiling and the handler turned the exception into an empty list.
    A caller cannot tell a fabricated zero from a measured one.
    """
    errors: dict[str, str] = out.setdefault("errors", {})

    def q(stmt: str, field: str) -> list[dict] | None:
        """Rows, or None when the query could not run. None is not []."""
        try:
            return store.structured_query(stmt) or []
        except Exception as exc:
            logger.warning("graph_stats (nebula) sub-query failed: {e}", e=exc)
            errors[field] = str(exc)[:200]
            return None

    def _count(rows: list[dict] | None, key: str, field: str) -> int | None:
        if rows is None:
            return None
        if not rows or not isinstance(rows[0], dict) or rows[0].get(key) is None:
            # A count aggregate always yields a row — `MATCH (a:Alert)
            # RETURN count(a)` returns [{'n': 0}] on an empty tag,
            # verified on the live store. So no row means the query did
            # not really answer, which is not the same as zero.
            errors[field] = "count query returned no row"
            return None
        return int(rows[0][key])

    counts = _nebula_show_stats(store)
    if counts:
        # Cheap and exact. Timestamped, because these are as old as the
        # last stats job.
        out.update(counts)
        out["source"] = "show_stats"
        out["stats_computed_at"] = _nebula_stats_computed_at(store)
        for field in ("entities", "relationships", "communities"):
            out.setdefault(field, None)
    else:
        out["source"] = "scan"
        out["entities"] = _count(
            q("MATCH (e:`Entity`) RETURN count(e) AS ent_n;", "entities"),
            "ent_n", "entities")
        out["relationships"] = _count(
            q("MATCH ()-[x:`RELATED`]->() RETURN count(x) AS rel_n;", "relationships"),
            "rel_n", "relationships")
        out["communities"] = _count(
            q("MATCH (c:`Community`) RETURN count(c) AS comm_n;", "communities"),
            "comm_n", "communities")

    # Per-node degree, percentiles computed here (id(e) forces per-node grouping;
    # OPTIONAL MATCH keeps degree-0 nodes). No `SHOW STATS` equivalent —
    # it reports totals, not a distribution — so this stays a scan and
    # fails honestly when the host cannot serve it.
    degrows = q("MATCH (e:`Entity`) OPTIONAL MATCH (e)-[x:`RELATED`]-() "
                "RETURN id(e) AS eid, count(x) AS deg;", "degree")
    if degrows is not None:
        degs = sorted(int(r.get("deg") or 0) for r in degrows if isinstance(r, dict))
        out["degree"] = {
            "avg": sum(degs) / len(degs) if degs else 0.0,
            "p50": _percentile(degs, 0.5),
            "p99": _percentile(degs, 0.99),
            "max": degs[-1] if degs else 0,
        }

    # Duplicate display names (case-insensitive), grouped in Python.
    namerows = q("MATCH (e:`Entity`) RETURN e.`Entity`.name AS dup_name;", "duplicates")
    if namerows is not None:
        names = [r.get("dup_name") for r in namerows
                 if isinstance(r, dict) and r.get("dup_name")]
        groups: dict[str, int] = {}
        for n in names:
            groups[n.strip().lower()] = groups.get(n.strip().lower(), 0) + 1
        dup = {k: c for k, c in groups.items() if c > 1}
        out["duplicate_name_groups"] = len(dup)
        out["duplicate_entities"] = sum(dup.values())
    return out


def _size_distribution(sizes: list[int]) -> dict:
    if not sizes:
        return {}
    s = sorted(sizes)
    return {
        "count": len(s), "min": s[0], "max": s[-1],
        "mean": sum(s) / len(s),
        "p50": _percentile(s, 0.5), "p90": _percentile(s, 0.9), "p99": _percentile(s, 0.99),
    }


def _components_from_edges(edges: list, names: list[str]) -> dict:
    """Weakly-connected components via in-worker igraph (no GDS under nebula)."""
    from src.graph.community_leiden import build_graph

    g, _ = build_graph(edges, names)
    if g.vcount() == 0:
        return {"component_count": 0, "distribution": {}}
    sizes = sorted(g.connected_components(mode="weak").sizes(), reverse=True)
    return {"component_count": len(sizes), "distribution": _size_distribution(sizes)}


def _components_nebula(store: Any) -> dict:
    from src.graph.community_leiden import extract_entity_edges

    edges, names = extract_entity_edges(store)
    return _components_from_edges(edges, names)


def _personalized_pagerank_from_edges(
    edges: list, names: list[str], seeds: list[str], top_n: int,
) -> list[dict]:
    """Seed-biased PageRank via in-worker igraph (no GDS under nebula)."""
    from src.graph.community_leiden import build_graph

    g, gnames = build_graph(edges, names)
    idx = {n: i for i, n in enumerate(gnames)}
    seed_idx = [idx[s] for s in seeds if s in idx]
    if not seed_idx or g.vcount() == 0:
        return []
    weights = g.es["weight"] if "weight" in g.es.attributes() else None
    scores = g.personalized_pagerank(reset_vertices=seed_idx, weights=weights, directed=False)
    ranked = sorted(zip(gnames, scores, strict=False), key=lambda x: -x[1])[: int(top_n)]
    return [{"name": n, "score": float(s)} for n, s in ranked]


def _personalized_pagerank_nebula(store: Any, seeds: list[str], top_n: int) -> list[dict]:
    from src.graph.community_leiden import extract_entity_edges

    edges, names = extract_entity_edges(store)
    return _personalized_pagerank_from_edges(edges, names, seeds, top_n)


def _shortest_path_from_edges(edges: list, names: list[str], source: str, target: str) -> dict:
    """Undirected shortest path via in-worker igraph (no GDS under nebula)."""
    from src.graph.community_leiden import build_graph

    g, gnames = build_graph(edges, names)
    idx = {n: i for i, n in enumerate(gnames)}
    si, ti = idx.get(source), idx.get(target)
    if si is None or ti is None:
        return {"path": [], "hops": -1}
    paths = g.get_shortest_paths(si, to=ti, mode="all")
    seq = paths[0] if paths else []
    if not seq:
        return {"path": [], "hops": -1}
    return {"path": [gnames[i] for i in seq], "hops": len(seq) - 1}


def _shortest_path_nebula(store: Any, source: str, target: str) -> dict:
    from src.graph.community_leiden import extract_entity_edges

    edges, names = extract_entity_edges(store)
    return _shortest_path_from_edges(edges, names, source, target)


def _pagerank_nebula(store: Any, top_n: int) -> list[dict]:
    """Read the igraph-materialized ``pagerank`` property (there is no GDS under
    nebula; centrality is computed in-worker by the materialize stage)."""
    stmt = (
        "MATCH (e:`Entity`) WHERE e.`Entity`.pagerank > 0 "
        "RETURN e.`Entity`.name AS name, e.`Entity`.pagerank AS score "
        f"ORDER BY score DESC LIMIT {int(top_n)};"
    )
    rows = store.structured_query(stmt) or []
    return [
        {"name": r.get("name"), "score": float(r.get("score") or 0.0)}
        for r in rows if isinstance(r, dict) and r.get("name")
    ]


async def pagerank(store: Any | None, *, top_n: int = 20) -> list[dict]:
    """Top-N entities by weighted PageRank (importance/centrality)."""
    if store is None:
        return []
    try:
        return await asyncio.to_thread(_pagerank_nebula, store, top_n)
    except Exception as exc:  # fail-soft
        logger.warning("pagerank (nebula) failed: {e}", e=exc)
        return []


async def personalized_pagerank(
    store: Any | None, seeds: list[str], *, top_n: int = 20,
) -> list[dict]:
    """Top-N entities by PageRank biased toward `seeds` (seed entity names).

    Empty/blank seeds → `[]` (nothing to bias toward).  Fail-soft like
    the rest: store/compute error → `[]`."""
    cleaned = [s for s in (seeds or []) if s and str(s).strip()]
    if store is None or not cleaned:
        return []
    try:
        return await asyncio.to_thread(
            _personalized_pagerank_nebula, store, cleaned, top_n)
    except Exception as exc:  # fail-soft
        logger.warning("personalized_pagerank (nebula) failed: {e}", e=exc)
        return []


async def components(store: Any | None) -> dict:
    """Weakly-connected-component count + size distribution (connectivity
    health; large singleton fraction explains empty Leiden communities)."""
    if store is None:
        return {"component_count": 0, "distribution": {}}
    try:
        return await asyncio.to_thread(_components_nebula, store)
    except Exception as exc:  # fail-soft
        logger.warning("components (nebula) failed: {e}", e=exc)
        return {"component_count": 0, "distribution": {}}


async def shortest_path(
    store: Any | None, source: str, target: str, *, max_hops: int = 6,
) -> dict:
    """Shortest undirected path between two entities by name.

    ``{"path": [], "hops": -1}`` when there's no path / on any error."""
    empty = {"path": [], "hops": -1}
    if store is None:
        return empty
    try:
        return await asyncio.to_thread(_shortest_path_nebula, store, source, target)
    except Exception as exc:  # fail-soft
        logger.warning("shortest_path (nebula) failed: {e}", e=exc)
        return empty


async def graph_stats(store: Any | None) -> dict:
    """Operational snapshot: entity/relationship counts, degree
    distribution (p50/p99/max), duplicate-name groups, community count.

    Feeds the live diagnostics from the 250k-scale assessment.  Every
    sub-query is independent + fail-soft so one failure doesn't void the
    rest.

    A field that could NOT be measured comes back ``None``, with the
    reason under ``errors``.  It is never 0.  Reporting a failure as a
    zero is how this function spent 2026-08-16 telling operators the
    production graph had no relationships and no communities while it
    held 310 989 and 2 302 — the counting scans were being refused for
    memory and the handler turned that into an empty result.

    Under nebula, ``source`` says where the counts came from:
    ``show_stats`` (Nebula's own ``SUBMIT JOB STATS`` output — exact,
    milliseconds, and as old as ``stats_computed_at``) or ``scan``.
    """
    out: dict[str, Any] = {
        "entities": None,
        "relationships": None,
        "degree": None,
        "duplicate_name_groups": None,
        "duplicate_entities": None,
        "communities": None,
        "errors": {},
    }
    if store is None:
        out["errors"]["store"] = "no graph store configured"
        return out
    return await asyncio.to_thread(_graph_stats_nebula, store, out)


__all__ = [
    "components",
    "graph_stats",
    "pagerank",
    "personalized_pagerank",
    "shortest_path",
]
