"""kb-tools with name resolution: resolve first, act on that one entity, report it; never walk
from a look-alike (the «Росатом» → «Российский суд» substitution)."""
import json

import pytest

from src.graph.name_resolution import NameResolver
from src.graph.retriever import RoundGraphData
from src.retrieval import atomic_tools
from src.retrieval.graph_rank import GraphRanker
from tests.test_graph.test_name_resolution import GRAPH, FakeLexicon, fetch_from


class FakeGraph:
    """awalk = the real neighbourhood of one vertex; aretrieve = the old seed-everything path."""

    def __init__(self):
        self.walked, self.retrieved = [], []

    async def awalk(self, name, hops=1, rel_filter=None, node_cap=50, edge_cap=100):
        self.caps = (node_cap, edge_cap)
        self.walked.append(name)
        if name != "Rosatom":
            return RoundGraphData()
        return RoundGraphData(
            entities=[{"entity_name": "Rosatom", "entity_type": "Organization"},
                      {"entity_name": "Алексей Лихачёв", "entity_type": "Person",
                       "description": "глава"},
                      {"entity_name": "Водители", "entity_type": "Group"},
                      {"entity_name": "Пакш-2", "entity_type": "Location"}],
            relations=[{"src_id": "Алексей Лихачёв", "tgt_id": "Rosatom", "label": "HEADS"},
                       {"src_id": "Алексей Лихачёв", "tgt_id": "Rosatom", "label": "WORKS_AT"},
                       {"src_id": "Rosatom", "tgt_id": "Водители", "label": "MENTIONS"},
                       {"src_id": "Rosatom", "tgt_id": "Пакш-2", "label": "BUILDS"}])

    async def aretrieve(self, q, path_depth=1):
        self.retrieved.append(q)
        return RoundGraphData(entities=[{"entity_name": "Российский суд"}])

    async def afind_entities_by_name(self, q, limit=None):
        return RoundGraphData(entities=[{"entity_name": "Росатом-Лукойл", "entity_type": ""}])


def resolver():
    return NameResolver(FakeLexicon(), fetch_from(GRAPH))


def obs(r):
    return json.loads(r.observation)


@pytest.mark.asyncio
async def test_neighbours_of_a_merged_away_name_are_the_canonical_entitys():
    g = FakeGraph()
    out = obs(await atomic_tools.find_neighbours(g, entity_name="Росатом", resolver=resolver()))
    assert g.walked == ["Rosatom"] and g.retrieved == []
    assert g.caps == (atomic_tools.NEIGHBOUR_NODES, atomic_tools.NEIGHBOUR_EDGES)
    assert out["resolution"]["chosen"]["name"] == "Rosatom" and out["centre_found"] is True
    assert "Алексей Лихачёв" in [e["entity_name"] for e in out["entities"]]


@pytest.mark.asyncio
async def test_unknown_or_ambiguous_centre_walks_nothing():
    g = FakeGraph()
    out = obs(await atomic_tools.find_neighbours(g, entity_name="Газпромнефть",
                                                 resolver=resolver()))
    assert out["resolution"]["status"] == "not_found" and out["entities"] == []
    assert "не найдено" in out["note"] and g.walked == [] and g.retrieved == []
    GRAPH["Лихачев Виктор"]["mention_count"] = 40
    try:
        out = obs(await atomic_tools.find_neighbours(g, entity_name="Лихачев",
                                                     resolver=resolver()))
    finally:
        GRAPH["Лихачев Виктор"]["mention_count"] = 2
    assert out["resolution"]["status"] == "ambiguous" and "неоднозначно" in out["note"]
    assert g.walked == []


@pytest.mark.asyncio
async def test_people_of_rosatom_type_filter_and_edge_order_for_a_vague_question():
    async def vague(query, texts):  # «люди»: the cross-encoder scores everything near zero
        return [0.01] * len(texts)
    out = obs(await atomic_tools.find_neighbours(
        FakeGraph(), entity_name="Росатом", query="люди", types=["Person"],
        ranker=GraphRanker(rerank=vague), resolver=resolver()))
    assert [e["entity_name"] for e in out["entities"]] == ["Rosatom", "Алексей Лихачёв"]
    assert out["relevance_note"] and out["types"] == ["Person"]
    out = obs(await atomic_tools.find_neighbours(
        FakeGraph(), entity_name="Росатом", query="с кем связан",
        ranker=GraphRanker(rerank=vague), resolver=resolver()))
    # two edges to the centre beat one when the question ranks nothing
    assert out["order"] == "edges_to_centre"
    assert out["entities"][1]["entity_name"] == "Алексей Лихачёв"


@pytest.mark.asyncio
async def test_find_entity_by_id_is_strict_and_offers_candidates():
    out = obs(await atomic_tools.find_entity_by_id(FakeGraph(), name="Росатом",
                                                   resolver=resolver()))
    assert [e["entity_name"] for e in out["entities"]] == ["Rosatom"]
    assert out["entities"][0]["matched_via"] == ["translit"]
    out = obs(await atomic_tools.find_entity_by_id(FakeGraph(), name="Лихачев",
                                                   resolver=resolver()))
    assert out["entities"] == [] and out["resolution"]["status"] == "not_found"
    assert out["candidates"][0]["entity_name"] == "Алексей Лихачёв"


@pytest.mark.asyncio
async def test_find_entity_by_name_ranks_resolver_hits_then_lookup():
    out = obs(await atomic_tools.find_entity_by_name(FakeGraph(), query="Лихачев", limit=5,
                                                     resolver=resolver()))
    names = [e["entity_name"] for e in out["entities"]]
    assert names[:2] == ["Алексей Лихачёв", "Лихачев Виктор"] and names[-1] == "Росатом-Лукойл"
    assert out["resolution"]["chosen"]["name"] == "Алексей Лихачёв"


@pytest.mark.asyncio
async def test_graph_walk_resolves_its_start():
    g = FakeGraph()
    out = obs(await atomic_tools.graph_walk(g, start_entity="РОСАТОМ", resolver=resolver()))
    assert g.walked == ["Rosatom"] and out["resolution"]["chosen"]["name"] == "Rosatom"


@pytest.mark.asyncio
async def test_without_a_resolver_the_old_paths_stay():
    g = FakeGraph()
    out = obs(await atomic_tools.find_neighbours(g, entity_name="Росатом"))
    assert g.retrieved == ["Росатом"] and "resolution" not in out


@pytest.mark.asyncio
async def test_a_people_question_filters_to_persons_and_a_timeout_orders_by_edges():
    async def slow(query, texts):
        import asyncio
        await asyncio.sleep(1)
        return [0.9] * len(texts)
    out = obs(await atomic_tools.find_neighbours(
        FakeGraph(), entity_name="Росатом", query="Выведи людей связанных с Росатомом",
        ranker=GraphRanker(rerank=slow, budget_s=0.05), resolver=resolver()))
    assert out["types_inferred"] is True and out["rank_timeout"] is True
    assert [e["entity_name"] for e in out["entities"]] == ["Rosatom", "Алексей Лихачёв"]
    assert out["order"] == "edges_to_centre"
    out = obs(await atomic_tools.find_neighbours(
        FakeGraph(), entity_name="Росатом", query="что строит", resolver=resolver()))
    assert "types_inferred" not in out and len(out["entities"]) == 4
