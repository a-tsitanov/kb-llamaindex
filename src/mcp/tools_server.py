"""MCP-2: atomic retrieval tools.

Exposes 8 of the raw retrieval functions from
``src/retrieval/atomic_tools.py`` directly as MCP tools — no
Temporal workflow in between (``filter_by_metadata`` is intentionally
omitted; it operates on an in-process accumulator that stateless
tool-call clients don't maintain).  Used when the MCP client (an LLM
running in Hermes Agent / Claude Desktop / Cursor / OpenWebUI) wants
to drive its own ReAct loop and just needs primitives.

Every tool carries an 1800s (30 min) execution timeout (FastMCP
``@mcp.tool(timeout=...)``, seconds) so a slow graph walk or cold
retriever can't hang a client indefinitely, while still letting the
heaviest legitimate calls finish.

GPU/LLM protection: every LLM call — including those inside
``graph_search`` / ``find_*`` (which use ``LLMSynonymRetriever`` for
query normalisation) — is served by the per-process ``LLMPool``
(``src/retrieval/llm_pool.py``, configured via ``settings.llm_pool``),
which keeps each role BoundedLLM-gated.  Concurrent MCP clients
automatically serialise behind it.

Run::

    # Stdio
    uv run python -m src.mcp.tools_server --transport stdio

    # Streamable HTTP (endpoint /mcp) — OpenWebUI etc.
    uv run python -m src.mcp.tools_server --transport http --port 9002
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import threading
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any

from fastmcp import FastMCP
from loguru import logger

from src.config import settings
from src.mcp._shared import (
    assert_api_key_env_set,
    build_sse_auth,
    log_banner,
    parse_args,
)
from src.retrieval import atomic_tools
from src.retrieval.graph_rank import GraphRanker
from src.stats.align import GRANULARITIES

mcp = FastMCP(
    name="kb-llamaindex-tools",
    instructions=(
        "Atomic retrieval tools over the project knowledge base.  "
        "Each tool returns a JSON-serialisable dict.  Compose them "
        "yourself in your own LLM loop.  For an already-orchestrated "
        "answer, use the sibling MCP-1 server (kb_search) instead."
    ),
    auth=build_sse_auth(),  # evaluated at import time; see build_sse_auth docstring
)


# ── lazy DI bootstrap ──────────────────────────────────────────────


_lock = asyncio.Lock()
_deps: dict[str, Any] = {}


async def _init() -> None:
    """First-call init: build retriever / graph_retriever /
    chunk_repository / BoundedLLM-wrapped LLM via the same factories
    used by the FastAPI route handlers and the Temporal search-side
    activities (see ``src/workflow/_search_deps.py``)."""
    # not "if _deps": the cross-encoder warm-up thread puts its model into _deps first
    if _deps.get("_ready"):
        return
    async with _lock:
        if _deps.get("_ready"):
            return
        from src.ingestion.embeddings import build_embedding_model
        from src.retrieval.vector_index import (
            build_vector_index,
            build_vector_store,
        )
        from src.storage.chunk_repository import ChunkRepository
        from src.storage.postgres import AsyncPostgres

        embed = build_embedding_model()
        store = build_vector_store()
        index = build_vector_index(store, embed)
        _deps["retriever"] = index.as_retriever(similarity_top_k=10)
        _deps["index"], _deps["embed"] = index, embed

        from src.retrieval.llm_pool import get_llm_pool
        llm = get_llm_pool().get("search")
        _deps["llm"] = llm

        try:
            from src.graph.index import (
                build_kg_extractor,
                build_property_graph_index,
            )
            from src.graph.retriever import GraphRetriever
            from src.graph.store import build_graph_store
            gs = build_graph_store()
            if settings.graph.backend == "nebula":
                # Nebula has no LlamaIndex PropertyGraphStore; use the
                # store-only retriever (nGQL awalk/find). Mirrors
                # _search_deps._get_graph_retriever. Vector/synonym aretrieve
                # is Phase 3.
                _deps["graph"] = GraphRetriever.for_store(
                    gs,
                    similarity_top_k=settings.agent.graph_similarity_top_k,
                    filter_polarity_temporal=(
                        settings.agent.graph_walk_filter_polarity_temporal
                    ),
                )
            else:
                pg = build_property_graph_index(
                    graph_store=gs, embed_model=embed,
                    extractor=build_kg_extractor(llm), nodes=None,
                    llm=llm,  # local LiteLLM model for the retriever's synonym step
                )
                _deps["graph"] = GraphRetriever(
                    pg,
                    filter_polarity_temporal=(
                        settings.agent.graph_walk_filter_polarity_temporal
                    ),
                )
            # Raw store for the GDS analysis tools (need structured_query).
            _deps["graph_store"] = gs
        except Exception as exc:
            logger.warning(
                "MCP-2: graph_retriever disabled (Neo4j down?): {e}",
                e=exc,
            )
            _deps["graph"] = None
            _deps["graph_store"] = None

        _deps["chunks"] = ChunkRepository(pg=AsyncPostgres())
        _deps["_ready"] = True


async def _r():
    await _init()
    return _deps["retriever"]


# ── relevance ranking (dense prefilter → bge cross-encoder) ───────────
# Needs the `rerank` image extra (sentence-transformers + CPU torch + the baked
# BAAI/bge-reranker-v2-m3). Without it the cross-encoder is skipped (fail-soft) and only
# the dense prefilter / the store order remain. MCP_TOOLS_RERANK=false turns it all off.
_RERANK_ON = os.environ.get("MCP_TOOLS_RERANK", "true").strip().lower() == "true"
# CPU cross-encoder ≈ 0.3 s per pair (measured 2026-10-01: 32 pairs 10 s, 16 pairs 4.7 s)
_RERANK_KEEP = int(os.environ.get("MCP_TOOLS_RERANK_KEEP", "16"))
_PREFILTER_KEEP = int(os.environ.get("MCP_TOOLS_PREFILTER_KEEP", "128"))
_VECTOR_POOL = int(os.environ.get("MCP_TOOLS_VECTOR_POOL", "30"))
_RANK_BUDGET_S = float(os.environ.get("MCP_TOOLS_RANK_BUDGET_S", "30"))
_CHUNK_CHARS = 1200
# graph_search depth / find_neighbours hops: 2 hops around a hub is thousands of vertices
# (live 2026-10-01: graph_search depth=2 timed out at 120 s, find_neighbours hops=2 took
# 55 s); multi-hop chains are graph_walk's job
_MAX_DEPTH = int(os.environ.get("MCP_TOOLS_MAX_DEPTH", "1"))


def _clamp_depth(asked: int) -> tuple[int, dict[str, Any]]:
    d = max(1, min(int(asked or 1), _MAX_DEPTH))
    note = ({"depth_note": f"глубина {asked} снижена до {d}: для цепочек используй graph_walk"}
            if int(asked or 1) > d else {})
    return d, note
_ce_lock = threading.Lock()  # tool calls run in parallel: load the 2 GB model once
_ce_slot = asyncio.Semaphore(1)  # one predict at a time: torch already uses every core


def _cross_encoder():
    if "cross_encoder" not in _deps:
        with _ce_lock:
            if "cross_encoder" not in _deps:
                try:
                    from src.retrieval.reranker import build_reranker
                    _deps["cross_encoder"] = build_reranker(top_n=_VECTOR_POOL)
                except Exception as exc:  # no torch in a lean image, model missing, ...
                    logger.warning("MCP-2: reranker unavailable, results stay unranked: {e}",
                                   e=exc)
                    _deps["cross_encoder"] = None
    return _deps["cross_encoder"]


async def _load_cross_encoder():
    return await asyncio.to_thread(_cross_encoder) if _RERANK_ON else None


def _cosine(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b, strict=False)) / (na * nb) if na and nb else 0.0


async def _dense_scores(query: str, texts: list[str]) -> list[float]:
    embed = _deps["embed"]
    q = await embed.aget_query_embedding(query)
    vs = await embed.aget_text_embedding_batch(texts)
    return [_cosine(q, v) for v in vs]


async def _predict(pairs: list[tuple[str, str]]) -> list[float]:
    ce = await _load_cross_encoder()
    if ce is None:
        raise RuntimeError("cross-encoder unavailable")
    async with _ce_slot:
        scores = await asyncio.to_thread(ce._model.predict, pairs)
    return [float(x) for x in scores]


async def _cross_scores(query: str, texts: list[str]) -> list[float]:
    return await _predict([(query, t) for t in texts])


async def _ranker() -> GraphRanker | None:
    if not _RERANK_ON:
        return None
    await _init()
    ce = await _load_cross_encoder()
    return GraphRanker(prefilter=_dense_scores, rerank=_cross_scores if ce else None,
                       prefilter_keep=_PREFILTER_KEEP, rerank_keep=_RERANK_KEEP,
                       budget_s=_RANK_BUDGET_S)


async def _rerank_chunks(query: str, nodes: list, top_k: int) -> list:
    """Cross-encoder order of the whole retrieved pool, cut to ``top_k`` (a pool larger than
    the reranker's own ``top_n`` is never silently truncated)."""
    if not nodes:
        return nodes
    # the same deadline as the graph ranker: over it vector_search keeps the dense order
    # (atomic_tools.vector_search catches the error); passages are cut — the cross-encoder
    # reads 512 tokens at most and the CPU cost grows with length
    scores = await asyncio.wait_for(
        _predict([(query, n.node.get_content()[:_CHUNK_CHARS]) for n in nodes]),
        _RANK_BUDGET_S)
    for n, s in zip(nodes, scores, strict=True):
        n.score = s
    return sorted(nodes, key=lambda n: -n.score)[:top_k]


async def _g():
    await _init()
    return _deps["graph"]


# ── name resolution (src/graph/name_resolution.py) ─────────────────
# Every name-taking tool resolves the name to ONE canonical entity first and reports it in
# `resolution`. MCP_TOOLS_RESOLVE=false restores the old per-tool matching.
_RESOLVE_ON = os.environ.get("MCP_TOOLS_RESOLVE", "true").strip().lower() == "true"


async def _resolver():
    if not _RESOLVE_ON:
        return None
    await _init()
    if "resolver" not in _deps:
        gs = _deps.get("graph_store")
        if gs is None or settings.graph.backend != "nebula":
            _deps["resolver"] = None
        else:
            from src.graph.name_resolution import NameResolver, nebula_fetch
            from src.storage.entity_lexicon import EntityLexicon
            _deps["resolver"] = NameResolver(EntityLexicon(), nebula_fetch(gs))
    return _deps["resolver"]


async def _resolve_all(names: list[str]) -> tuple[list[str], list[dict], list[dict]]:
    """→ (canonical names that resolved, every resolution, the ones that did not)."""
    resolver = await _resolver()
    if resolver is None:
        return list(names), [], []
    resolved, report, missing = [], [], []
    for n in names:
        res = await resolver.resolve(n)
        report.append(res.to_dict())
        if res.name is None:
            missing.append(res.to_dict())
        else:
            resolved.append(res.name)
    return resolved, report, missing


async def _c():
    await _init()
    return _deps["chunks"]


async def _gs():
    await _init()
    return _deps.get("graph_store")


# ── MCP tools (one per atomic_tools.* function) ────────────────────


@mcp.tool(timeout=1800)
async def vector_search(query: str, top_k: int = 10) -> dict[str, Any]:
    """Dense vector (embedding) semantic search over document chunks, re-ranked
    by a cross-encoder when available (a wider pool is retrieved and the best
    `top_k` kept). Returns the top_k chunks with text + metadata. Not keyword /
    BM25 search: exact rare terms may be missed — try `graph_search` too.

    USE FOR: factual / "what / how / why" questions answered by the text
    of documents. This is the default for content questions.
    NOT FOR: entity lookup or relationships — use the graph tools
    (`graph_search`, `find_entity_by_*`, `find_neighbours`, `graph_walk`).
    NEXT STEP: to read more around a good hit, call `get_chunks_by_doc_id`
    with its `doc_id`.
    """
    await _init()
    if await _load_cross_encoder() is not None:
        pool = _deps["index"].as_retriever(similarity_top_k=max(_VECTOR_POOL, top_k))
        r = await atomic_tools.vector_search(pool, query=query, top_k=top_k,
                                             rerank=_rerank_chunks)
    else:
        r = await atomic_tools.vector_search(await _r(), query=query, top_k=top_k)
    return {"sources": json.loads(r.observation)}


@mcp.tool(timeout=1800)
async def graph_search(query: str, depth: int = 1) -> dict[str, Any]:
    """Similarity search over the knowledge graph from a free-text query.
    Returns matched entities + their neighbours up to `depth` triplet-hops
    + related chunks.

    `depth`: 1 = matched nodes + immediate relations (larger values are cut
    to the server maximum, default 1 — use `graph_walk` for chains).
    USE FOR: graph / relationship questions when you have NO specific
    entity pinned yet — discovery ("что в графе связано с темой X").
    PREFER INSTEAD: `find_entity_by_id` (you have an exact identifier),
    `find_entity_by_name` (you have a partial name), `find_neighbours`
    (you have a known entity, want 1 hop), `graph_walk` (known entity,
    multi-hop chains). Entities come back most relevant to `query` first
    (`relevance` = cross-encoder score). Returns empty lists if the graph is
    unavailable."""
    depth, note = _clamp_depth(depth)
    r = await atomic_tools.graph_search(await _g(), query=query, depth=depth,
                                        ranker=await _ranker())
    return {**note, **json.loads(r.observation)}


@mcp.tool(timeout=1800)
async def graph_walk(
    start_entity: str, hops: int = 2, rel_filter: list[str] | None = None,
) -> dict[str, Any]:
    """Bounded MULTI-hop traversal following real relationships outward
    from a KNOWN start entity (hard-capped nodes / edges / hops).

    USE FOR: transitive connection / chain questions — "how is X linked
    to Y", "trace X's network N hops out". Optionally restrict to
    `rel_filter` relationship types. Returns entities + relations.
    NOT FOR: a single hop (use `find_neighbours`) or discovery without a
    start entity (use `graph_search` / `find_entity_by_name` first).
    `start_entity` is resolved to one graph entity first (`resolution` says which);
    an unknown or ambiguous name returns candidates and walks nothing."""
    r = await atomic_tools.graph_walk(
        await _g(), start_entity=start_entity, hops=hops,
        rel_filter=rel_filter, resolver=await _resolver(),
    )
    return json.loads(r.observation)


@mcp.tool(timeout=1800)
async def find_entity_by_id(
    name: str, entity_type: str | None = None,
) -> dict[str, Any]:
    """Exact pinpoint lookup by a precise identifier or canonical name
    (E.164 phone, INN, OGRN, SNILS, email, exact entity name).

    USE FOR: "whose number is +7…", "find INN 7707…" — when the user
    gives an exact identifier. One entity expected.
    PREFER INSTEAD: `find_entity_by_name` when you only have a partial /
    approximate name; `graph_search` for non-name semantic queries.
    Case, ё/е, a merged-away name and another script ("Rosatom" / «Росатом») still
    match; otherwise `status: not_found` with candidates."""
    r = await atomic_tools.find_entity_by_id(
        await _g(), name=name, entity_type=entity_type, resolver=await _resolver(),
    )
    return json.loads(r.observation)


@mcp.tool(timeout=1800)
async def find_entity_by_name(
    query: str, limit: int = 10,
) -> dict[str, Any]:
    """Entity lookup by NAME: exact, any case / ё-е, a name merged into another entity
    («Росатом» → "Rosatom"), the other script ("Likhachev"), a surname inside a full name
    ("Лихачев" → «Алексей Лихачёв»), a prefix or a close spelling. Each row says how it
    matched (`matched_via`, `score`); `resolution.chosen` is the best one. Pass the name
    only — not a question: extra words match unrelated names.

    USE FOR: resolving an approximate / partial name into canonical
    entities — usually the first step before drilling in with
    `find_neighbours` or `graph_walk`.
    PREFER INSTEAD: `find_entity_by_id` for an exact identifier;
    `graph_search` for non-name semantic queries. Returns entity rows
    only (no chunks)."""
    r = await atomic_tools.find_entity_by_name(
        await _g(), query=query, limit=limit, resolver=await _resolver(),
    )
    return json.loads(r.observation)


async def _edges_between(store: Any, a: str, b: str) -> list[dict[str, Any]]:
    """Live RELATED edges between two exact entity names (either direction)."""
    from datetime import date

    from src.graph.nebula_store import _q, entity_vid
    from src.graph.retriever import _relation_is_live
    va, vb = entity_vid(a), entity_vid(b)
    rows = await asyncio.to_thread(
        store.structured_query,
        f"GO FROM {_q(va)} OVER RELATED BIDIRECT WHERE id($$) == {_q(vb)} YIELD "
        "src(edge) AS s, properties(edge).rel_type AS label, "
        "properties(edge).polarity AS polarity, properties(edge).valid_to AS valid_to;")
    today = date.today().isoformat()
    return [{"src_id": a if r.get("s") == va else b, "tgt_id": b if r.get("s") == va else a,
             "label": r.get("label") or "RELATED", "polarity": r.get("polarity")}
            for r in rows or [] if _relation_is_live(r, now_iso=today)]


@mcp.tool(timeout=60)
async def relations_between(a: str, b: str) -> dict[str, Any]:
    """Graph relations between two entities, each resolved strictly (exact / case / alias /
    transliteration — no fuzzy guess). For clients that check a relation before drawing it;
    a model should use `find_neighbours`. Returns {relations: [{src_id, tgt_id, label}],
    resolution, unresolved?}."""
    resolver = await _resolver()
    gs = await _gs()
    if resolver is None or gs is None:
        return {"relations": [], "error": "name resolution unavailable"}
    report, names = [], []
    for n in (a, b):
        res = await resolver.resolve(n, strict=True)
        report.append(res.to_dict())
        names.append(res.name)
    if None in names:
        return {"relations": [], "resolution": report,
                "unresolved": [r["query"] for r, n in zip(report, names, strict=True) if n is None]}
    return {"relations": await _edges_between(gs, names[0], names[1]), "resolution": report}


@mcp.tool(timeout=120)
async def resolve_names(text: str) -> dict[str, Any]:
    """Names in a free-text request that are KB entities, with the entity each resolves to
    (exact / case / ё-е / merged-away name / other script / legal form / case ending — no
    fuzzy guesses). For clients that prepare a request before a model sees it; a model
    should use `find_entity_by_name`."""
    from src.graph.name_resolution import resolve_spans
    resolver = await _resolver()
    if resolver is None:
        return {"names": [], "error": "name resolution unavailable"}
    return {"names": await resolve_spans(resolver, text)}


@mcp.tool(timeout=1800)
async def find_neighbours(
    entity_name: str, hops: int = 1, query: str = "", types: list[str] | None = None,
) -> dict[str, Any]:
    """Neighbours + relations of a KNOWN entity, up to `hops` triplet-hops.

    `hops`: 1 = immediate neighbours (larger values are cut to the server
    maximum, default 1 — use `graph_walk` for chains).
    USE FOR: "who / what is connected to X", and as the core of an entity
    dossier.
    PREFER INSTEAD: `graph_walk` for deterministic edge-following with
    rel-type filtering; `graph_search` if the entity isn't pinned down
    yet; `find_entity_*` to resolve the entity first.
    Pass the user's question as `query` to get the neighbours most relevant to
    it first (a well-known person has hundreds of neighbours; without `query`
    they come in arbitrary order). `types` keeps only those entity types
    (e.g. ["Person"] for «люди, связанные с X»).
    `entity_name` is resolved to one graph entity first (`resolution`); an unknown or
    ambiguous name returns candidates and no neighbours. `relevance_note` means nothing
    matched the question well — do not present that list as the answer."""
    hops, note = _clamp_depth(hops)
    r = await atomic_tools.find_neighbours(
        await _g(), entity_name=entity_name, hops=hops, query=query,
        ranker=await _ranker() if query.strip() else None,
        resolver=await _resolver(), types=types,
    )
    return {**note, **json.loads(r.observation)}


@mcp.tool(timeout=1800)
async def get_chunks_by_doc_id(
    doc_id: str, limit: int = 50, offset: int = 0,
) -> dict[str, Any]:
    """Fetch chunks of ONE document by `doc_id`, in position order,
    paginated via `limit` / `offset`.

    USE FOR: expanding context around a `vector_search` hit within the
    same source, or reading a document chunk-by-chunk.
    REQUIRES: a `doc_id` you already have (from `vector_search` or graph
    results). For the whole raw file at once, see `read_full_document`."""
    r = await atomic_tools.get_chunks_by_doc_id(
        await _c(), doc_id=doc_id, limit=limit, offset=offset,
    )
    # Observation is either a JSON list of chunks or an error dict.
    try:
        return {"chunks": json.loads(r.observation)}
    except json.JSONDecodeError:
        return {"error": r.observation}


@mcp.tool(timeout=1800)
async def read_full_document(
    doc_id: str, max_chars: int = 20000,
) -> dict[str, Any]:
    """Raw full text of the original uploaded file (pre-chunk,
    pre-translation), capped at `max_chars`.

    USE FOR: tables, code, or short documents where chunk-level
    retrieval splits content badly.
    REQUIRES: a `doc_id`. For large documents prefer
    `get_chunks_by_doc_id` (this returns one big blob, truncated at
    `max_chars`)."""
    r = await atomic_tools.read_full_document(
        await _c(), doc_id=doc_id, max_chars=max_chars,
    )
    if r.observation.startswith("Error"):
        return {"error": r.observation}
    return {"text": r.observation}


# ── graph analysis tools (Track 7b — read-only GDS) ────────────────
#
# Diagnostic / exploratory, NOT retrieval: they run GDS algorithms over
# the whole __Entity__ graph (heavier, projection-backed) and are
# fail-soft — Neo4j/GDS down or unavailable yields a safe empty result,
# never an error.  `from src.graph import analysis` is module-level.


@mcp.tool(timeout=1800)
async def graph_pagerank(top_n: int = 20) -> dict[str, Any]:
    """Most CENTRAL entities in the whole graph by weighted PageRank.

    USE FOR: "who/what are the most important / connected entities" —
    a global importance ranking, not tied to a query.
    PREFER INSTEAD: `graph_personalized_pagerank` when you want
    importance *relative to* specific seed entities. Returns top_n
    {name, score}. Empty if Neo4j/GDS is unavailable."""
    from src.graph import analysis
    return {"top": await analysis.pagerank(await _gs(), top_n=top_n)}


@mcp.tool(timeout=1800)
async def graph_personalized_pagerank(
    seeds: list[str], top_n: int = 20,
) -> dict[str, Any]:
    """Entities most relevant to the SEED entities by seed-biased
    (personalized) PageRank.

    USE FOR: "what's most connected to X and Y" — centrality relative to
    `seeds` (entity names; each is resolved, see `resolution` / `unresolved`).
    Empty seeds → empty result. Returns top_n {name, score}; empty if the graph
    is unavailable."""
    from src.graph import analysis
    resolved, report, missing = await _resolve_all(seeds)
    out: dict[str, Any] = {"top": await analysis.personalized_pagerank(
        await _gs(), resolved, top_n=top_n,
    ) if resolved else []}
    if report:
        out["resolution"] = report
    if missing:
        out["unresolved"] = [m["query"] for m in missing]
    return out


@mcp.tool(timeout=1800)
async def graph_components() -> dict[str, Any]:
    """Weakly-connected-component count + size distribution of the graph.

    USE FOR: connectivity health — a large singleton fraction explains
    sparse/empty communities and weak multi-hop reach. Returns
    {component_count, distribution}; empty if Neo4j/GDS is unavailable."""
    from src.graph import analysis
    return await analysis.components(await _gs())


@mcp.tool(timeout=1800)
async def graph_shortest_path(
    source: str, target: str, max_hops: int = 6,
) -> dict[str, Any]:
    """Shortest undirected path between two entities.

    USE FOR: "how are X and Y connected" — the concrete chain of entities
    between them. Both names are resolved first (`resolution`); a name that
    does not resolve is listed in `unresolved`. Returns {path:[names], hops};
    {path:[], hops:-1} when there's no path (or the graph is unavailable)."""
    from src.graph import analysis
    resolved, report, missing = await _resolve_all([source, target])
    if missing:
        return {"path": [], "hops": -1, "resolution": report,
                "unresolved": [m["query"] for m in missing]}
    out = await analysis.shortest_path(
        await _gs(), resolved[0], resolved[1], max_hops=max_hops,
    )
    return {**out, "resolution": report} if report else out


@mcp.tool(timeout=1800)
async def graph_stats() -> dict[str, Any]:
    """Operational snapshot of the knowledge graph: entity / relationship
    counts, degree distribution (p50/p99/max), duplicate-name groups,
    community count.

    USE FOR: a quick health/size read of the graph.

    A field that could not be measured is `null`, NEVER 0, and the reason
    is under `errors` — do not read a null as "the graph has none of
    these". `source` says where the counts came from: `show_stats` means
    Nebula's own job results, exact but as old as `stats_computed_at`;
    `scan` means counted live. Degree and duplicate counts have no cheap
    equivalent and are `null` whenever the graph is too large to scan."""
    from src.graph import analysis
    return await analysis.graph_stats(await _gs())


# ── ingest statistics (Postgres `documents` pipeline) ──────────────
#
# NOT retrieval and NOT graph: a direct read over the `documents` table's
# per-channel / per-group processing state.  Deliberately BYPASSES _init()
# (no retriever/graph bootstrap needed for a plain Postgres aggregate) and
# calls AsyncPostgres — the SAME aggregation methods the /api/v1/stats REST
# routes and the message_stats CLI use, so all three surfaces report identical
# numbers.  The thin `_stats_by` / `_timeline` helpers hold the validation so
# they stay unit-testable without FastMCP tool-invocation internals.


async def _stats_by(
    group_by: str, since: str | None, until: str | None,
) -> dict[str, Any]:
    from datetime import date

    from src.storage.postgres import GROUP_BY_COLUMN, AsyncPostgres

    dimension = GROUP_BY_COLUMN.get(group_by)
    if dimension is None:
        return {"error": f"group_by must be one of {sorted(GROUP_BY_COLUMN)}"}
    try:
        s = date.fromisoformat(since) if since else None
        u = date.fromisoformat(until) if until else None
    except ValueError as exc:
        return {"error": f"since/until must be ISO YYYY-MM-DD: {exc}"}
    rows = await AsyncPostgres().status_counts_by(dimension, since=s, until=u)
    return {"group_by": group_by, "rows": rows}


async def _timeline(
    date_field: str, group_by: str | None, channel: str | None,
    group: str | None, since: str | None, until: str | None,
) -> dict[str, Any]:
    from datetime import date

    from src.storage.postgres import GROUP_BY_COLUMN, AsyncPostgres

    if date_field not in ("created_at", "doc_date"):
        return {"error": "date_field must be 'created_at' or 'doc_date'"}
    if group_by is not None and group_by not in GROUP_BY_COLUMN:
        return {"error": f"group_by must be one of {sorted(GROUP_BY_COLUMN)}"}
    try:
        s = date.fromisoformat(since) if since else None
        u = date.fromisoformat(until) if until else None
    except ValueError as exc:
        return {"error": f"since/until must be ISO YYYY-MM-DD: {exc}"}
    buckets = await AsyncPostgres().timeline_counts(
        date_field=date_field, group_by=group_by,
        channel=channel, group=group, since=s, until=u,
    )
    # `day` is a datetime.date → ISO-stringify for a JSON-safe payload.
    return {
        "date_field": date_field,
        "buckets": [{**b, "day": b["day"].isoformat()} for b in buckets],
    }


def _period_bounds(period: str, granularity: str) -> tuple[date, date]:
    """First and last day covered by a bucket key from
    ``epoch_days_to_period``."""
    if granularity == "year":
        y = int(period)
        return date(y, 1, 1), date(y, 12, 31)
    if granularity == "quarter":
        y, q = int(period[:4]), int(period[-1])
        m0 = 3 * (q - 1) + 1
        m1 = m0 + 2
        return date(y, m0, 1), date(y, m1, monthrange(y, m1)[1])
    if granularity == "month":
        y, m = int(period[:4]), int(period[5:7])
        return date(y, m, 1), date(y, m, monthrange(y, m)[1])
    start = date.fromisoformat(period)
    if granularity == "week":
        return start, start + timedelta(days=6)
    return start, start


def _period_in_window(
    period: str, granularity: str, since: str | None, until: str | None,
) -> bool:
    """Keep a bucket that OVERLAPS the window.

    Overlap rather than containment: a coarse bucket straddling a
    boundary still carries mentions from inside the window, and dropping
    it would silently lose them.  The previous implementation compared
    truncated ISO strings, which broke on quarter keys — ``'Q'`` sorts
    after every digit, so ``"2026-Q2"`` compared greater than every
    ``"YYYY-MM"`` bound.
    """
    start, end = _period_bounds(period, granularity)
    if since and end < date.fromisoformat(since):
        return False
    return not (until and start > date.fromisoformat(until))


# Backends whose store cannot serve `topic_trend` AT ALL.  The primitive
# calls `run_rows(store, cypher, {"topic": topic})`; nebula's
# `structured_query` raises NotImplementedError on a non-empty `param_map`
# (src/graph/nebula_store.py:268-272) and `run_rows` fail-softs every
# exception to `[]` (src/analytics/store_query.py:23-25).  The tool would
# therefore answer "0 mentions, ever" for every topic — indistinguishable
# from a real zero.  A missing answer is honest; a silent zero is not.
#
# DELETE THIS GUARD (and this constant) as soon as NebulaGraphStore binds
# nGQL parameters.  Nothing else needs to change.
_TOPIC_TREND_UNSUPPORTED_BACKENDS = frozenset({"nebula"})


async def _topic_trend(
    store: Any, topic: str, granularity: str,
    since: str | None, until: str | None, _fn: Any = None,
) -> dict[str, Any]:
    from datetime import date

    from src.analytics.primitives.dynamics import topic_trend as _primitive

    if not topic or not topic.strip():
        return {"error": "topic must be a non-empty string"}
    if granularity not in GRANULARITIES:
        return {"error": f"granularity must be one of {sorted(GRANULARITIES)}"}
    for name, value in (("since", since), ("until", until)):
        if value is not None:
            try:
                date.fromisoformat(value)
            except ValueError:
                return {"error": f"{name} must be ISO YYYY-MM-DD, got {value!r}"}
    if store is None:
        return {"error": "graph store unavailable"}
    if settings.graph.backend in _TOPIC_TREND_UNSUPPORTED_BACKENDS:
        return {"error": (
            f"topic_trend is unavailable on the {settings.graph.backend} graph "
            "backend: its query binds a parameter, which NebulaGraphStore "
            "does not support yet, and the analytics layer degrades that to "
            "an empty result — which would be reported as 'never mentioned'. "
            "No trend can be returned for any topic on this backend."
        )}
    fn = _fn or _primitive
    res = await fn(store, topic=topic.strip(), granularity=granularity)
    rows = []
    for r in res.rows:
        if not _period_in_window(r["period"], granularity, since, until):
            continue
        # `period` is a LABEL (`"2026-Q1"`, `"2026-03"`, `"2026"`), which
        # `date.fromisoformat` cannot parse.  MCP-3's `stat_align` wants
        # `{period_start, value}`, so emit those too — additively, and
        # from here, because this module is the one that knows both the
        # label format and the granularity.  MCP-3 must not learn either.
        rows.append({
            **r,
            "period_start": _period_bounds(r["period"], granularity)[0].isoformat(),
            "value": r["mentions"],
        })
    return {"topic": topic.strip(), "granularity": granularity, "rows": rows}


async def _polarity_evolution(
    store: Any, name: str | None, rel_type: str | None, _fn: Any = None,
) -> dict[str, Any]:
    """No `period_start`/`value` here, deliberately — see the tool docstring.

    Rows come from `build_dynamics_graph_ops(store).polarity_evolution`,
    which returns one row per (period, polarity) pair, not a series.  Its
    nebula implementation inlines literals into nGQL and passes no
    `param_map`, so it does NOT share `topic_trend`'s backend fault and
    is not guarded.
    """
    from src.analytics.primitives.dynamics import polarity_evolution as _primitive

    if not name and not rel_type:
        return {"error": "provide at least one of name / rel_type"}
    if store is None:
        return {"error": "graph store unavailable"}
    fn = _fn or _primitive
    res = await fn(store, name=name, rel_type=rel_type)
    return {"name": name, "rel_type": rel_type, "rows": res.rows}


@mcp.tool(timeout=120)
async def channel_message_stats(
    group_by: str = "channel",
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """Counts of INGESTED Telegram messages, grouped by source channel (or
    channel group), broken down by pipeline status (completed / pending /
    processing / failed / vector_only / skipped) plus a per-key total, sorted
    by total descending.

    USE FOR: "сколько сообщений обработано", "статистика по каналам", "how many
    posts per channel", pipeline-health questions (a channel's `pending` is its
    processing backlog). `group_by="channel"` (default) for per-channel;
    `group_by="group"` for per folder-group (news / analytics / …). Optional
    `since` / `until` are ISO `YYYY-MM-DD` bounds on ingest time (created_at).
    Documents with no channel tag are excluded.
    NOT FOR: message CONTENT / semantic search (use `vector_search`) or graph
    entities. NEXT STEP: for daily dynamics call `channel_message_timeline`."""
    return await _stats_by(group_by, since, until)


@mcp.tool(timeout=120)
async def channel_message_timeline(
    date_field: str = "created_at",
    group_by: str | None = None,
    channel: str | None = None,
    group: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """Daily counts of ingested Telegram messages — the ingest volume over
    time.

    USE FOR: "динамика ингеста", "сколько сообщений в день", ingest-trend
    questions. `date_field`: "created_at" (when processed, default) or
    "doc_date" (the post's original date). Optionally break out per key with
    `group_by="channel"|"group"`, and/or filter to a single `channel` /
    `group`. `since` / `until` are ISO `YYYY-MM-DD` bounds. Returns
    `{date_field, buckets:[{day, count[, key]}]}`, ordered by day.
    NOT FOR: per-channel status totals (use `channel_message_stats`)."""
    return await _timeline(date_field, group_by, channel, group, since, until)


@mcp.tool(timeout=1800)
async def topic_trend(
    topic: str,
    granularity: str = "month",
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """How often a topic is mentioned across ingested documents, per period
    — the channel-side ATTENTION series.

    USE FOR: "как часто писали про X", and as the channel-side input to
    the MCP-3 `stat_align` tool when comparing attention against a poll
    indicator.  `granularity`: day / week / month (default) / quarter /
    year.  `since` / `until` are ISO `YYYY-MM-DD` bounds applied to the
    returned buckets.  Returns `{topic, granularity, rows:[{period,
    mentions, period_start, value}]}`, where `period` is a human label
    (`"2026-Q1"`, `"2026-03"`) and `period_start` is that bucket's first
    day as an ISO date.  PASS THE ROWS STRAIGHT TO `stat_align`: it reads
    `period_start` and `value`, which is why both are here.
    If the graph backend cannot serve this query, you get `{"error": …}`
    rather than an empty series — do not read a missing answer as "this
    topic was never mentioned".
    NOT FOR: ingest volume (use `channel_message_timeline`) or message
    content (use `vector_search`)."""
    await _init()
    return await _topic_trend(
        _deps.get("graph_store"), topic, granularity, since, until,
    )


@mcp.tool(timeout=1800)
async def polarity_evolution(
    name: str | None = None, rel_type: str | None = None,
) -> dict[str, Any]:
    """How the polarity of an entity's relations shifts over time — the
    channel-side VALUATION series.

    USE FOR: "как менялось отношение к X". Provide at least one of
    `name` (entity) / `rel_type` (relation type).  Polarity is computed
    over graph EDGES, not per-message sentiment — it is a coarser signal
    than a poll's rating scale, so read it as direction rather than
    magnitude.

    NOT DIRECTLY USABLE BY `stat_align`, unlike `topic_trend`.  Rows are
    `{period, polarity, n}` — a per-polarity BREAKDOWN with several rows
    per period, not one series, and `period` is always a month label
    (`"2026-03"`) regardless of what you asked for.  There is no single
    `value` to align: which polarity counts as "the" series is a
    judgement, so this tool does not make it for you.  To compare tone
    against a poll you must pick one polarity, decide whether you want
    its count or its share of the period, and build `{period_start,
    value}` points yourself.
    NOT FOR: mention counts (use `topic_trend`, whose rows DO feed
    `stat_align` unchanged)."""
    await _init()
    report = None
    if name:
        resolved, report, missing = await _resolve_all([name])
        if missing:
            return {"name": name, "rel_type": rel_type, "rows": [],
                    "resolution": report[0]}
        name = resolved[0]
    out = await _polarity_evolution(
        _deps.get("graph_store"), name, rel_type,
    )
    return {**out, "resolution": report[0]} if report else out


# Note: filter_by_metadata is not exposed via MCP-2.  It only makes
# sense in the context of an existing accumulator, which atomic-MCP
# clients don't maintain — they pass each tool call as a fresh
# request and assemble context themselves.


# ── Entity watch (docs/superpowers/specs/2026-10-15-entity-watch-design.md) ─
# Subscriptions live in Postgres `watch`; the monitor sweep turns ingest
# journals into `watch_event` rows; these tools read them as a feed. One
# owner until the panel has users.

_OWNER = "default"
WATCH_KINDS: tuple[str, ...] = (
    "new_mention", "new_connection", "new_identifier", "new_event", "contradiction",
)


def _entity_search():
    from src.storage.entity_search import EntitySearchRepository

    return EntitySearchRepository()


def _watch_repo():
    from src.storage.watch import WatchRepository

    return WatchRepository()


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _candidate(row: dict[str, Any]) -> dict[str, Any]:
    return {k: row.get(k) for k in ("vid", "name", "label", "mention_count")}


async def _watch(name: str, kinds: list[str] | None, note: str) -> dict[str, Any]:
    bad = sorted(set(kinds or []) - set(WATCH_KINDS))
    if bad:
        return {"error": f"unknown kinds {bad}; expected a subset of {list(WATCH_KINDS)}"}
    search = _entity_search()
    hits = await search.search(name, mode="exact", limit=5)
    if len(hits) != 1:
        hits = await search.search(name, mode="substring", limit=10)
    if not hits:
        return {"status": "not_found", "query": name}
    if len(hits) > 1:
        return {"status": "ambiguous", "query": name,
                "candidates": [_candidate(h) for h in hits]}
    hit = hits[0]
    await _watch_repo().add_watch(_OWNER, hit["vid"], hit["name"], kinds=list(kinds or []), note=note)
    return {"status": "watching", "entity": _candidate(hit), "kinds": list(kinds or [])}


async def _unwatch(name_or_vid: str) -> dict[str, Any]:
    repo = _watch_repo()
    for w in await repo.list_watch(_OWNER):
        if name_or_vid in (w["entity_vid"], w["entity_name"]):
            await repo.remove_watch(_OWNER, w["entity_vid"])
            return {"status": "removed", "entity": w["entity_name"]}
    return {"status": "not_watched", "query": name_or_vid}


async def _watchlist() -> dict[str, Any]:
    return {"watches": _json_safe(await _watch_repo().list_watch(_OWNER))}


def build_feed_cards(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group feed events into one card per document (events without a
    document get a card each), cards ordered by their newest event."""
    cards: dict[str, dict[str, Any]] = {}
    for r in rows:
        doc = str(r["doc_id"]) if r.get("doc_id") else None
        key = doc or f"event:{r['id']}"
        card = cards.get(key)
        if card is None:
            path = r.get("doc_path") or ""
            card = cards[key] = {
                "doc_id": doc,
                "doc_title": path.rsplit("/", 1)[-1] if path else None,
                "doc_date": _json_safe(r.get("doc_date")),
                "link": settings.monitor.document_link.format(doc_id=doc) if doc else None,
                "latest": r["detected_at"],
                "events": [],
            }
        card["latest"] = max(card["latest"], r["detected_at"])
        card["events"].append({
            "id": r["id"], "entity": r["entity_name"], "kind": r["kind"],
            "why": r.get("why", ""), "detail": _json_safe(r.get("detail") or {}),
            "detected_at": _json_safe(r["detected_at"]),
            "acked": r.get("acked_at") is not None,
        })
    ordered = sorted(cards.values(), key=lambda c: c["latest"], reverse=True)
    for c in ordered:
        c["latest"] = _json_safe(c["latest"])
    return ordered


async def _watch_feed(include_acked: bool, limit: int) -> dict[str, Any]:
    repo = _watch_repo()
    rows = await repo.feed(_OWNER, include_acked=include_acked, limit=limit)
    await repo.mark_seen(_OWNER, [r["id"] for r in rows])
    return {"count": len(rows), "cards": build_feed_cards(rows)}


async def _ack(event_ids: list[int] | None, all_events: bool) -> dict[str, Any]:
    if not all_events and not event_ids:
        return {"error": "pass event_ids or all=true"}
    n = await _watch_repo().ack(_OWNER, event_ids=event_ids, all_events=all_events)
    return {"acked": n}


@mcp.tool(timeout=120)
async def kb_watch(name: str, kinds: list[str] | None = None, note: str = "") -> dict[str, Any]:
    """Put an entity (person, organisation, phone, …) on watch: new documents
    mentioning it, new connections / identifiers and contradicting facts then
    show up in `kb_watch_feed`.

    `name` is resolved against the KB entity table (exact, then fuzzy). One
    match ⇒ subscribed; several ⇒ returns `candidates` and subscribes to
    nothing — call again with the exact candidate name. `kinds` limits the
    events (new_mention, new_connection, new_identifier, new_event, contradiction);
    empty = all. `note` is a free-text reason. Only events detected after
    the subscription are shown."""
    return await _watch(name, kinds, note)


@mcp.tool(timeout=120)
async def kb_unwatch(name_or_vid: str) -> dict[str, Any]:
    """Remove an entity from the watchlist (by its watched name or vid)."""
    return await _unwatch(name_or_vid)


@mcp.tool(timeout=120)
async def kb_watchlist() -> dict[str, Any]:
    """List watched entities with their event kinds, note and since-when."""
    return await _watchlist()


@mcp.tool(timeout=120)
async def kb_watch_feed(include_acked: bool = False, limit: int = 50) -> dict[str, Any]:
    """What is new about watched entities: events grouped into one card per
    source document (title, date, `link` to GET the document — add
    `?variant=original` for the uploaded file). Unacknowledged events only
    unless `include_acked`. Acknowledge with `kb_ack`."""
    return await _watch_feed(include_acked, limit)


@mcp.tool(timeout=120)
async def kb_ack(event_ids: list[int] | None = None, all: bool = False) -> dict[str, Any]:
    """Mark feed events as read (`event_ids` from `kb_watch_feed`, or `all`)."""
    return await _ack(event_ids, all)


def main() -> None:
    args = parse_args()
    assert_api_key_env_set()
    log_banner(
        "kb-llamaindex-tools",
        transport=args["transport"], host=args["host"], port=args["port"],
    )
    if _RERANK_ON:  # warm the cross-encoder so the first ranked call does not pay the load
        threading.Thread(target=_cross_encoder, name="ce-warmup", daemon=True).start()
    if args["transport"] == "stdio":
        mcp.run(transport="stdio")
    else:
        # Streamable HTTP (modern MCP transport; endpoint `/mcp`).  Replaces
        # the legacy SSE transport for MCP-2.
        mcp.run(
            transport="http",
            host=args["host"], port=args["port"],
        )


if __name__ == "__main__":
    main()
