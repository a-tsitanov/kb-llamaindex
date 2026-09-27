import src.workflow._search_deps as sd
from src.tenancy.context import default_graph_context, new_graph_context

# ``ChunkRepository`` / ``get_llm_pool`` are imported inside the builders in
# ``_search_deps`` (keeps worker import light), so patch the source modules.


async def test_chunk_repository_is_cached_per_graph(monkeypatch):
    sd.reset_for_tests()
    built = []

    class FakeRepo:
        def __init__(self, *, graph, **kw):
            built.append(graph.id)
            self.graph = graph
    monkeypatch.setattr("src.storage.chunk_repository.ChunkRepository", FakeRepo)
    a1 = await sd.get_chunk_repository(new_graph_context("acme"))
    a2 = await sd.get_chunk_repository(new_graph_context("acme"))
    d = await sd.get_chunk_repository(default_graph_context())
    assert a1 is a2 and a1 is not d
    assert built == ["acme", "default"]
    sd.reset_for_tests()


async def test_llm_stays_process_global(monkeypatch):
    sd.reset_for_tests()
    calls = []

    class Pool:
        def get(self, role):
            calls.append(role)
            return object()
    monkeypatch.setattr(
        "src.retrieval.llm_pool.get_llm_pool", lambda: Pool(), raising=False,
    )
    assert await sd.get_search_llm() is await sd.get_search_llm()
    sd.reset_for_tests()


async def test_concurrent_first_calls_build_once_per_graph(monkeypatch):
    """The per-graph lazy build stays lock-protected: N concurrent first
    calls for one graph build exactly one repo."""
    import asyncio

    monkeypatch.setattr(sd, "_lock", asyncio.Lock())
    sd.reset_for_tests()
    built = []

    async def _slow_build(graph):
        built.append(graph.id)
        await asyncio.sleep(0.01)
        return object()
    monkeypatch.setattr(sd, "_build_chunk_repo_once", _slow_build)
    g = new_graph_context("acme")
    repos = await asyncio.gather(*(sd.get_chunk_repository(g) for _ in range(5)))
    assert len({id(r) for r in repos}) == 1
    assert built == ["acme"]
    sd.reset_for_tests()


async def test_graph_retriever_attempt_is_per_graph(monkeypatch):
    """A failed (None) graph-retriever build is cached for THAT graph only."""
    import asyncio

    monkeypatch.setattr(sd, "_lock", asyncio.Lock())
    sd.reset_for_tests()
    attempts = []

    async def _llm():
        return object()

    async def _build(graph, embed, llm):
        attempts.append(graph.id)
        return None if graph.id == "acme" else object()
    monkeypatch.setattr(sd, "get_search_llm", _llm)
    monkeypatch.setattr(sd, "_get_embed_model", lambda: object())
    monkeypatch.setattr(sd, "_build_graph_retriever_once", _build)
    assert await sd.get_graph_retriever(new_graph_context("acme")) is None
    assert await sd.get_graph_retriever(new_graph_context("acme")) is None
    assert await sd.get_graph_retriever(default_graph_context()) is not None
    assert attempts == ["acme", "default"]
    sd.reset_for_tests()
