"""Tests for `src/graph/entity_resolution.py`.

Stubs the LLM (verdict-by-pair dict), the embedding model
(deterministic vectors keyed by name), and the graph store
(returns canned existing canonicals).  Verifies the full ER
pipeline: deterministic matches, embedding-based candidates,
LLM judge, hyper-hub clamp, identifier exclusion, name_map
application, incremental ER.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

import pytest
from llama_index.core.base.llms.types import ChatMessage
from llama_index.core.graph_stores.types import (
    KG_NODES_KEY,
    EntityNode,
    Relation,
)
from llama_index.core.schema import TextNode

from src.graph.entity_resolution import (
    ERConfig,
    _deep_normalize,
    _initials_signature,
    _is_cyrillic_name,
    resolve_entities,
)
from src.tenancy.context import GraphContext, default_graph_context

# ── stubs ───────────────────────────────────────────────────────────


@dataclass
class _EmbeddingStub:
    """Maps `name`-derived prefix → fixed vector.  Tests register
    explicit name→vector entries; everything else returns a hash-
    derived stable but distinct vector.
    """

    table: dict[str, list[float]] = field(default_factory=dict)
    batch_calls: int = 0

    async def aget_text_embedding_batch(self, texts: list[str]) -> list[list[float]]:
        self.batch_calls += 1
        return [self._lookup(t) for t in texts]

    async def aget_text_embedding(self, text: str) -> list[float]:
        return self._lookup(text)

    def _lookup(self, text: str) -> list[float]:
        # text is either "name" (no description) or "name: description".
        # Try exact match first, then prefix-match against table keys.
        if text in self.table:
            return list(self.table[text])
        for prefix, vec in self.table.items():
            # Strip trailing ":" from prefix when matching name-only
            # text — the production code skips the colon for entities
            # without a description.
            stripped = prefix.rstrip(":")
            if text == stripped or text.startswith(prefix):
                return list(vec)
        # Deterministic fallback: 4-dim vector from hash; ensures
        # different unseen names get different vectors.
        h = abs(hash(text)) % 9973
        return [math.sin(h), math.cos(h), math.sin(h * 2), math.cos(h * 2)]


@dataclass
class _ScriptedJudgeLLM:
    """LLM stub that maps (name_a, name_b) → bool (SAME/DIFFERENT).

    Returns a JSON array per achat() call so the production parser
    in `_parse_judge_response` is exercised.
    """

    verdicts: dict[tuple[str, str], bool] = field(default_factory=dict)
    raise_on_call: bool = False
    calls: list[list[ChatMessage]] = field(default_factory=list)

    async def achat(self, messages: list[ChatMessage], **_: Any) -> Any:
        self.calls.append(messages)
        if self.raise_on_call:
            raise RuntimeError("judge timeout simulated")

        user = messages[-1].content or ""
        # Parse all pairs from the user message.
        pair_entries = []
        import re

        for m in re.finditer(
            r"Pair (\d+):\s*\n\s*A:\s*'([^']+)'.*?\n\s*B:\s*'([^']+)'",
            user,
            re.DOTALL,
        ):
            idx = int(m.group(1))
            a = m.group(2)
            b = m.group(3)
            key1 = (a, b)
            key2 = (b, a)
            same = self.verdicts.get(key1, self.verdicts.get(key2, False))
            pair_entries.append({
                "pair": idx, "verdict": "SAME" if same else "DIFFERENT",
            })

        class _Resp:
            class _Msg:
                content = json.dumps(pair_entries)

            message = _Msg()

        return _Resp()


@dataclass
class _GraphStoreStub:
    """Returns canned canonical entities via structured_query."""

    rows: list[dict] = field(default_factory=list)
    raises: bool = False
    graph: GraphContext = field(default_factory=default_graph_context)

    def structured_query(self, query: str, param_map: dict | None = None) -> list[dict]:
        if self.raises:
            raise RuntimeError("neo4j down")
        return self.rows


@pytest.fixture(autouse=True)
def _no_namesake_lookup(monkeypatch):
    """The person rule's stored-namesake lookup reads Postgres; tests that
    need it set rows through `namesakes`."""
    rows: list[dict] = []

    async def _lookup(self, stems, *, limit=200):
        return list(rows)

    from src.storage.entity_search import EntitySearchRepository

    monkeypatch.setattr(EntitySearchRepository, "persons_by_surname", _lookup)
    return rows


def _ent(
    name: str, label: str = "Concept", desc: str = "",
    mention_count: int = 1,
) -> EntityNode:
    return EntityNode(
        name=name, label=label,
        properties={"description": desc, "mention_count": mention_count},
    )


# ── pure helpers ────────────────────────────────────────────────────


def test_deep_normalize() -> None:
    assert _deep_normalize("Basal Cell Carcinoma") == "basal cell carcinoma"
    assert _deep_normalize("Basal-cell  carcinoma!") == "basal cell carcinoma"
    assert _deep_normalize("Иванов И. И.") == "иванов и и"


def test_initials_signature_full() -> None:
    sig = _initials_signature("Иванов И.И.")
    assert sig is not None
    assert sig[0] == "иванов"


def test_is_cyrillic_name() -> None:
    assert _is_cyrillic_name("Базальноклеточный Рак")
    assert not _is_cyrillic_name("Basal Cell Carcinoma")
    assert not _is_cyrillic_name("BCC")


# ── end-to-end resolve_entities ─────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_lingual_merge() -> None:
    """BCC and Базальноклеточный Рак — same vector + LLM SAME → merge."""
    embed = _EmbeddingStub(table={
        "Basal Cell Carcinoma:": [1.0, 0.0, 0.0, 0.0],
        "Базальноклеточный Рак:": [1.0, 0.0, 0.0, 0.0],  # identical → cosine 1.0
    })
    llm = _ScriptedJudgeLLM(verdicts={
        ("Basal Cell Carcinoma", "Базальноклеточный Рак"): True,
    })
    entities = [
        _ent("Basal Cell Carcinoma", desc="A type of skin cancer.", mention_count=3),
        _ent("Базальноклеточный Рак", desc="Тип рака кожи.", mention_count=5),
    ]
    out_ents, out_rels, name_map = await resolve_entities(
        entities, [], [], llm=llm, embed_model=embed,
    )
    # One canonical entity remains.
    assert len(out_ents) == 1
    # Canonical picked by mention_count → Cyrillic with count 5.
    assert out_ents[0].name == "Базальноклеточный Рак"
    assert "Basal Cell Carcinoma" in out_ents[0].properties["aliases"]
    # name_map keyed by normalised name of the non-canonical.
    assert any("basal" in k.lower() for k in name_map)


@pytest.mark.asyncio
async def test_initialism_deterministic_no_llm() -> None:
    """Иванов И.И. ≡ Иван Иванов via initials regex — no LLM call."""
    embed = _EmbeddingStub()
    llm = _ScriptedJudgeLLM()  # would record any call
    entities = [
        _ent("Иванов И.И.", label="Person", mention_count=4),
        _ent("Иван Иванов", label="Person", mention_count=2),
    ]
    out_ents, _, name_map = await resolve_entities(
        entities, [], [], llm=llm, embed_model=embed,
    )
    assert len(out_ents) == 1
    # Mention_count tiebreak: Иванов И.И. (4) wins over Иван Иванов (2).
    assert out_ents[0].name == "Иванов И.И."
    # No LLM judge call because deterministic confirmed the pair.
    assert llm.calls == []
    assert len(name_map) == 1


@pytest.mark.asyncio
async def test_type_vs_instance_trap_rejected() -> None:
    """Cosine 0.95 but LLM DIFFERENT → not merged."""
    embed = _EmbeddingStub(table={
        "Клиент:": [1.0, 0.0, 0.0, 0.0],
        "Клиент #4521:": [0.999, 0.04, 0.0, 0.0],  # very close
    })
    # Borderline (cosine ≥ HIGH but same-script auto-merge applies);
    # to route to LLM we use a cross-script trick — actually let's
    # use a borderline cosine to ensure LLM is asked.
    embed.table["Клиент:"] = [1.0, 0.0, 0.0, 0.0]
    embed.table["Клиент #4521:"] = [0.80, 0.60, 0.0, 0.0]
    # cosine = 0.80 → in [LOW, HIGH) range → routes to LLM.
    llm = _ScriptedJudgeLLM(verdicts={
        ("Клиент", "Клиент #4521"): False,
    })
    entities = [
        _ent("Клиент", desc="Generic concept of a customer.", mention_count=10),
        _ent("Клиент #4521", desc="A specific customer record.", mention_count=2),
    ]
    out_ents, _, name_map = await resolve_entities(
        entities, [], [], llm=llm, embed_model=embed,
    )
    assert len(out_ents) == 2
    assert name_map == {}


@pytest.mark.asyncio
async def test_deterministic_label_excluded() -> None:
    """Phone/INN/Email labels are SKIPPED — even with cosine 1.0."""
    embed = _EmbeddingStub(table={
        "+74951234567:": [1.0, 0.0, 0.0, 0.0],
        "+74951234568:": [1.0, 0.0, 0.0, 0.0],
    })
    llm = _ScriptedJudgeLLM(verdicts={
        ("+74951234567", "+74951234568"): True,  # would merge if asked
    })
    entities = [
        _ent("+74951234567", label="PhoneNumber"),
        _ent("+74951234568", label="PhoneNumber"),
    ]
    out_ents, _, name_map = await resolve_entities(
        entities, [], [], llm=llm, embed_model=embed,
    )
    assert len(out_ents) == 2  # both kept
    assert llm.calls == []     # LLM never consulted
    assert name_map == {}


@pytest.mark.asyncio
async def test_self_loop_relation_dropped() -> None:
    """When A and B merge, a relation A→B becomes self-loop and is dropped."""
    embed = _EmbeddingStub(table={
        "Basal Cell Carcinoma:": [1.0, 0.0, 0.0, 0.0],
        "Базальноклеточный Рак:": [1.0, 0.0, 0.0, 0.0],
    })
    llm = _ScriptedJudgeLLM(verdicts={
        ("Basal Cell Carcinoma", "Базальноклеточный Рак"): True,
    })
    a = _ent("Basal Cell Carcinoma", mention_count=1)
    b = _ent("Базальноклеточный Рак", mention_count=1)
    self_loop = Relation(
        label="ALIAS_OF", source_id=a.id, target_id=b.id,
        properties={"description": "Same thing."},
    )
    out_ents, out_rels, _ = await resolve_entities(
        [a, b], [self_loop], [], llm=llm, embed_model=embed,
    )
    # When source_id == target_id post-rewrite (same canonical), drop.
    assert all(r.source_id != r.target_id for r in out_rels)


@pytest.mark.asyncio
async def test_hyper_hub_clamp() -> None:
    """Cluster size ≥ hyper_hub_threshold → not merged, marked review."""
    # Build 13 entities that all share the same embedding → one big cluster.
    name_template = "Entity {i}"
    table = {
        f"{name_template.format(i=i)}:": [1.0, 0.0, 0.0, 0.0] for i in range(13)
    }
    embed = _EmbeddingStub(table=table)
    # LLM says SAME for every pair encountered.
    llm = _ScriptedJudgeLLM()  # not consulted because cosine 1.0 = auto-merge
    entities = [_ent(name_template.format(i=i)) for i in range(13)]
    cfg = ERConfig(hyper_hub_threshold=12, high=0.95)
    out_ents, _, name_map = await resolve_entities(
        entities, [], [], llm=llm, embed_model=embed, config=cfg,
    )
    # All 13 kept (not merged).
    assert len(out_ents) == 13
    # name_map empty (no consolidation happened).
    assert name_map == {}
    # er_review_needed flag on every member.
    review_flagged = sum(
        1 for e in out_ents if (e.properties or {}).get("er_review_needed")
    )
    assert review_flagged == 13


@pytest.mark.asyncio
async def test_judge_timeout_treated_as_different() -> None:
    """LLM raises → all borderline pairs default to DIFFERENT."""
    embed = _EmbeddingStub(table={
        "A:": [1.0, 0.0, 0.0, 0.0],
        "B:": [0.80, 0.60, 0.0, 0.0],  # borderline cosine 0.80
    })
    llm = _ScriptedJudgeLLM(raise_on_call=True)
    entities = [_ent("A", desc="ay"), _ent("B", desc="bee")]
    out_ents, _, name_map = await resolve_entities(
        entities, [], [], llm=llm, embed_model=embed,
    )
    assert len(out_ents) == 2  # both kept
    assert name_map == {}


@pytest.mark.asyncio
async def test_embedding_failure_passthrough() -> None:
    """Embed API raises → return inputs unchanged, no ER applied."""

    class _RaisingEmbed:
        async def aget_text_embedding_batch(self, texts):
            raise RuntimeError("embed down")

        async def aget_text_embedding(self, text):
            raise RuntimeError("embed down")

    llm = _ScriptedJudgeLLM()
    entities = [_ent("X"), _ent("Y")]
    out_ents, out_rels, name_map = await resolve_entities(
        entities, [], [], llm=llm, embed_model=_RaisingEmbed(),
    )
    assert out_ents == entities  # identity, not just equal
    assert out_rels == []
    assert name_map == {}


@pytest.mark.asyncio
async def test_incremental_er_from_graph_store() -> None:
    """Stored canonical from prior ingest matches new entity → merge."""
    stored_vec = [1.0, 0.0, 0.0, 0.0]
    embed = _EmbeddingStub(table={
        "BCC:": stored_vec,  # new entity, same vector as stored
    })
    llm = _ScriptedJudgeLLM(verdicts={
        ("BCC", "Базальноклеточный Рак"): True,
        ("Базальноклеточный Рак", "BCC"): True,
    })
    # Stored canonical arrives via the vector-store kNN (the ingest path);
    # the graph-store window source yields nothing on Nebula.
    class _VS:
        def knn(self, vec, k):
            return [{
                "name": "Базальноклеточный Рак",
                "label": "Concept",
                "embedding": stored_vec,
                "mention_count": 10,
                "description": "Существующая каноническая запись.",
            }]

        def upsert(self, ents):
            pass

    graph_store = _GraphStoreStub(rows=[])
    new_entity = _ent("BCC", desc="Abbreviation.", mention_count=2)
    out_ents, _, name_map = await resolve_entities(
        [new_entity], [], [], llm=llm, embed_model=embed,
        graph_store=graph_store,
        config=ERConfig(use_native_vector_knn=True),
        vector_store=_VS(),
    )
    # The new BCC should be redirected to the stored canonical.
    assert len(out_ents) == 1
    assert out_ents[0].name == "Базальноклеточный Рак"
    assert "BCC" in (out_ents[0].properties or {}).get("aliases", [])


@pytest.mark.asyncio
async def test_name_map_applied_to_chunk_metadata() -> None:
    """After ER, chunk-level KG_NODES_KEY entities get renamed to canonical."""
    embed = _EmbeddingStub(table={
        "Basal Cell Carcinoma:": [1.0, 0.0, 0.0, 0.0],
        "Базальноклеточный Рак:": [1.0, 0.0, 0.0, 0.0],
    })
    llm = _ScriptedJudgeLLM(verdicts={
        ("Basal Cell Carcinoma", "Базальноклеточный Рак"): True,
    })
    # Chunk-level entities point to per-chunk EntityNodes (separate
    # instances) with the same names.  After ER, both should be
    # renamed to the canonical.
    chunk_a = TextNode(id_="c1", text="...")
    chunk_a.metadata[KG_NODES_KEY] = [_ent("Basal Cell Carcinoma")]
    chunk_b = TextNode(id_="c2", text="...")
    chunk_b.metadata[KG_NODES_KEY] = [_ent("Базальноклеточный Рак")]

    merged = [
        _ent("Basal Cell Carcinoma", mention_count=1),
        _ent("Базальноклеточный Рак", mention_count=3),
    ]
    await resolve_entities(
        merged, [], [chunk_a, chunk_b], llm=llm, embed_model=embed,
    )
    # Both chunk-level entities now carry the canonical name.
    final_names = {
        ent.name
        for chunk in (chunk_a, chunk_b)
        for ent in chunk.metadata[KG_NODES_KEY]
    }
    assert final_names == {"Базальноклеточный Рак"}


@pytest.mark.asyncio
async def test_aliases_preserved() -> None:
    """Cluster members' non-canonical names land in properties['aliases']."""
    embed = _EmbeddingStub(table={
        "Иванов И.И.:": [1.0, 0.0, 0.0, 0.0],
        "Иван Иванов:": [1.0, 0.0, 0.0, 0.0],
    })
    llm = _ScriptedJudgeLLM()  # deterministic pre-pass handles this
    entities = [
        _ent("Иванов И.И.", label="Person", mention_count=5),
        _ent("Иван Иванов", label="Person", mention_count=1),
    ]
    out_ents, _, _ = await resolve_entities(
        entities, [], [], llm=llm, embed_model=embed,
    )
    assert len(out_ents) == 1
    aliases = (out_ents[0].properties or {}).get("aliases") or []
    assert "Иван Иванов" in aliases


