"""Relevance ranking of graph tool results (dense prefilter → cross-encoder)."""
from __future__ import annotations

import json

import pytest

from src.retrieval import atomic_tools
from src.retrieval.graph_rank import GraphRanker, entity_text

ENTS = [
    {"entity_name": "ТАСС / Москва", "entity_type": "Organization", "description": "агентство"},
    {"entity_name": "Rosatom", "entity_type": "Organization", "description": "госкорпорация"},
    {"entity_name": "Пакш-2", "entity_type": "Other", "description": "АЭС в Венгрии"},
    {"entity_name": "Александр Ушаков", "entity_type": "Other", "description": ""},
]
RELS = [
    {"src_id": "Алексей Лихачёв", "tgt_id": "ТАСС / Москва", "label": "MENTIONED_IN", "description": ""},
    {"src_id": "Алексей Лихачёв", "tgt_id": "Rosatom", "label": "HEADS", "description": ""},
    {"src_id": "Алексей Лихачёв", "tgt_id": "Пакш-2", "label": "RELATED", "description": ""},
]


def score_by(keyword_weights):
    calls = []

    async def scorer(query, texts):
        calls.append(len(texts))
        return [sum(w for k, w in keyword_weights.items() if k in t) for t in texts]
    scorer.calls = calls
    return scorer


def test_entity_text_is_name_type_description():
    assert entity_text(ENTS[2]) == "Пакш-2 (Other): АЭС в Венгрии"
    assert entity_text({"entity_name": "X"}) == "X"


@pytest.mark.asyncio
async def test_rerank_orders_entities_and_relations_by_relevance():
    ranker = GraphRanker(rerank=score_by({"госкорпорация": 3, "АЭС": 2}), rerank_keep=10)
    ents, rels = await ranker.rank("чем руководит", ENTS, RELS)
    assert [e["entity_name"] for e in ents][:2] == ["Rosatom", "Пакш-2"]
    assert ents[0]["relevance"] == 3.0
    assert [r["tgt_id"] for r in rels] == ["Rosatom", "Пакш-2", "ТАСС / Москва"]


@pytest.mark.asyncio
async def test_prefilter_bounds_what_the_cross_encoder_sees():
    rerank = score_by({"Rosatom": 1})
    ranker = GraphRanker(prefilter=score_by({"госкорпорация": 5, "АЭС": 4}), rerank=rerank,
                         prefilter_keep=2, rerank_keep=10)
    ents, _ = await ranker.rank("q", ENTS, [])
    assert rerank.calls == [2]  # only the dense top-2 went to the cross-encoder
    assert [e["entity_name"] for e in ents][:2] == ["Rosatom", "Пакш-2"]
    assert len(ents) == 4  # the rest keeps its place after the ranked head


@pytest.mark.asyncio
async def test_a_failing_scorer_leaves_the_order_unchanged():
    async def boom(query, texts):
        raise RuntimeError("model down")
    ents, rels = await GraphRanker(rerank=boom).rank("q", ENTS, RELS)
    assert ents == ENTS and rels == RELS


class _G:
    def __init__(self, data):
        self.data = data

    async def aretrieve(self, q, path_depth=1):
        return self.data


class _Data:
    def __init__(self):
        self.entities, self.relations, self.chunks = list(ENTS), list(RELS), []


@pytest.mark.asyncio
async def test_find_neighbours_ranks_by_the_question_when_given():
    ranker = GraphRanker(rerank=score_by({"госкорпорация": 3}))
    r = await atomic_tools.find_neighbours(_G(_Data()), entity_name="Алексей Лихачёв",
                                           query="чем руководит", ranker=ranker)
    assert json.loads(r.observation)["entities"][0]["entity_name"] == "Rosatom"
    r = await atomic_tools.find_neighbours(_G(_Data()), entity_name="Алексей Лихачёв")
    assert json.loads(r.observation)["entities"][0]["entity_name"] == "ТАСС / Москва"


@pytest.mark.asyncio
async def test_graph_search_ranks_by_its_query():
    ranker = GraphRanker(rerank=score_by({"АЭС": 3}))
    r = await atomic_tools.graph_search(_G(_Data()), query="атомные станции", ranker=ranker)
    assert json.loads(r.observation)["entities"][0]["entity_name"] == "Пакш-2"


@pytest.mark.asyncio
async def test_vector_search_applies_the_chunk_reranker_before_top_k():
    from llama_index.core.schema import NodeWithScore, TextNode

    nodes = [NodeWithScore(node=TextNode(id_=f"n{i}", text=f"t{i}"), score=1.0 - i / 10)
             for i in range(6)]

    class _R:
        async def aretrieve(self, q):
            return nodes

    async def rerank(query, pool, top_k):
        return list(reversed(pool))[:top_k]

    r = await atomic_tools.vector_search(_R(), query="q", top_k=2, rerank=rerank)
    assert [s["chunk_id"] for s in json.loads(r.observation)] == ["n5", "n4"]
    r = await atomic_tools.vector_search(_R(), query="q", top_k=2)
    assert [s["chunk_id"] for s in json.loads(r.observation)] == ["n0", "n1"]


