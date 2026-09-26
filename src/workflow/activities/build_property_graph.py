"""`build_property_graph` — Chunk + MENTIONS + entity/relation upsert."""

from __future__ import annotations

import asyncio

from llama_index.core.graph_stores.types import KG_NODES_KEY, KG_RELATIONS_KEY
from loguru import logger
from temporalio import activity

from src.graph.store import build_graph_store
from src.workflow.contracts import GraphBuilt, Merged
from src.workflow.heartbeat import heartbeat_every
from src.workflow.staging import build_staging_store

# Pulse interval for the blocking Neo4j writes. Must stay well under the
# activity's heartbeat_timeout (5m in graph_build.py). At 37k nodes / 60k
# edges a single upsert can outrun that window; without a continuous pulse
# Temporal fires timeout_type_heartbeat and _FAST_RETRY re-runs the whole
# activity (up to 50×), amplifying offered load into a Neo4j-CPU retry storm.
_HEARTBEAT_INTERVAL_S = 60.0

_NEO4J_UNSAFE_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "canonical_identifiers",
        "canonical_identifiers_augment",
    }
)
_PRESERVE_METADATA_KEYS: frozenset[str] = frozenset(
    {
        KG_NODES_KEY,
        KG_RELATIONS_KEY,
    }
)


def _is_neo4j_safe(value) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, (list, tuple)):
        return all(v is None or isinstance(v, (str, int, float, bool)) for v in value)
    return False


def _strip_neo4j_unsafe_metadata(nodes) -> None:
    for n in nodes:
        md = getattr(n, "metadata", None)
        if not md:
            continue
        for key in list(md.keys()):
            if key in _PRESERVE_METADATA_KEYS:
                continue
            if key in _NEO4J_UNSAFE_METADATA_KEYS or not _is_neo4j_safe(md[key]):
                md.pop(key, None)


@activity.defn
async def build_property_graph(merged: Merged) -> GraphBuilt:
    activity.logger.info(
        "build_property_graph start  doc=%s",
        merged.kg.parsed.ctx.doc_id,
    )
    activity.heartbeat({"stage": "init"})

    staging = build_staging_store()
    entities, relations, nodes = await asyncio.to_thread(
        staging.read_pickle,
        merged.merged_entities_uri,
    )
    activity.heartbeat(
        {
            "stage": "loaded",
            "entities": len(entities),
            "relations": len(relations),
            "chunks": len(nodes),
        }
    )

    # Pulse on a timer throughout the blocking graph-write region: store
    # construction (driver I/O + schema refresh, behind a process-global
    # lock), the entity/relation upserts, the gated first_seen stamp, and the lookup-index
    # DDL all run off the loop via to_thread and can each be slow under
    # hub-node lock contention. A one-shot heartbeat between steps is not
    # enough — a single step can outrun heartbeat_timeout. heartbeat_every
    # keeps a progressing-but-slow build from being mistaken for a dead one.
    async with heartbeat_every(_HEARTBEAT_INTERVAL_S, {"stage": "writing"}):
        graph_store = await asyncio.to_thread(build_graph_store)

        _strip_neo4j_unsafe_metadata(nodes)
        activity.heartbeat({"stage": "scrubbed"})

        activity.logger.info(
            "build_property_graph building index  chunks=%d",
            len(nodes),
        )
        # Chunks are NOT graph nodes under nebula (their vectors live in
        # Milvus, written by the separate vector-half of ingest), so there is
        # no LlamaIndex PropertyGraphIndex write here. The entity/relation
        # graph write happens via the explicit upsert_* below.
        from src.config import settings

        activity.heartbeat({"stage": "index_built"})

        if entities:
            await asyncio.to_thread(graph_store.upsert_nodes, entities)
            activity.heartbeat({"stage": "entities_upserted", "count": len(entities)})
        # Trust-based conflict resolution: read what the graph already believes
        # about this batch's pairs and let the more credible source keep the
        # belief (see src/graph/edge_conflicts.py).  Gated on the trust table
        # being configured at all — with no policy there is nothing to resolve,
        # and skipping spares the batch its read-back.
        edge_conflicts: list[dict] = []
        if relations and settings.signals.source_trust:
            from dataclasses import asdict

            from src.analytics.source_trust import trust_for
            from src.graph.edge_conflicts import load_stored_edges, resolve_edge_conflicts
            from src.retrieval.date_filters import today_epoch_days

            stored_edges = await asyncio.to_thread(
                load_stored_edges, graph_store, relations,
            )
            relations, conflicts = resolve_edge_conflicts(
                relations,
                stored_edges,
                doc_trust=trust_for(merged.kg.parsed.ctx.group),
                doc_id=merged.kg.parsed.ctx.doc_id,
                ingest_epoch=today_epoch_days(),
            )
            edge_conflicts = [asdict(c) for c in conflicts]
            activity.heartbeat(
                {"stage": "conflicts_resolved", "count": len(edge_conflicts)},
            )

        if relations:
            await asyncio.to_thread(graph_store.upsert_relations, relations)
            activity.heartbeat({"stage": "relations_upserted", "count": len(relations)})

        if edge_conflicts:
            # Audit trail for the beliefs this write retired / rejected. The
            # graph keeps only the winner, so a logging failure loses history —
            # but never the ingest.
            try:
                from src.storage.postgres import AsyncPostgres

                await AsyncPostgres().record_fact_conflicts(edge_conflicts)
            except Exception as exc:
                logger.warning("fact_supersede log skipped (non-fatal): {e}", e=exc)

        # E1 — ON-CREATE-emulated first_seen stamping (gated, dark by default).
        # Relation.source_id/target_id are synthetic EntityNode.id values (not
        # entity names), so build an id→name map from the merged entities list
        # before constructing the relation triples for the Cypher stamp query.
        from src.config import settings

        if settings.events.first_seen_enabled:
            # Best-effort enrichment: a stamping failure must NEVER fail the
            # graph build itself (stamp_first_seen is fail-soft inside, but
            # the triple-building above it can also throw on odd shapes).
            try:
                from src.graph.first_seen import stamp_first_seen
                from src.retrieval.date_filters import today_epoch_days

                _id_to_name = {e.id: e.name for e in entities}
                _ent_names = [e.name for e in entities]
                _rel_triples = [
                    (_id_to_name[r.source_id], r.label, _id_to_name[r.target_id])
                    for r in relations
                    if r.source_id in _id_to_name and r.target_id in _id_to_name
                ]
                await asyncio.to_thread(
                    stamp_first_seen,
                    graph_store,
                    entity_names=_ent_names,
                    relations=_rel_triples,
                    ingest_epoch=today_epoch_days(),
                    doc_id=merged.kg.parsed.ctx.doc_id,
                )
            except Exception as exc:  # enrichment, not the build
                logger.warning("first_seen stamping skipped (non-fatal): {e}", e=exc)
            activity.heartbeat({"stage": "first_seen_stamped"})


    logger.info(
        "build_property_graph done  doc={d}  e={e}  r={r}",
        d=merged.kg.parsed.ctx.doc_id,
        e=len(entities),
        r=len(relations),
    )
    return GraphBuilt(entities=len(entities), relations=len(relations))