@pytest.mark.asyncio
async def test_singletons_get_er_metadata() -> None:
    """Entities not in any cluster still get er_canonical_name +
    er_embedding so the next ingest can match against them."""
    embed = _EmbeddingStub(table={
        "Unique Concept:": [0.1, 0.2, 0.3, 0.4],
    })
    llm = _ScriptedJudgeLLM()
    entities = [_ent("Unique Concept", desc="Solo.")]
    out_ents, _, _ = await resolve_entities(
        entities, [], [], llm=llm, embed_model=embed,
    )
    assert len(out_ents) == 1
    props = out_ents[0].properties or {}
    assert props.get("er_canonical_name") == "Unique Concept"
    assert json.loads(props.get("er_embedding")) == [0.1, 0.2, 0.3, 0.4]


@pytest.mark.asyncio
async def test_load_existing_canonicals_issues_no_query_and_returns_empty():
    """The bounded-window source has no Nebula query path: it must return
    no stored candidates WITHOUT touching the store (replaces the old
    Cypher-shape test)."""
    from src.graph.entity_resolution import _load_existing_canonicals

    class _Store:
        def structured_query(self, query, param_map=None):
            raise AssertionError("must not query the graph store")

    assert await _load_existing_canonicals(_Store(), limit=123) == []


@pytest.mark.asyncio
async def test_load_existing_canonicals_none_store_returns_empty():
    from src.graph.entity_resolution import _load_existing_canonicals

    assert await _load_existing_canonicals(None, limit=10) == []