@pytest.mark.asyncio
async def test_neighbours_rank_by_the_edge_to_the_centre_not_by_look_alike_names():
    seen = []

    async def scorer(query, texts):
        seen.append((query, texts))
        # a name-similarity bias (the real failure) plus a reward for a HEADS edge
        return [(0.6 if "HEADS" in t else 0.0) + (0.3 if "Чихачев" in t else 0.0)
                for t in texts]

    data = _Data()
    data.entities = [{"entity_name": "Алексей Лихачев", "entity_type": "Person"},
                     {"entity_name": "Алексей Чихачев", "entity_type": "Person"}, *ENTS]
    r = await atomic_tools.find_neighbours(_G(data), entity_name="Алексей Лихачёв",
                                           query="с кем связан Алексей Лихачёв",
                                           ranker=GraphRanker(rerank=scorer))
    out = json.loads(r.observation)
    names = [e["entity_name"] for e in out["entities"]]
    # the centre (ё/е-insensitive) stays first; the edge-bearing Rosatom beats the look-alike
    assert names[:3] == ["Алексей Лихачев", "Rosatom", "Алексей Чихачев"]
    query, texts = seen[0]
    assert "Лихачёв" in query  # the question is not stripped of the centre's name
    assert "Rosatom (Organization) | связь с Алексей Лихачёв: HEADS: госкорпорация" in texts
    assert "Алексей Чихачев (Person) | нет прямой связи с Алексей Лихачёв" in texts
    assert out["centre_found"] is True and out["ranked"] is True


@pytest.mark.asyncio
async def test_missing_centre_is_reported_with_the_closest_names():
    data = _Data()
    data.entities = [{"entity_name": "Российский суд"}, {"entity_name": "Росатом-Сервис"}]
    r = await atomic_tools.find_neighbours(_G(data), entity_name="Росатом")
    out = json.loads(r.observation)
    assert out["centre_found"] is False and "Росатом-Сервис" in out["closest"]
    assert "нет в результате" in out["centre_note"]


@pytest.mark.asyncio
async def test_prefilter_runs_whenever_the_cross_encoder_would_not_see_everything():
    ents = [{"entity_name": f"e{i}", "description": "best" if i == 99 else ""}
            for i in range(100)]
    rerank = score_by({"best": 1})
    prefilter_seen = []

    async def prefilter(query, texts):
        prefilter_seen.append(len(texts))
        return [1.0 if "best" in t else 0.0 for t in texts]
    ranker = GraphRanker(prefilter=prefilter, rerank=rerank, prefilter_keep=128, rerank_keep=10)
    out, _ = await ranker.rank("q", ents, [])
    assert prefilter_seen == [100] and rerank.calls == [10]
    assert out[0]["entity_name"] == "e99" and out[0]["match"] == "strong"


@pytest.mark.asyncio
async def test_nothing_relevant_is_said_when_every_score_is_low():
    async def low(query, texts):
        return [0.02] * len(texts)
    ents, _, meta = await GraphRanker(rerank=low).rank_meta("люди", ENTS, RELS)
    assert {e["match"] for e in ents} == {"none"}
    assert meta["best_relevance"] == 0.02 and "ничего релевантного" in meta["relevance_note"]

    async def high(query, texts):
        return [0.97] + [0.01] * (len(texts) - 1)
    _, _, meta = await GraphRanker(rerank=high).rank_meta("q", ENTS, RELS)
    assert meta["best_relevance"] == 0.97 and "relevance_note" not in meta


@pytest.mark.asyncio
async def test_over_budget_ranking_keeps_the_store_order():
    import asyncio

    async def slow(query, texts):
        await asyncio.sleep(1)
        return [1.0] * len(texts)
    ents, rels, meta = await GraphRanker(rerank=slow, budget_s=0.05).rank_meta("q", ENTS, RELS)
    assert ents == ENTS and rels == RELS
    assert meta == {"ranked": False, "rank_timeout": True}


@pytest.mark.asyncio
async def test_a_wrong_length_scorer_result_is_logged_and_ignored():
    from loguru import logger
    msgs = []
    sink = logger.add(lambda m: msgs.append(str(m)), level="WARNING")
    try:
        async def short(query, texts):
            return [1.0]
        ents, _ = await GraphRanker(rerank=short).rank("q", ENTS, RELS)
    finally:
        logger.remove(sink)
    assert ents == ENTS and any("returned 1 scores for 4" in m for m in msgs)


@pytest.mark.asyncio
async def test_cross_encoder_loads_once_and_predicts_one_at_a_time(monkeypatch):
    import asyncio
    import threading
    import time

    from src.mcp import tools_server as ts

    built, inflight, peak = [], [0], [0]
    lock = threading.Lock()

    class _Model:
        def predict(self, pairs):
            with lock:
                inflight[0] += 1
                peak[0] = max(peak[0], inflight[0])
            time.sleep(0.05)
            with lock:
                inflight[0] -= 1
            return [0.5] * len(pairs)

    class _CE:
        _model = _Model()

    def build_reranker(top_n):
        time.sleep(0.05)
        built.append(top_n)
        return _CE()

    import src.retrieval.reranker as rr
    monkeypatch.setattr(rr, "build_reranker", build_reranker)
    monkeypatch.setattr(ts, "_RERANK_ON", True)
    monkeypatch.setattr(ts, "_deps", {})
    monkeypatch.setattr(ts, "_ce_slot", asyncio.Semaphore(1))
    await asyncio.gather(*(ts._cross_scores("q", ["a", "b"]) for _ in range(4)))
    assert len(built) == 1 and peak[0] == 1


@pytest.mark.asyncio
async def test_chunk_rerank_keeps_the_whole_pool_up_to_top_k(monkeypatch):
    from llama_index.core.schema import NodeWithScore, TextNode

    from src.mcp import tools_server as ts

    async def predict(pairs):
        return [float(i) for i in range(len(pairs))]
    monkeypatch.setattr(ts, "_predict", predict)
    nodes = [NodeWithScore(node=TextNode(id_=f"n{i}", text=f"t{i}"), score=1.0)
             for i in range(40)]
    out = await ts._rerank_chunks("q", nodes, 40)
    assert len(out) == 40 and out[0].node.id_ == "n39"
