"""Offline graph-community detection (Search R6, decision C1).

DECOUPLED / OFFLINE only — runs from the ``CommunityBuildWorkflow`` on
the dedicated ``kb-graph-build`` queue (admin endpoint / schedule), NEVER
on the query hot path.

The Leiden COMPUTE backend is pluggable via ``community_backend``
(ADR-0015): ``"leidenalg"`` (default) streams the edges out and runs
hierarchical Leiden in this worker (``src/graph/community_leiden.py``);
``"graphscope"`` runs distributed single-level Leiden
(``src/graph/community_graphscope.py``).  Both backends emit the SAME
``rows`` (``[{name, communityId, ids}]``), so the grouping + ``:Community``
materialisation below are backend-agnostic.

``detect_communities`` runs Leiden over the entity sub-graph and
materialises ``:Community`` nodes:

  1. Stream the entity edges out through the edge-export seam.
  2. Cluster them in-worker → one ``communityId`` (+ dendrogram ``ids``)
     per entity.
  3. Group members by ``communityId``, drop communities below
     ``min_size``.
  4. Idempotently write one ``:Community {id, level}`` node per group and
     link its members (``IN_COMMUNITY``) via the community writeback.

Detection is fail-safe: a ``None`` store or any detection error is logged
and yields ``[]`` so the calling activity never raises through the
Temporal boundary.  The write-back is NOT fail-open (see below).
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from loguru import logger

from src.config import settings
from src.graph.community_graphscope import single_level_rows_graphscope
from src.graph.community_leiden import (
    extract_entity_edges,
    hierarchy_rows,
    single_level_rows,
)
from src.workflow.contracts import CommunityRef


async def _read_old_reports(store: Any | None) -> dict[tuple[int, str], dict]:
    """{(level, members_hash) -> {report,title,summary,report_vec}} from the
    PRIOR build, read BEFORE prune so unchanged communities keep their
    report.  Best-effort: [] / {} on None store or any error (logged)."""
    if store is None:
        return {}
    try:
        from src.graph.community_writeback import build_community_writeback
        rows = await asyncio.to_thread(build_community_writeback(store).read_old_reports)
    except Exception as exc:
        logger.warning("communities: read old reports failed: {e}", e=exc)
        return {}
    out: dict[tuple[int, str], dict] = {}
    for r in rows or []:
        h = r.get("h")
        if h is None:
            continue
        out[(int(r.get("level") or 0), h)] = {
            "report": r.get("report"), "title": r.get("title"),
            "summary": r.get("summary"), "report_vec": r.get("report_vec"),
            "summarized_at": r.get("summarized_at"),
        }
    return out


def members_hash(members: list[str]) -> str:
    """Order-insensitive content hash of a community's members.

    Lets a re-run skip re-summarising a community whose membership is
    unchanged (``members_hash`` persisted on the ``:Community`` node).  The
    ``\\x1f`` (unit separator) join is collision-safe vs. member names that
    might themselves contain commas/spaces.
    """
    return hashlib.sha256("\x1f".join(sorted(members)).encode("utf-8")).hexdigest()


def _group_by_levels(
    rows: list[dict], *, min_size: int, max_levels: int,
) -> list[CommunityRef]:
    """Map a Leiden dendrogram stream into ``CommunityRef``s across levels.

    ``rows``: ``[{name, ids:[finest..coarsest]}]`` (the
    ``intermediateCommunityIds`` list per node).  level 0 == coarsest
    (``ids[-1]`` == today's ``communityId``); level k == ``ids[-(k+1)]``
    (finer as k grows).  ``parent_id`` of a level-k community == the id of
    the level-(k-1) (coarser) community its members map to.  Pure /
    unit-testable; communities below ``min_size`` are dropped.
    """
    if not rows:
        return []
    # node name → [level0_cid, level1_cid, ...] (coarsest..finer).  Rows may
    # carry ragged ``ids`` (a degenerate single-level run yields a bare int
    # column); guard the first valid row for ``depth``.
    node_level_cid: dict[str, list[str]] = {}
    depth = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = r.get("name")
        ids = r.get("ids")
        if not name or not isinstance(ids, (list, tuple)) or not ids:
            continue
        d = min(len(ids), max_levels)
        depth = max(depth, d)
        node_level_cid[str(name)] = [str(ids[-(k + 1)]) for k in range(d)]
    if not node_level_cid:
        return []

    out: list[CommunityRef] = []
    for k in range(depth):
        members_by_cid: dict[str, list[str]] = {}
        parent_by_cid: dict[str, str] = {}
        for name, cids in node_level_cid.items():
            if k >= len(cids):
                continue
            cid = cids[k]
            members_by_cid.setdefault(cid, []).append(name)
            if k > 0:
                parent_by_cid[cid] = cids[k - 1]  # coarser level is the parent
        # INVARIANT (Leiden nesting): a level-(k-1) community is the union of
        # its level-k children, so member_count(parent) >= member_count(child).
        # Hence `min_size` can never drop a parent while keeping a child →
        # the level>0 parent lookup in `merge_subcommunity` never
        # orphans. Holds only while intermediateCommunityIds stays strictly
        # nested (hierarchical Leiden guarantees this).
        for cid, members in members_by_cid.items():
            if len(members) < min_size:
                continue
            members = sorted(members)
            out.append(CommunityRef(
                community_id=cid, level=k, members=members,
                members_hash=members_hash(members),
                parent_id=parent_by_cid.get(cid, ""),
                needs_report=True,
            ))
    # Deterministic ordering — coarsest level first, then largest, then id.
    out.sort(key=lambda c: (c.level, -c.member_count, c.community_id))
    return out


def _coarsest_from_rows(
    rows: list[dict], *, min_size: int, level: int,
) -> list[CommunityRef]:
    """Group the COARSEST dendrogram column (today's ``communityId``) into
    ``CommunityRef``s, dropping communities below ``min_size``.

    Back-compat shim for the single-level ``detect_communities`` path: it
    reads ``communityId`` (the last/coarsest column == ``ids[-1]``) so the
    grouping is identical to the legacy ``_group_by_community`` while ALSO
    stamping ``members_hash`` (the new ``:Community`` field).  ``level``
    tags the output exactly as the caller asked (legacy ``level`` param).
    """
    buckets: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        cid = row.get("communityId")
        if cid is None:
            ids = row.get("ids")
            if isinstance(ids, (list, tuple)) and ids:
                cid = ids[-1]
        if not name or cid is None:
            continue
        buckets.setdefault(str(cid), []).append(str(name))
    out: list[CommunityRef] = []
    for cid, members in buckets.items():
        if len(members) < min_size:
            continue
        members = sorted(members)
        out.append(CommunityRef(
            community_id=cid, level=level, members=members,
            members_hash=members_hash(members), parent_id="",
            needs_report=True,
        ))
    out.sort(key=lambda c: (-c.member_count, c.community_id))
    return out


async def _leiden_rows(
    store: Any, *, gamma: float, max_levels: int, seed: int = 19,
) -> list[dict]:
    """leidenalg backend: stream edges + cluster in-worker.

    Returns the canonical rows shape
    (``[{name, communityId, ids}]``).  CPU-bound clustering runs in a
    thread so the activity event loop (and its heartbeat) stays live.
    """
    edges, names = await asyncio.to_thread(extract_entity_edges, store)
    if max_levels > 1:
        return await asyncio.to_thread(
            hierarchy_rows, edges, names,
            gamma=gamma, max_levels=max_levels, seed=seed,
        )
    return await asyncio.to_thread(
        single_level_rows, edges, names, gamma=gamma, seed=seed,
    )


async def _graphscope_rows(
    store: Any, *, gamma: float, seed: int = 19,
) -> list[dict]:
    """graphscope backend: stream edges + distributed single-level Leiden.

    Same rows shape as ``_leiden_rows`` (``[{name, communityId, ids}]``).
    CPU/network-bound clustering runs in a thread so the activity event loop
    (and its heartbeat) stays live, mirroring ``_leiden_rows``.
    """
    edges, names = await asyncio.to_thread(extract_entity_edges, store)
    return await asyncio.to_thread(
        single_level_rows_graphscope, edges, names, gamma=gamma, seed=seed,
    )


async def detect_communities(
    store: Any | None,
    *,
    min_size: int = 3,
    level: int = 0,
    gamma: float = 1.0,
) -> list[CommunityRef]:
    """Run Leiden over the entity graph and materialise ``:Community``.

    SINGLE-LEVEL (back-compat) path: detects only the coarsest dendrogram
    column (today's ``communityId``) and writes it at the requested
    ``level`` with ``(:__Entity__)-[:IN_COMMUNITY]->(:Community)`` links and
    a level-scoped prune — IDENTICAL to the pre-hierarchy behaviour, now
    additionally stamping ``members_hash``.  For the full dendrogram use
    ``detect_hierarchy``.

    Returns the detected communities (``member_count >= min_size``).
    Fail-safe: ``store is None`` or ANY detection error → ``[]`` (logged,
    never raised) so the calling activity stays green.
    """
    if store is None:
        logger.info("communities: no graph store — skipping detection")
        return []

    if settings.temporal.community_backend == "graphscope":
        try:
            rows = await _graphscope_rows(store, gamma=gamma)
            stats = {"nodes": len({r["name"] for r in rows}), "rels": -1}
        except Exception as exc:
            logger.error("communities: graphscope detection FAILED: {e}", e=exc)
            return []
        if not rows:
            # The graphscope adapter fail-opens to no rows on any import/API
            # error — and is a stub returning [] until the manual cluster gate
            # finalises it.  Unlike an empty leidenalg result (a
            # legitimate "no communities" that SHOULD prune the stale layer),
            # an empty graphscope result is a FAILURE signal: return a true
            # no-op that leaves the existing :Community layer untouched (never
            # prune it away), mirroring the leidenalg branch's raise->[] which
            # also short-circuits before the write-back.  Note this keys on
            # `rows`, not `communities`: non-empty rows whose groups all fall
            # below min_size are a real detection and still prune correctly.
            logger.warning(
                "communities: graphscope returned 0 rows — treating as a "
                "fail-open no-op (existing communities left intact)"
            )
            return []
    else:
        try:
            rows = await _leiden_rows(store, gamma=gamma, max_levels=1)
            stats = {"nodes": len({r["name"] for r in rows}), "rels": -1}
        except Exception as exc:
            logger.error("communities: leidenalg detection FAILED: {e}", e=exc)
            return []

    if not rows:
        logger.warning(
            "communities: Leiden returned 0 rows — projected {n} entities / "
            "{r} relationships (empty or disconnected __Entity__ graph?)",
            n=stats["nodes"], r=stats["rels"],
        )
    communities = _coarsest_from_rows(rows, min_size=min_size, level=level)
    logger.info(
        "communities: detected {n} communities (>= {m} members) from {r} "
        "rows — projected {pn} entities / {pr} relationships",
        n=len(communities), m=min_size, r=len(rows),
        pn=stats["nodes"], pr=stats["rels"],
    )

    # Persist :Community nodes + member links via the community writeback
    # (nGQL).
    from src.graph.community_writeback import build_community_writeback
    writeback = build_community_writeback(store)
    try:
        await asyncio.to_thread(writeback.ensure_schema)
        # Prune the prior run's communities for THIS level FIRST so a rebuild
        # starts clean (Leiden may renumber/shrink ids). Level-scoped.
        await asyncio.to_thread(writeback.prune_level, level)
        for comm_ref in communities:
            # asyncio.to_thread forwards **kwargs; each call is awaited before
            # the next iteration, so no closure/late-binding concern.
            await asyncio.to_thread(
                writeback.merge_community,
                community_id=comm_ref.community_id, level=comm_ref.level,
                member_count=comm_ref.member_count, members_hash=comm_ref.members_hash,
                members=comm_ref.members, carry=None,
            )
    except Exception as exc:
        # NOT fail-open: without :Community nodes the refs we'd return are
        # unusable — the caller fans out one summarize per ref and every report
        # write then fails ("Vertex or edge not found"), burning an LLM call
        # each.  Fail loudly so the build retries instead of silently
        # producing nothing.
        logger.error("communities: :Community write failed: {e}", e=exc)
        raise

    return communities


async def detect_hierarchy(
    store: Any | None,
    *,
    max_levels: int,
    min_size: int = 3,
    gamma: float = 1.0,
) -> list[CommunityRef]:
    """Run Leiden over the entity graph and materialise the community
    HIERARCHY (up to ``max_levels`` dendrogram levels).

    level 0 == coarsest (today's ``communityId``) and keeps
    ``(:__Entity__)-[:IN_COMMUNITY]->(:Community {level:0})`` exactly as
    ``detect_communities`` does.  All levels (including finer k>0)
    keep ``(:__Entity__)-[:IN_COMMUNITY]->(:Community)`` member links
    for leaf context; finer levels additionally wire
    ``(:Community {level:k-1})-[:PARENT_OF]->(:Community {level:k})``
    to form the dendrogram coarser→finer.  Every level stamps
    ``member_count`` + ``members_hash``.

    A rebuild prunes ALL prior ``:Community`` (every level) up front since
    the dendrogram depth/ids can change between runs.

    Returns the detected communities across all levels (coarsest first).
    Fail-safe: ``store is None`` or ANY detection error → ``[]`` (logged,
    never raised).
    """
    if store is None:
        logger.info("communities: no graph store — skipping hierarchy detection")
        return []

    if settings.temporal.community_backend == "graphscope":
        # graphscope is single-level only; hierarchical detection has no
        # graphscope implementation — an explicit fail-safe no-op.
        logger.error(
            "communities: hierarchy detection is unavailable on the graphscope "
            "backend (single-level only)",
        )
        return []
    try:
        rows = await _leiden_rows(store, gamma=gamma, max_levels=max_levels)
        stats = {"nodes": len({r["name"] for r in rows}), "rels": -1}
    except Exception as exc:
        logger.error(
            "communities: leidenalg hierarchy detection FAILED: {e}", e=exc,
        )
        return []

    if not rows:
        logger.warning(
            "communities: Leiden returned 0 rows — projected {n} entities / "
            "{r} relationships (empty or disconnected __Entity__ graph?)",
            n=stats["nodes"], r=stats["rels"],
        )
    communities = _group_by_levels(rows, min_size=min_size, max_levels=max_levels)
    n_levels = len({c.level for c in communities})
    logger.info(
        "communities: detected {n} communities across {L} level(s) "
        "(>= {m} members) from {r} rows — projected {pn} entities / "
        "{pr} relationships",
        n=len(communities), L=n_levels, m=min_size, r=len(rows),
        pn=stats["nodes"], pr=stats["rels"],
    )

    # Read the PRIOR build's reports BEFORE we prune so a community whose
    # (level, members_hash) is unchanged carries its report over (no
    # re-summarisation).  Best-effort: {} on any error.
    old_reports = await _read_old_reports(store)

    # Carry forward unchanged reports: a community whose (level, members_hash)
    # matches a prior report keeps it (needs_report=False); the (possibly
    # model_copied) refs are returned so the build-workflow sees the right
    # needs_report flags.  Pre-compute the per-community carry param block.
    carried_refs: list[CommunityRef] = []
    carry_params: list[dict] = []
    n_carried = 0
    for comm in communities:
        carried = old_reports.get((comm.level, comm.members_hash))
        if carried and carried.get("report"):
            comm = comm.model_copy(update={"needs_report": False})
            params = {
                "carry_report": carried.get("report"),
                "carry_title": carried.get("title"),
                "carry_summary": carried.get("summary"),
                "carry_report_vec": carried.get("report_vec"),
                # Preserve the ORIGINAL summarisation time — a carried report
                # was NOT re-summarised, so summarized_at must reflect content
                # freshness, not the rebuild time (keeps staleness logic sane).
                "carry_summarized_at": carried.get("summarized_at"),
            }
            n_carried += 1
        else:
            params = {
                "carry_report": None, "carry_title": None,
                "carry_summary": None, "carry_report_vec": None,
                "carry_summarized_at": None,
            }
        carried_refs.append(comm)
        carry_params.append(params)
    communities = carried_refs
    if n_carried:
        logger.info(
            "communities: carried over {n} unchanged report(s) (skipping re-summarise)",
            n=n_carried,
        )

    # Persist the hierarchy.  Communities are sorted coarsest-first, so a
    # level-k node's level-(k-1) parent is always written before it.
    from src.graph.community_writeback import build_community_writeback
    writeback = build_community_writeback(store)
    try:
        await asyncio.to_thread(writeback.ensure_schema)
        # Prune EVERY prior :Community (depth/ids can change between runs).
        await asyncio.to_thread(writeback.prune_all)
        for comm_ref, carry in zip(communities, carry_params):
            carry_clean = {
                "report": carry.get("carry_report"),
                "title": carry.get("carry_title"),
                "summary": carry.get("carry_summary"),
                "report_vec": carry.get("carry_report_vec"),
                "summarized_at": carry.get("carry_summarized_at"),
            }
            if comm_ref.level == 0:
                await asyncio.to_thread(
                    writeback.merge_community,
                    community_id=comm_ref.community_id, level=comm_ref.level,
                    member_count=comm_ref.member_count, members_hash=comm_ref.members_hash,
                    members=comm_ref.members, carry=carry_clean,
                )
            else:
                await asyncio.to_thread(
                    writeback.merge_subcommunity,
                    community_id=comm_ref.community_id, level=comm_ref.level,
                    parent_id=comm_ref.parent_id, member_count=comm_ref.member_count,
                    members_hash=comm_ref.members_hash, members=comm_ref.members,
                    carry=carry_clean,
                )
    except Exception as exc:
        # NOT fail-open — see the single-level path above.  A partially written
        # hierarchy is worse still: communities are written coarsest-first, so
        # an abort leaves the root vertex in place and EVERY descendant missing.
        logger.error("communities: :Community hierarchy write failed: {e}", e=exc)
        raise

    return communities


__all__ = ["detect_communities", "detect_hierarchy", "members_hash"]