def _mk_item(name: str, vec: list[float], *, label: str = "Person", desc: str = "d"):
    from src.graph.entity_resolution import _Item, _normalize_entity_name
    return _Item(
        name=name, norm=_normalize_entity_name(name), label=label,
        description=desc, mention_count=3, source="new", embedding=vec,
    )


def test_candidate_pairs_numpy_path_matches_pure_python(monkeypatch):
    """The vectorised cosine path is an optimisation — it must yield the
    EXACT same candidate set as the pure-Python `_cosine` fallback, never
    a behaviour change."""
    import src.graph.entity_resolution as er

    items = [
        _mk_item("Alpha One", [1.0, 0.0, 0.0, 0.0]),
        _mk_item("Alpha Two", [0.99, 0.10, 0.0, 0.0]),   # near-dup of Alpha
        _mk_item("Beta Core", [0.0, 1.0, 0.0, 0.0]),
        _mk_item("Beta Prime", [0.02, 0.98, 0.05, 0.0]),  # near-dup of Beta
        _mk_item("Gamma", [0.0, 0.0, 1.0, 0.0]),
        _mk_item("Delta", [0.0, 0.0, 0.0, 1.0]),
        _mk_item("Beta Two", [0.0, 0.97, 0.10, 0.0]),     # another Beta-ish
        _mk_item("Empty Desc", [0.9, 0.2, 0.0, 0.0], desc=""),  # empty-desc floor
    ]
    cfg = ERConfig()

    auto_np, bord_np = er._candidate_pairs(items, cfg)
    set_np = {(a, b) for a, b, _ in [*auto_np, *bord_np]}

    monkeypatch.setattr(er, "_normalized_matrix", lambda group: None)
    auto_py, bord_py = er._candidate_pairs(items, cfg)
    set_py = {(a, b) for a, b, _ in [*auto_py, *bord_py]}

    assert set_np == set_py


