"""Process-level cache for search-side dependencies inside Temporal
activities.

Activities re-enter Python on each invocation; building a Milvus
client + connecting to Nebula + bootstrapping the BGE-reranker from
scratch on every ReAct step would multiply latency.  We memoise per
worker process — first activity in this worker builds them, all
subsequent calls reuse.

Graph-agnostic deps (LLMs, synthesizers, embed model, reranker) are cached
once per process in ``_global``; graph-scoped deps (vector index/retriever,
graph retriever, chunk repository) are cached per ``graph.id`` in
``_per_graph`` — every graph-scoped getter takes a ``GraphContext``.

Lock-protected so concurrent activity workers don't race the lazy
init.  Reset hooks left out — workers restart cleanly enough; if
the underlying store config changes the operator restarts the
worker.

All builders obtain their LLM from the shared per-process ``LLMPool``
(``src/retrieval/llm_pool.py``) — still BoundedLLM-gated under the
hood — so concurrent activities share one GPU semaphore.
"""

from __future__ import annotations

import asyncio
from typing import Any

from llama_index.core.llms import LLM
from loguru import logger

from src.retrieval.atomic_tools import (
    GraphRetrieverProtocol,
    RetrieverProtocol,
)
from src.tenancy.context import GraphContext

# The unified rerank now owns the top_n cut (after group weighting), so the
# cached cross-encoder is built as a pure SCORER that never truncates below
# this cap. Pools are bounded (top_k × sub-questions + graph + walk); 256 is
# comfortably above any real pool.
_RERANK_SCORE_CAP = 256

_lock = asyncio.Lock()

# Graph-agnostic deps — one per worker process: LLMs, synthesizers, the
# embed model, the reranker (and its ``reranker_failed`` fail-soft flag).
_GLOBAL_KEYS = (
    "llm", "synthesizer", "synthesis_llm", "synthesis_synthesizer",
    "reranker", "_embed_model",
)
_global: dict[str, Any] = dict.fromkeys(_GLOBAL_KEYS)

# Graph-scoped deps keyed by ``graph.id``: retriever, ``_vector_index``,
# ``graph_retriever`` (+ its per-graph ``graph_retriever_attempted`` flag),
# ``chunk_repository``.  Each inner dict is created lazily by ``_slot``.
_per_graph: dict[str, dict[str, Any]] = {}


def _slot(graph: GraphContext) -> dict[str, Any]:
    """The per-graph cache dict for ``graph`` (created on first touch).
    Plain dict ops, no await — safe to call with or without ``_lock``."""
    slot = _per_graph.get(graph.id)
    if slot is None:
        slot = _per_graph[graph.id] = {
            "retriever": None, "_vector_index": None,
            "graph_retriever": None, "chunk_repository": None,
        }
    return slot


def _get_embed_model():
    """Process-global embed model (graph-agnostic).  Caller holds ``_lock``."""
    if _global["_embed_model"] is None:
        from src.ingestion.embeddings import build_embedding_model
        _global["_embed_model"] = build_embedding_model()
    return _global["_embed_model"]


async def _build_retriever_once(graph: GraphContext):
    """Build ``graph``'s vector index + default retriever.  Caller holds
    ``_lock``.  The index is stashed so per-request retrievers at a custom
    top_k (the date over-fetch path) reuse it without rebuilding the Milvus
    client."""
    from src.retrieval.vector_index import build_vector_index, build_vector_store
    embed = _get_embed_model()
    store = build_vector_store(graph)
    index = build_vector_index(store, embed)
    slot = _slot(graph)
    slot["_vector_index"] = index
    return index.as_retriever(similarity_top_k=10), embed


async def _build_graph_retriever_once(graph: GraphContext, embed_model, llm):
    """Returns None when the graph store is unreachable — graph-tools handle this.

    ``embed_model`` / ``llm`` are unused: Nebula has no LlamaIndex
    PropertyGraphStore, so the retriever works over nGQL (awalk/afind)."""
    try:
        from src.config import settings
        from src.graph.retriever import GraphRetriever
        from src.graph.store import build_graph_store
        gs = build_graph_store(graph)
        return GraphRetriever.for_store(
            gs,
            similarity_top_k=settings.agent.graph_similarity_top_k,
            filter_polarity_temporal=(
                settings.agent.graph_walk_filter_polarity_temporal
            ),
        )
    except Exception as exc:
        logger.warning(
            "search_deps: graph_retriever disabled for graph {g} "
            "(graph store unreachable?): {e}",
            g=graph.id, e=exc,
        )
        return None


async def _build_chunk_repo_once(graph: GraphContext):
    from src.storage.chunk_repository import ChunkRepository
    from src.storage.postgres import AsyncPostgres
    return ChunkRepository(graph=graph, pg=AsyncPostgres(graph=graph))


async def _build_synthesizer_once(llm):
    from llama_index.core import get_response_synthesizer
    from llama_index.core.response_synthesizers.type import ResponseMode
    return get_response_synthesizer(
        llm=llm, response_mode=ResponseMode.COMPACT,
    )


async def get_search_llm() -> LLM:
    """Project search-role LLM from the shared per-process LLM pool.

    Process-global (graph-agnostic); memoised here — ``pool.get`` is a
    synchronous dict lookup, so no lock/await is needed."""
    if _global["llm"] is None:
        from src.retrieval.llm_pool import get_llm_pool
        _global["llm"] = get_llm_pool().get("search")
    return _global["llm"]


