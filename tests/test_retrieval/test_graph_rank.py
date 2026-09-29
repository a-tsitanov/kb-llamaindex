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