@pytest.mark.asyncio
async def test_cleanup_stored_losers_safe_on_failure():
    """When the repoint+delete query fails (e.g. APOC missing), the loser
    node must be LEFT INTACT — exactly one query attempt per pair, no
    second `DETACH DELETE` that would drop its edges, and no raise."""
    from src.graph.entity_resolution import _cleanup_stored_losers

    calls: list[dict] = []

    from src.tenancy.context import default_graph_context

    class _BoomStore:
        graph = default_graph_context()  # build_er_graph_ops scopes the verdict cache by it

        def structured_query(self, query, param_map=None):
            calls.append({"query": query, "param_map": param_map})
            raise RuntimeError("apoc.merge.relationship not found")

    # Must not raise.
    await _cleanup_stored_losers(_BoomStore(), [("Loser A", "Canon A")])

    # Exactly one attempt (the APOC repoint) — no destructive fallback.
    assert len(calls) == 1
    assert "DETACH DELETE" not in calls[0]["query"] or "apoc.merge" in calls[0]["query"]


# ── ERGraphOps seam wiring (Task 4) ─────────────────────────────────


def test_load_verdict_cache_routes_through_er_graph_ops_seam(monkeypatch):
    """`_load_verdict_cache` must delegate to
    `build_er_graph_ops(store).load_verdicts(keys)` rather than issuing
    Cypher inline."""
    import src.graph.entity_resolution as er

    class _FakeOps:
        def __init__(self):
            self.calls: list[list[str]] = []

        def load_verdicts(self, keys):
            self.calls.append(list(keys))
            return {"k1": True}

    fake = _FakeOps()
    seam_calls: list[Any] = []

    def _fake_build(store):
        seam_calls.append(store)
        return fake

    monkeypatch.setattr(er, "build_er_graph_ops", _fake_build)

    store = object()
    result = er._load_verdict_cache(store, ["k1", "k2"])

    assert result == {"k1": True}
    assert fake.calls == [["k1", "k2"]]
    assert seam_calls == [store]