async def get_retriever(graph: GraphContext) -> RetrieverProtocol:
    async with _lock:
        slot = _slot(graph)
        if slot["retriever"] is None:
            ret, _ = await _build_retriever_once(graph)
            slot["retriever"] = ret
    return slot["retriever"]


async def get_vector_retriever(
    graph: GraphContext, top_k: int, filters: Any | None = None,
) -> RetrieverProtocol:
    """Per-request vector retriever at a custom ``similarity_top_k`` over
    ``graph``'s chunk collection.

    Used by the date-filter path (``retrieve_subquestion``). ``filters`` is
    a Milvus ``MetadataFilters`` push-down: WITHOUT it the vector search
    ranks the globally-most-similar chunks and a post-filter then drops the
    out-of-range ones — which starves the in-range pool when the corpus
    spans many dates (the relevant same-date chunks never enter the global
    top-k). Pushing the date bound INTO the Milvus search makes it rank the
    top-k among only in-range chunks. Over-fetch still applies so the merged
    pool (vector + graph + walk) has candidates for rerank. Reuses the
    cached per-graph vector index — ``as_retriever`` is an in-memory wrap
    (no Milvus rebuild), so building one per request is cheap."""
    async with _lock:
        slot = _slot(graph)
        if slot["_vector_index"] is None:
            ret, _ = await _build_retriever_once(graph)
            if slot["retriever"] is None:
                slot["retriever"] = ret
        index = slot["_vector_index"]
    return index.as_retriever(similarity_top_k=top_k, filters=filters)


async def get_graph_retriever(graph: GraphContext) -> GraphRetrieverProtocol | None:
    """Per-graph graph retriever.  The build is attempted ONCE per graph
    (``graph_retriever_attempted`` lives in the graph's slot): an
    unreachable store for one graph caches ``None`` for that graph only."""
    slot = _slot(graph)
    if slot["graph_retriever"] is not None or "graph_retriever_attempted" in slot:
        return slot["graph_retriever"]
    # Resolve the (process-global) LLM before taking _lock.
    llm = await get_search_llm()
    async with _lock:
        if "graph_retriever_attempted" in slot:
            return slot["graph_retriever"]
        embed = _get_embed_model()
        slot["graph_retriever"] = await _build_graph_retriever_once(
            graph, embed, llm,
        )
        slot["graph_retriever_attempted"] = True
    return slot["graph_retriever"]


async def get_chunk_repository(graph: GraphContext):
    async with _lock:
        slot = _slot(graph)
        if slot["chunk_repository"] is None:
            slot["chunk_repository"] = await _build_chunk_repo_once(graph)
    return slot["chunk_repository"]


async def get_synthesizer():
    # Resolve the LLM before taking _lock (pool.get is non-blocking).
    llm = await get_search_llm()
    async with _lock:
        if _global["synthesizer"] is None:
            _global["synthesizer"] = await _build_synthesizer_once(llm)
    return _global["synthesizer"]


async def get_synthesis_llm() -> LLM:
    """Large-tier final-synthesis LLM from the shared per-process pool."""
    from src.retrieval.llm_pool import get_llm_pool
    return get_llm_pool().get("synthesis")


async def get_synthesis_synthesizer():
    """ResponseSynthesizer bound to the large tier (R2)."""
    # Resolve the LLM before taking _lock (pool.get is non-blocking).
    llm = await get_synthesis_llm()
    async with _lock:
        if _global["synthesis_synthesizer"] is None:
            _global["synthesis_synthesizer"] = await _build_synthesizer_once(llm)
    return _global["synthesis_synthesizer"]


async def get_reranker(top_n: int | None = None):
    """Process-cached bge cross-encoder (Search R5 unified rerank).

    Heavy: pulls ``sentence-transformers`` and downloads
    ``BAAI/bge-reranker-v2-m3`` on first use — memoised per worker
    process so the unified rerank pass before synthesis doesn't reload
    it.  The cached instance is always built as a pure SCORER sized to
    ``_RERANK_SCORE_CAP`` (never pre-cuts below it) — the rerank
    activity applies per-group weighting and then owns the final
    ``top_n`` cut.  ``top_n`` is kept as a parameter for signature
    compatibility but is no longer used to size the build."""
    async with _lock:
        # Fail-soft: the reranker pulls sentence-transformers + torch, which are
        # heavy and may be absent from a lean deploy image (e.g. no linux-arm64
        # torch wheel). Rerank is OPTIONAL — on a missing dep, cache the failure
        # (so we don't re-attempt the import every call) and return None; the
        # rerank activity then skips reranking and returns the pool as-is.
        if _global.get("reranker_failed"):
            return None
        if _global["reranker"] is None:
            from src.retrieval.reranker import build_reranker
            try:
                _global["reranker"] = build_reranker(top_n=_RERANK_SCORE_CAP)
            except Exception as exc:  # ImportError (no torch) or model-load failure
                from loguru import logger
                logger.warning(
                    "reranker unavailable — search continues WITHOUT rerank: {e}", e=exc,
                )
                _global["reranker_failed"] = True
                return None
    return _global["reranker"]


def reset_for_tests() -> None:
    """Test hook — clear the global AND per-graph caches.  Production code
    never calls."""
    _global.clear()
    _global.update(dict.fromkeys(_GLOBAL_KEYS))
    _per_graph.clear()
