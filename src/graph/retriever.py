"""Graph-search wrapper for the agent loop.

Returns a ``RoundGraphData`` with structured ``entities`` and
``relations`` lists — same shape used by enterprise-kb's
``query_graph_data`` so dedup / accumulation logic ports
directly.

Implementation over the NebulaGraph store (nGQL subgraph walks, seeded
by Milvus entity kNN + the Postgres entity table):
  * Returns three things the agent cares about:
      - entity dicts (``entity_name``, ``entity_type``,
        ``description``);
      - relationship dicts (``src_id``, ``tgt_id``, ``label``);
      - chunk nodes related to the matched graph elements.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date

from llama_index.core.schema import NodeWithScore
from loguru import logger

from src.graph.nebula_store import _q as _nebula_q
from src.graph.nebula_store import entity_vid

# ── bounded multi-hop walk caps (R3) ─────────────────────────────────
# Hard ceilings so a deep/dense traversal can never blow up the agent's
# context. Hops are clamped before the subgraph call and node/edge caps
# are enforced when mapping rows (defensive truncation).
GRAPH_WALK_MAX_HOPS = 3
GRAPH_WALK_NODE_CAP = 50
GRAPH_WALK_EDGE_CAP = 100

# ── relation polarity / temporal validity filtering (#8) ─────────────
# merge.py stores a logical ``polarity`` (majority vote) and an opaque ISO
# validity window (``valid_from`` / ``valid_to``) on each relationship.
# lightrag_parse normalises polarity to exactly one of these three values;
# anything missing/unrecognised reads as "affirmed". Edges in
# EXCLUDED_POLARITIES are dropped at retrieval; 'uncertain' is KEPT by
# default (it is a hedge, not a denial). Override the set here to change.
EXCLUDED_POLARITIES = frozenset({"negated"})


def _relation_is_live(rel: dict, *, now_iso: str) -> bool:
    """True if a walk-relation dict should be surfaced to the agent.

    Drops edges the source text NEGATES (``polarity`` in
    ``EXCLUDED_POLARITIES``) and edges whose ``valid_to`` is strictly
    before ``now_iso`` (expired). NULL/missing polarity ⇒ affirmed; NULL
    ``valid_to`` ⇒ never-expiring; legacy edges lacking both props pass.

    Temporal compare is lexicographic on ISO strings, which is correct for
    same-shaped ISO dates ("2020" < "2026-06-16", "2020-01-01" <
    "2026-06-16"). Mixed precision compares by common prefix, which keeps
    a year-only ``valid_to`` of a past year correctly expired.
    """
    polarity = rel.get("polarity")
    if polarity is not None and str(polarity).strip().lower() in EXCLUDED_POLARITIES:
        return False
    valid_to = rel.get("valid_to")
    if valid_to:
        # Compare on the overlapping prefix length so "2020" vs
        # "2026-06-16" doesn't mis-rank on length.
        vt = str(valid_to)
        cmp = now_iso[: len(vt)]
        if vt < cmp:
            return False
    return True


@dataclass
class RoundGraphData:
    entities: list[dict] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)
    chunks: list[NodeWithScore] = field(default_factory=list)
    # Why this came back empty, when it did so because the lookup could
    # not run. Empty string means it ran. Without this an infrastructure
    # refusal is indistinguishable from "the graph has no such entity" —
    # which is exactly how a `GraphMemoryExceeded` spent a day being
    # reported to callers as "Украина is not in the knowledge base".
    error: str = ""


def _find_by_name_ngql(query: str, *, limit: int) -> str:
    """PREFIX name lookup under nebula, over the ``entity_name_idx`` index.

    Whitespace-split the input and OR a ``STARTS WITH`` per token. Exact
    and prefix both work: "Украина" finds itself, "Иванов" finds "Иванов
    Иван Иванович".

    KNOWN LIMIT: a token matching mid-name does NOT match. "Ромаш" will
    not find "ООО Ромашка", which the previous ``CONTAINS`` version
    promised. That promise was not kept in practice — ``CONTAINS`` cannot
    use an index, so the query was a full scan of every Entity vertex,
    and on a 161k-entity graph it failed outright with
    ``GraphMemoryExceeded (-2600)``. Measured 2026-08-18: this form
    answers in under two seconds where ``CONTAINS`` failed in three.
    Prefix matching that works beats substring matching that does not.

    True substring search needs an index built for it — a trigram table
    of entity names in Postgres, the way the statistics registry is
    searched. That is a separate piece of work; do not reintroduce
    ``CONTAINS`` here instead.

    Returns ``""`` for blank input so the caller short-circuits.
    Case-sensitive, like the index.
    """
    tokens = [t for t in (query or "").split() if t.strip()]
    if not tokens:
        return ""
    clauses = " OR ".join(
        f"`Entity`.name STARTS WITH {_nebula_q(t)}" for t in tokens
    )
    return (
        f"LOOKUP ON `Entity` WHERE {clauses} "
        "YIELD id(vertex) AS vid, `Entity`.name AS name, "
        "`Entity`.label AS label, `Entity`.description AS description "
        f"| LIMIT {int(limit)};"
    )


class GraphRetriever:
    """Async graph search over the NebulaGraph store (nGQL + Milvus kNN)."""

    def __init__(
        self,
        store,
        *,
        similarity_top_k: int = 10,
        filter_polarity_temporal: bool = True,
    ) -> None:
        self._graph_store = store
        self._similarity_top_k = similarity_top_k
        # #8: drop negated / expired relations from awalk results. Resolved
        # at construction (activity-runtime code) so it's snapshot-stable
        # for the life of the retriever; opt-out via AgentSettings.
        self._filter_polarity_temporal = filter_polarity_temporal

    @classmethod
    def for_store(
        cls,
        store,
        *,
        similarity_top_k: int = 10,
        filter_polarity_temporal: bool = True,
    ) -> GraphRetriever:
        """Build a retriever backed by a KbGraphStore (structured_query +
        subgraph): awalk / afind_entities_by_name / aretrieve all run over
        nGQL (aretrieve seeds via Milvus kNN + the entity table)."""
        return cls(
            store,
            similarity_top_k=similarity_top_k,
            filter_polarity_temporal=filter_polarity_temporal,
        )

    async def aretrieve(
        self, query: str, *, path_depth: int | None = None,
    ) -> RoundGraphData:
        """Similarity retrieval over the KG. ``path_depth`` overrides how
        many hops ``awalk`` expands around each matched entity (None ⇒ 1;
        clamped to ``[1, GRAPH_WALK_MAX_HOPS]`` by the walk)."""
        return await self._aretrieve_nebula(query, path_depth)

    async def awalk(
        self,
        start_entity: str,
        *,
        hops: int = 2,
        rel_filter: list[str] | None = None,
    ) -> RoundGraphData:
        """Bounded N-hop traversal from ``start_entity``.

        Distinct from ``aretrieve`` (which is similarity-based). This
        issues one bounded nebula ``subgraph`` call against the store:

          * ``hops`` is clamped to ``GRAPH_WALK_MAX_HOPS``.
          * ``rel_filter`` restricts the returned relations to the given
            labels (empty ⇒ all).
          * Python-side truncation guarantees at most
            ``GRAPH_WALK_NODE_CAP`` nodes / ``GRAPH_WALK_EDGE_CAP`` edges.

        Returns the same ``RoundGraphData`` shape as ``aretrieve`` so
        callers serialise identically. Empty on any failure / missing
        store (best-effort — never raises through the tool boundary).
        """
        if self._graph_store is None:
            return RoundGraphData()

        safe_hops = max(1, min(int(hops), GRAPH_WALK_MAX_HOPS))
        try:
            rows = await asyncio.to_thread(
                self._graph_store.subgraph, entity_vid(start_entity), safe_hops,
            )
        except Exception as exc:
            logger.warning("graph_walk (nebula) failed: {e}", e=repr(exc))
            return RoundGraphData()
        out = self._map_walk_rows(rows)
        if rel_filter:
            allow = set(rel_filter)
            out.relations = [r for r in out.relations if r.get("label") in allow]
        return out

    async def _nebula_knn_names(self, query: str) -> list[str]:
        """Embed the query and kNN over ``er_vec`` (Milvus entity vectors),
        returning the matched entity names."""
        from src.graph.entity_vector_store import build_entity_vector_store
        from src.ingestion.embeddings import build_embedding_model

        vec = await build_embedding_model().aget_text_embedding(query)
        evs = build_entity_vector_store(self._graph_store.graph)
        cands = await asyncio.to_thread(evs.knn, vec, self._similarity_top_k)
        # EntityCandidate is a TypedDict (a dict), not an attr object.
        return [c.get("name") for c in cands if isinstance(c, dict) and c.get("name")]

    async def _entity_table_names(self, query: str) -> list[dict]:
        """Lexical seeds from the Postgres entity mirror. Fail-soft: an
        outage here just means the vector path stands alone."""
        try:
            from src.storage.entity_search import EntitySearchRepository
            return await EntitySearchRepository(graph=self._graph_store.graph).search(
                query, mode="substring", limit=self._similarity_top_k,
            )
        except Exception as exc:
            logger.warning("entity-table seed failed (vector-only): {e}", e=repr(exc))
            return []

    async def _aretrieve_nebula(
        self, query: str, path_depth: int | None,
    ) -> RoundGraphData:
        """graph_search under nebula: union vector kNN (``er_vec`` in Milvus)
        and lexical hits from the Postgres entity mirror, then
        subgraph-expand each matched entity via ``awalk``. There is no
        LlamaIndex PropertyGraphIndex retriever here. Fail-soft — a vector
        or table outage degrades to the other path, not to empty."""
        if self._graph_store is None or not (query or "").strip():
            return RoundGraphData()
        try:
            knn_names = await self._nebula_knn_names(query)
        except Exception as exc:  # embed / vector-store / kNN failure
            logger.warning("aretrieve (nebula) entity kNN failed: {e}", e=repr(exc))
            knn_names = []
        table_rows = await self._entity_table_names(query)
        names = list(dict.fromkeys(
            [*knn_names, *[r["name"] for r in table_rows if r.get("name")]]
        ))

        hops = path_depth if path_depth is not None else 1
        out = RoundGraphData()
        for name in names:
            sub = await self.awalk(name, hops=hops)
            out.entities.extend(sub.entities)
            out.relations.extend(sub.relations)
        out.entities = _dedupe_entities(out.entities)
        return out

    async def afind_entities_by_name(
        self, query: str, *, limit: int | None = None,
    ) -> RoundGraphData:
        """Prefix lookup of entities by (partial) name.

        Complements ``aretrieve`` (vector + entity table): catches
        "Иванов" → "Иванов Иван Иванович" via the ``entity_name_idx``
        index (see ``_find_by_name_ngql``).  Best-effort — empty on a
        missing store / blank query; a failed lookup returns an empty
        result carrying ``error`` (never raises)."""
        if self._graph_store is None:
            return RoundGraphData()
        cap = limit if limit is not None else self._similarity_top_k
        ngql = _find_by_name_ngql(query, limit=int(cap))
        if not ngql:  # blank query -> nothing to look up
            return RoundGraphData()
        try:
            rows = await asyncio.to_thread(
                self._graph_store.structured_query, ngql,
            )
        except Exception as exc:
            logger.warning("find_entities_by_name (nebula) failed: {e}", e=repr(exc))
            # Report it. Returning a bare empty result told the caller
            # "no such entity" when the truth was "the lookup could
            # not run".
            return RoundGraphData(error=str(exc)[:200])
        out = RoundGraphData()
        for row in (rows or [])[: int(cap)]:
            # LOOKUP yields flat columns; accept the older `p` map too
            # so a caller or fake feeding either shape still works.
            p = (row or {}).get("p") or row or {}
            name = p.get("name")
            if not name:
                continue
            out.entities.append({
                "entity_name": name,
                "entity_type": p.get("label") or "",
                "description": p.get("description") or "",
            })
        out.entities = _dedupe_entities(out.entities)
        return out

    def _map_rel(self, rel: dict) -> dict | None:
        """Map one walk-relation dict → mapped row, or ``None`` if it is
        filtered out (negated / expired) and filtering is enabled.

        Exposes ``polarity`` / ``valid_from`` / ``valid_to`` on the kept
        rows so downstream can still reason over a hedged ('uncertain')
        edge even though negated/expired ones never reach it.
        """
        if self._filter_polarity_temporal and not _relation_is_live(
            rel, now_iso=date.today().isoformat(),
        ):
            return None
        return {
            "src_id": rel.get("src") or "",
            "tgt_id": rel.get("tgt") or "",
            "label": rel.get("label") or "",
            "polarity": rel.get("polarity"),
            "valid_from": rel.get("valid_from"),
            "valid_to": rel.get("valid_to"),
        }

    def _map_walk_rows(self, rows: list[dict] | None) -> RoundGraphData:
        """Map the walk rows (``[{entities, relations}]``) into ``RoundGraphData``.

        Defensive caps re-applied here — the subgraph call has no LIMIT.
        """
        out = RoundGraphData()
        for row in rows or []:
            for ent in (row.get("entities") or []):
                name = ent.get("name")
                if not name:
                    continue
                out.entities.append({
                    "entity_name": name,
                    "entity_type": ent.get("label") or "",
                    "description": ent.get("description") or "",
                })
            for rel in (row.get("relations") or []):
                mapped = self._map_rel(rel)
                if mapped is not None:
                    out.relations.append(mapped)
        out.entities = _dedupe_entities(out.entities)[:GRAPH_WALK_NODE_CAP]
        out.relations = _dedupe_relations(out.relations)[:GRAPH_WALK_EDGE_CAP]
        return out


def _dedupe_entities(entities: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for e in entities:
        key = e["entity_name"]
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _dedupe_relations(relations: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    out: list[dict] = []
    for r in relations:
        key = (r["src_id"], r["tgt_id"], r["label"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out