def test_load_verdict_cache_fail_open_when_seam_raises(monkeypatch):
    """Contract preserved: any error from the seam is logged and
    swallowed — `_load_verdict_cache` returns `{}`, never raises."""
    import src.graph.entity_resolution as er

    class _BoomOps:
        def load_verdicts(self, keys):
            raise RuntimeError("boom")

    monkeypatch.setattr(er, "build_er_graph_ops", lambda store: _BoomOps())

    assert er._load_verdict_cache(object(), ["k1"]) == {}


def test_store_verdicts_routes_through_er_graph_ops_seam(monkeypatch):
    """`_store_verdicts` must delegate to
    `build_er_graph_ops(store).store_verdicts(entries)` rather than
    issuing the constraint + UNWIND-MERGE Cypher inline."""
    import src.graph.entity_resolution as er

    class _FakeOps:
        def __init__(self):
            self.calls: list[dict] = []

        def store_verdicts(self, entries):
            self.calls.append(dict(entries))

    fake = _FakeOps()
    seam_calls: list[Any] = []

    def _fake_build(store):
        seam_calls.append(store)
        return fake

    monkeypatch.setattr(er, "build_er_graph_ops", _fake_build)

    store = object()
    er._store_verdicts(store, {"k": True})

    assert fake.calls == [{"k": True}]
    assert seam_calls == [store]


def test_store_verdicts_fail_open_when_seam_raises(monkeypatch):
    """Contract preserved: any error from the seam is logged and
    swallowed — `_store_verdicts` must not raise."""
    import src.graph.entity_resolution as er

    class _BoomOps:
        def store_verdicts(self, entries):
            raise RuntimeError("boom")

    monkeypatch.setattr(er, "build_er_graph_ops", lambda store: _BoomOps())

    er._store_verdicts(object(), {"k": True})  # must not raise


@pytest.mark.asyncio
async def test_cleanup_stored_losers_routes_through_er_graph_ops_seam(monkeypatch):
    """The merge loop must delegate to
    `build_er_graph_ops(graph_store).merge_loser_into_canonical(loser=,
    canon=)` for each pair, in order, with the exact kwargs."""
    import src.graph.entity_resolution as er

    class _FakeOps:
        def __init__(self):
            self.calls: list[dict] = []

        def merge_loser_into_canonical(self, *, loser, canon):
            self.calls.append({"loser": loser, "canon": canon})

    fake = _FakeOps()
    monkeypatch.setattr(er, "build_er_graph_ops", lambda store: fake)

    await er._cleanup_stored_losers(
        object(), [("Loser A", "Canon A"), ("Loser B", "Canon B")],
    )

    assert fake.calls == [
        {"loser": "Loser A", "canon": "Canon A"},
        {"loser": "Loser B", "canon": "Canon B"},
    ]


@pytest.mark.asyncio
async def test_cleanup_stored_losers_fail_open_when_seam_raises(monkeypatch):
    """SAFETY-CRITICAL: when `merge_loser_into_canonical` raises for one
    pair (the nebula seam's "never delete without repointing" guarantee
    surfaces as a raise), the loser must be left intact — no exception
    escapes the loop, and subsequent pairs are still processed."""
    import src.graph.entity_resolution as er

    class _FlakyOps:
        def __init__(self):
            self.calls: list[dict] = []

        def merge_loser_into_canonical(self, *, loser, canon):
            self.calls.append({"loser": loser, "canon": canon})
            if loser == "Loser A":
                raise RuntimeError("nGQL re-insert failed")

    fake = _FlakyOps()
    monkeypatch.setattr(er, "build_er_graph_ops", lambda store: fake)

    # Must not raise, despite the first pair's seam call failing.
    await er._cleanup_stored_losers(
        object(), [("Loser A", "Canon A"), ("Loser B", "Canon B")],
    )

    # Both pairs were attempted — the failure on pair 1 didn't abort the
    # loop, so pair 2 still got its (successful) merge attempt.
    assert fake.calls == [
        {"loser": "Loser A", "canon": "Canon A"},
        {"loser": "Loser B", "canon": "Canon B"},
    ]


@pytest.mark.asyncio
async def test_singletons_get_er_vec_when_native_knn_enabled() -> None:
    """With native kNN on, singletons also get the native `er_vec` list
    (alongside the legacy `er_embedding` JSON) so the vector index can
    find them."""
    embed = _EmbeddingStub(table={"Unique Concept:": [0.1, 0.2, 0.3, 0.4]})
    out_ents, _, _ = await resolve_entities(
        [_ent("Unique Concept", desc="Solo.")], [], [],
        llm=_ScriptedJudgeLLM(), embed_model=embed,
        config=ERConfig(use_native_vector_knn=True),  # graph_store=None → no kNN load
    )
    props = out_ents[0].properties or {}
    assert props.get("er_vec") == [0.1, 0.2, 0.3, 0.4]
    assert json.loads(props.get("er_embedding")) == [0.1, 0.2, 0.3, 0.4]


@pytest.mark.asyncio
async def test_load_candidates_native_issues_no_query_and_returns_empty() -> None:
    """Without a vector store there is nothing to kNN against: no stored
    candidates and no graph-store query (replaces the old Cypher
    queryNodes fixture test; the Milvus path is covered by
    test_resolve_entities_uses_vector_store_knn_and_upsert)."""
    from src.graph.entity_resolution import _Item, _load_candidates_native

    class _Store:
        def structured_query(self, query, param_map=None):
            raise AssertionError("must not query the graph store")

    new = [_Item(name="New X", norm="new x", label="Person",
                 description="", mention_count=1, source="new",
                 embedding=[1.0, 0.0])]
    assert await _load_candidates_native(_Store(), new, k=10) == []


@pytest.mark.asyncio
async def test_load_candidates_via_store_builds_deduped_stored_items() -> None:
    """Downstream half of the old native-kNN test, fed via the vector-store
    path: kNN hits across new entities are deduped by name into stored
    _Items carrying embedding/label/mention_count; hits without an
    embedding are skipped."""
    from src.graph.entity_resolution import _Item, _load_candidates_via_store

    hits = [
        {"name": "Stored A", "label": "Person", "embedding": [1.0, 0.0],
         "mention_count": 7, "description": "d"},
        {"name": "Stored B", "label": "Organization", "embedding": [0.0, 1.0],
         "mention_count": 3, "description": ""},
        {"name": "No Vec", "label": "Person", "embedding": [],
         "mention_count": 1, "description": ""},
    ]

    class _VS:
        def __init__(self): self.calls = []
        def knn(self, vec, k):
            self.calls.append((list(vec), k))
            return hits  # same hits for every new entity -> dedup

    new = [
        _Item(name="New X", norm="new x", label="Person", description="",
              mention_count=1, source="new", embedding=[1.0, 0.0]),
        _Item(name="New Y", norm="new y", label="Person", description="",
              mention_count=1, source="new", embedding=[0.0, 1.0]),
    ]
    vs = _VS()
    out = await _load_candidates_via_store(vs, new, k=10)

    assert vs.calls == [([1.0, 0.0], 10), ([0.0, 1.0], 10)]
    by_name = {it.name: it for it in out}
    assert set(by_name) == {"Stored A", "Stored B"}
    assert len(out) == 2
    assert by_name["Stored A"].embedding == [1.0, 0.0]
    assert by_name["Stored A"].source == "stored"
    assert by_name["Stored A"].mention_count == 7
    assert by_name["Stored B"].embedding == [0.0, 1.0]
    assert by_name["Stored B"].label == "Organization"


@pytest.mark.asyncio
async def test_resolve_entities_uses_vector_store_knn_and_upsert(monkeypatch):
    """When a vector_store is passed with native kNN on, ER pulls candidates
    from store.knn and upserts canonicals to store.upsert."""
    from src.graph.entity_resolution import ERConfig, resolve_entities

    class _VS:
        def __init__(self): self.knn_calls = 0; self.upserted = []
        def knn(self, vec, k):
            self.knn_calls += 1
            return []          # no stored candidates -> within-batch ER only
        def upsert(self, ents): self.upserted.extend(ents)

    vs = _VS()
    # one new entity; stub embed so it gets an embedding
    ents = [EntityNode(name="Иванов", label="PERSON", properties={})]
    async def _fake_embed(items, _model):
        for it in items: it.embedding = [0.1, 0.2]
        return True
    monkeypatch.setattr("src.graph.entity_resolution._embed_entities", _fake_embed)

    out_ents, _, _ = await resolve_entities(
        ents, [], [], llm=object(), embed_model=object(), graph_store=None,
        config=ERConfig(use_native_vector_knn=True, vector_knn_k=5),
        vector_store=vs,
    )
    assert vs.knn_calls == 1          # queried the store for the new entity
    assert len(vs.upserted) >= 1      # canonicals upserted to the vector store


# ── entity-watch: the merge carries subscriptions/journals to the canonical ──


@pytest.fixture(autouse=True)
def _no_watch_rewrite_db(request, monkeypatch):
    """_cleanup_stored_losers rewrites the entity-watch tables after each
    merge; keep the rest of this file off a real Postgres."""
    if "watch_rewrite" in request.node.name:
        return
    import src.graph.entity_resolution as er

    async def _noop(graph, loser, canon):
        return None

    monkeypatch.setattr(er, "_rewrite_watch_vid", _noop)


@pytest.mark.asyncio
async def test_watch_rewrite_follows_each_successful_merge_only(monkeypatch):
    import src.graph.entity_resolution as er

    class _FlakyOps:
        def merge_loser_into_canonical(self, *, loser, canon):
            if loser == "Loser A":
                raise RuntimeError("nGQL re-insert failed")

    rewrites: list[tuple[object, str, str]] = []

    async def _rec(graph, loser, canon):
        rewrites.append((graph, loser, canon))

    class _Store:
        graph = object()

    store = _Store()
    monkeypatch.setattr(er, "build_er_graph_ops", lambda store: _FlakyOps())
    monkeypatch.setattr(er, "_rewrite_watch_vid", _rec)

    await er._cleanup_stored_losers(store, [("Loser A", "Canon A"), ("Loser B", "Canon B")])

    # the failed merge left the loser intact, so its watch rows stay too;
    # the rewrite runs in the merged store's graph
    assert rewrites == [(store.graph, "Loser B", "Canon B")]


@pytest.mark.asyncio
async def test_watch_rewrite_maps_names_to_vids_and_never_raises(monkeypatch):
    import src.graph.entity_resolution as er
    import src.storage.watch as watch_mod
    from src.graph.nebula_store import entity_vid

    calls: list[tuple] = []
    graphs: list[object] = []
    graph = object()

    class _Repo:
        def __init__(self, *, graph):
            graphs.append(graph)

        async def rewrite_vid(self, loser_vid, canon_vid, canon_name):
            calls.append((loser_vid, canon_vid, canon_name))
            raise RuntimeError("pg down")

    monkeypatch.setattr(watch_mod, "WatchRepository", _Repo)
    await er._rewrite_watch_vid(graph, "Исаев В.И.", "Исаев Валентин Игоревич")  # must not raise
    assert calls == [(entity_vid("Исаев В.И."), entity_vid("Исаев Валентин Игоревич"),
                      "Исаев Валентин Игоревич")]
    assert graphs == [graph]


# ── person-name rule ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_person_forms_in_one_document_merge_to_the_full_name() -> None:
    """Поляков / Поляков С.Н. / Полякова Сергея Николаевича / Поляков
    Сергей Николаевич — one person, canonical is the full nominative FIO
    even though the bare surname is mentioned most; no LLM at all (the
    3-member cluster skips the verification call)."""
    llm = _ScriptedJudgeLLM()
    entities = [
        _ent("Поляков", label="Person", mention_count=9),
        _ent("Поляков С.Н.", label="Person", mention_count=3),
        _ent("Полякова Сергея Николаевича", label="Person", mention_count=1),
        _ent("Поляков Сергей Николаевич", label="Person", mention_count=1),
    ]
    out_ents, _, name_map = await resolve_entities(
        entities, [], [], llm=llm, embed_model=_EmbeddingStub(),
    )
    assert [e.name for e in out_ents] == ["Поляков Сергей Николаевич"]
    assert set(name_map.values()) == {"Поляков Сергей Николаевич"}
    assert llm.calls == []


@pytest.mark.asyncio
async def test_ambiguous_short_form_is_not_merged_by_the_rule() -> None:
    """Соколов С.С. fits both namesakes — the rule leaves it alone."""
    # Far-apart vectors: neither cosine auto-merge nor the judge pool.
    embed = _EmbeddingStub(table={
        "Соколов С.С.": [1.0, 0.0, 0.0, 0.0],
        "Соколов Семён Степанович": [0.0, 1.0, 0.0, 0.0],
        "Соколов Сергей Сергеевич": [0.0, 0.0, 1.0, 0.0],
    })
    llm = _ScriptedJudgeLLM()
    entities = [
        _ent("Соколов С.С.", label="Person"),
        _ent("Соколов Семён Степанович", label="Person"),
        _ent("Соколов Сергей Сергеевич", label="Person"),
    ]
    out_ents, _, name_map = await resolve_entities(
        entities, [], [], llm=llm, embed_model=embed,
    )
    assert len(out_ents) == 3
    assert name_map == {}


@pytest.mark.asyncio
async def test_different_initials_never_reach_auto_merge_or_judge() -> None:
    """Identical vectors (cosine 1.0) would auto-merge — the name veto
    stops it, and the judge is not asked."""
    vec = [1.0, 0.0, 0.0, 0.0]
    embed = _EmbeddingStub(table={"Елисеев С.Н.:": vec, "Елисеев А.Л.:": vec})
    llm = _ScriptedJudgeLLM(verdicts={("Елисеев С.Н.", "Елисеев А.Л."): True})
    out_ents, _, name_map = await resolve_entities(
        [_ent("Елисеев С.Н.", label="Person"), _ent("Елисеев А.Л.", label="Person")],
        [], [], llm=llm, embed_model=embed,
    )
    assert len(out_ents) == 2
    assert name_map == {}
    assert llm.calls == []


@pytest.mark.asyncio
async def test_stored_full_name_from_entity_mirror_absorbs_new_short_form(
    _no_namesake_lookup,
) -> None:
    """kNN found nothing; the surname lookup brings the stored full FIO and
    the new short form merges into it. A new bare surname does not merge
    across documents."""
    _no_namesake_lookup.append({
        "vid": "v1", "name": "Исаев Валентин Игоревич", "label": "Person",
        "description": "", "mention_count": 7,
    })
    llm = _ScriptedJudgeLLM()
    out_ents, _, name_map = await resolve_entities(
        [_ent("Исаев В.И.", label="Person"), _ent("Медведев", label="Person")],
        [], [], llm=llm, embed_model=_EmbeddingStub(),
        graph_store=_GraphStoreStub(rows=[]),
    )
    names = sorted(e.name for e in out_ents)
    assert names == ["Исаев Валентин Игоревич", "Медведев"]
    assert name_map == {"Исаев В.И.": "Исаев Валентин Игоревич"}
    canon = next(e for e in out_ents if e.name == "Исаев Валентин Игоревич")
    # the mirror row has no vector — the new member's is carried over
    assert json.loads(canon.properties["er_embedding"])


@pytest.mark.asyncio
async def test_bare_surname_does_not_merge_with_stored_namesake(_no_namesake_lookup) -> None:
    _no_namesake_lookup.append({
        "vid": "v1", "name": "Медведев Е.В.", "label": "Person",
        "description": "", "mention_count": 3,
    })
    out_ents, _, name_map = await resolve_entities(
        [_ent("Медведев", label="Person")], [], [],
        llm=_ScriptedJudgeLLM(), embed_model=_EmbeddingStub(),
        graph_store=_GraphStoreStub(rows=[]),
    )
    assert [e.name for e in out_ents] == ["Медведев"]
    assert name_map == {}


@pytest.mark.asyncio
async def test_person_rule_off_restores_initials_signature() -> None:
    """Flag off: the old one-initial signature merges Иванов И.И. with
    Иван Иванов and ignores the bare surname."""
    entities = [
        _ent("Иванов И.И.", label="Person", mention_count=4),
        _ent("Иван Иванов", label="Person", mention_count=2),
        _ent("Иванов", label="Person", mention_count=9),
    ]
    embed = _EmbeddingStub(table={
        "Иванов И.И.": [1.0, 0.0, 0.0, 0.0],
        "Иван Иванов": [0.0, 1.0, 0.0, 0.0],
        "Иванов": [0.0, 0.0, 1.0, 0.0],
    })
    out_ents, _, _ = await resolve_entities(
        entities, [], [], llm=_ScriptedJudgeLLM(), embed_model=embed,
        config=ERConfig(person_name_rule=False),
    )
    assert sorted(e.name for e in out_ents) == ["Иванов", "Иванов И.И."]
