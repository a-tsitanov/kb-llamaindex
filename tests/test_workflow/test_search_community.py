"""Unit tests for the offline community-build activities + workflow
helpers (Search R6).

The community activities are plain async fns over stubbed deps (no live
Temporal) — same pattern as the other search-activity tests.  We cover:

  * ``summarize_community_activity`` produces a summary via a mock small
    LLM and issues the ``:Community.summary`` MERGE; fail-safe on error,
  * the pure ``build_summarize_specs`` workflow helper turns detected
    communities into batchable summarize params (idempotent re-run).
"""

from __future__ import annotations

import json
import re
from unittest.mock import MagicMock

import pytest

from src.graph.community_writeback import community_vid
from src.graph.nebula_store import _q
from src.tenancy.context import default_graph_context
from src.workflow.contracts import (
    DetectCommunitiesResult,
    DetectedCommunity,
    SummarizeCommunityParams,
)
from src.workflow.search.activities import community as community_mod
from src.workflow.search.activities.community import summarize_community_activity
from src.workflow.search.community_wf import (
    build_summarize_specs,
    group_specs_by_level,
)


class _FakeStore:
    def __init__(self, *, member_rows=None, child_rows=None, raise_on=None):
        self._member_rows = member_rows or []
        self._child_rows = child_rows or []
        self._raise_on = raise_on
        self.calls: list[tuple[str, dict]] = []
        self.graph = default_graph_context()

    def structured_query(self, cypher, param_map=None):
        self.calls.append((cypher, param_map or {}))
        if self._raise_on and self._raise_on in cypher:
            raise RuntimeError("boom")
        if "PARENT_OF" in cypher:
            return self._child_rows
        if "RETURN" in cypher and "description" in cypher:
            return self._member_rows
        return []


class _NebulaStmtStore:
    """nGQL fake keyed on the EXACT statements the nebula seam issues.

    ``responses`` maps a full statement to its canned rows; an unknown
    statement answers ``[]`` (a legitimately empty read) and is still
    recorded in ``calls``.  Nebula binds no parameters, so a non-empty
    ``param_map`` is a test failure."""

    def __init__(self, responses=None):
        self._responses = dict(responses or {})
        self.calls: list[str] = []
        self.graph = default_graph_context()

    def structured_query(self, query, param_map=None):
        assert not param_map, f"nebula binds no params, got {param_map!r}"
        self.calls.append(query)
        return list(self._responses.get(query, []))


def _member_go(community_id, level):
    return (
        f"GO FROM {_q(community_vid(community_id, level))} OVER `IN_COMMUNITY` "
        "REVERSELY YIELD src(edge) AS m;"
    )


def _child_go(community_id, level):
    return (
        f"GO FROM {_q(community_vid(community_id, level))} OVER `PARENT_OF` "
        "YIELD dst(edge) AS child;"
    )


def _summ_store(community_id, level, *, members=(), children=()):
    """Nebula store answering ``NebulaCommunitySummarize``'s reads.

    ``members``: ``{"name","description"}`` rows reached via
    ``IN_COMMUNITY REVERSELY`` + ``FETCH PROP ON Entity``; ``children``:
    ``{"title","summary"}`` reports reached via ``PARENT_OF`` +
    ``FETCH PROP ON Community`` (each carries a non-empty ``report``)."""
    responses: dict[str, list[dict]] = {}
    mvids = [f"m{i}" for i in range(len(members))]
    if mvids:
        listed = ", ".join(_q(v) for v in mvids)
        responses[_member_go(community_id, level)] = [{"m": v} for v in mvids]
        responses[
            f"FETCH PROP ON `Entity` {listed} YIELD id(vertex) AS vid, "
            "`Entity`.name AS name, `Entity`.description AS description;"
        ] = [{"vid": v, **m} for v, m in zip(mvids, members, strict=True)]
    cvids = [f"c{i}" for i in range(len(children))]
    if cvids:
        listed = ", ".join(_q(v) for v in cvids)
        responses[_child_go(community_id, level)] = [{"child": v} for v in cvids]
        responses[
            f"FETCH PROP ON `Community` {listed} YIELD "
            "`Community`.title AS title, `Community`.summary AS summary, "
            "`Community`.report AS report, `Community`.member_count AS mc;"
        ] = [
            {**c, "report": "{}", "mc": len(children) - i}
            for i, c in enumerate(children)
        ]
    return _NebulaStmtStore(responses)


_UPDATE_RE = re.compile(
    r'^UPDATE VERTEX ON `Community` "(?P<vid>[0-9a-f]+)" SET '
    r'report = (?P<report>"(?:[^"\\]|\\.)*"), '
    r'title = (?P<title>"(?:[^"\\]|\\.)*"), '
    r'summary = (?P<summary>"(?:[^"\\]|\\.)*"), '
    r"summarized_at = (?P<ts>\d+);$"
)


def _report_write(store, community_id, level):
    """The report write the nebula summarize issued for ONE community, as a
    field dict (string literals decoded — ``_q`` escaping is JSON-compatible),
    or ``None`` when no such ``UPDATE VERTEX`` was issued."""
    vid = community_vid(community_id, level)
    for stmt in store.calls:
        m = _UPDATE_RE.match(stmt)
        if m and m["vid"] == vid:
            return {
                "community_id": community_id,
                "report": json.loads(m["report"]),
                "title": json.loads(m["title"]),
                "summary": json.loads(m["summary"]),
                "statement": stmt,
            }
    return None


class _RecReportStore:
    """Milvus report-vec store fake: records ``upsert``s (the nebula home of
    ``report_vec`` — it is never written to the graph vertex)."""

    def __init__(self):
        self.upserts: list[list[dict]] = []

    def knn(self, query_vec, *, level, limit):
        raise AssertionError("the WRITE path must never knn")

    def upsert(self, reports):
        self.upserts.append(reports)


class _FakeEmbed:
    """Returns a fixed-length vector; records the embedded text."""

    def __init__(self, dim=4):
        self.dim = dim
        self.seen_text: str | None = None

    async def aget_text_embedding(self, text):
        self.seen_text = text
        return [0.1] * self.dim


def _report_json(title="Группа", summary="Сводка.", findings=None):
    import json

    return json.dumps(
        {
            "title": title,
            "summary": summary,
            "findings": findings
            if findings is not None
            else [{"statement": "Вывод.", "importance": 80}],
        },
        ensure_ascii=False,
    )


class _FakeLLM:
    """Records the prompt(s); returns a canned structured-report JSON."""

    def __init__(self, text=None):
        self.text = text if text is not None else _report_json()
        self.seen_prompt: str | None = None
        self.prompts: list[str] = []

    async def acomplete(self, prompt, **_kw):
        self.seen_prompt = prompt
        self.prompts.append(prompt)
        return MagicMock(text=self.text)


@pytest.fixture(autouse=True)
def _stub_activity_ctx(monkeypatch):
    mock = MagicMock()
    mock.heartbeat = MagicMock()
    mock.logger = MagicMock()
    monkeypatch.setattr(community_mod, "activity", mock)
    # Default embed stub so the activity never builds a real embedding
    # model in unit tests (individual tests may override).
    monkeypatch.setattr(community_mod, "_get_embed_model", lambda: _FakeEmbed())
    # Default inert report-vec store so no test reaches a real Milvus
    # (individual tests may override with their own recorder).
    monkeypatch.setattr(
        community_mod, "build_community_report_vector_store",
        lambda s: _RecReportStore(),
    )


@pytest.mark.asyncio
async def test_summarize_produces_report_and_persists(monkeypatch):
    store = _summ_store("2", 0, members=[
        {"name": "Ромашка", "description": "Поставщик материалов."},
        {"name": "СтройИнвест", "description": "Подрядчик."},
    ])
    report_store = _RecReportStore()
    monkeypatch.setattr(
        community_mod, "build_community_report_vector_store", lambda s: report_store,
    )
    llm = _FakeLLM(_report_json(
        title="Строительные компании",
        summary="Группа строительных компаний.",
        findings=[{"statement": "Тесно связаны контрактами.", "importance": 90}],
    ))
    embed = _FakeEmbed()
    monkeypatch.setattr(community_mod, "_get_store", lambda graph: store)
    monkeypatch.setattr(community_mod, "_get_summary_llm", lambda: llm)
    monkeypatch.setattr(community_mod, "_get_embed_model", lambda: embed)

    out = await summarize_community_activity(SummarizeCommunityParams(
        community_id="2", level=0, member_count=2,
    ))

    assert out.community_id == "2"
    assert out.summary == "Группа строительных компаний."
    assert out.persisted is True
    # The member names made it into the prompt.
    assert "Ромашка" in (llm.seen_prompt or "")
    # title + summary were embedded.
    assert "Строительные компании" in (embed.seen_text or "")
    assert "Группа строительных компаний." in (embed.seen_text or "")
    # The report write was issued with report/title/summary; on nebula the
    # report_vec goes to the Milvus report-vec store, not the vertex.
    write = _report_write(store, "2", 0)
    assert write is not None
    assert write["community_id"] == "2"
    assert write["title"] == "Строительные компании"
    assert write["summary"] == "Группа строительных компаний."
    [vec_report] = report_store.upserts[0]
    assert isinstance(vec_report["embedding"], list)
    import json as _json
    parsed = _json.loads(write["report"])
    assert parsed["findings"][0]["importance"] == 90


@pytest.mark.asyncio
async def test_summarize_level_gt0_uses_child_reports(monkeypatch):
    store = _summ_store(
        "7", 1,
        members=[{"name": "X", "description": "y"}],
        children=[
            {"title": "Дочернее A", "summary": "Сводка A."},
            {"title": "Дочернее B", "summary": "Сводка B."},
        ],
    )
    llm = _FakeLLM()
    monkeypatch.setattr(community_mod, "_get_store", lambda graph: store)
    monkeypatch.setattr(community_mod, "_get_summary_llm", lambda: llm)

    out = await summarize_community_activity(SummarizeCommunityParams(
        community_id="7", level=1, member_count=2,
    ))

    assert out.persisted is True
    # Child-report context (not member context) drove the prompt.
    assert "Дочернее A" in (llm.seen_prompt or "")
    assert "Дочерние сообщества" in (llm.seen_prompt or "")
    # The PARENT_OF child-report query was issued.
    assert _child_go("7", 1) in store.calls


@pytest.mark.asyncio
async def test_summarize_level_gt0_falls_back_to_members(monkeypatch):
    # No child reports yet → must fall back to member context.
    store = _summ_store(
        "7", 1,
        members=[{"name": "Альфа", "description": "Описание."}],
        children=[],
    )
    llm = _FakeLLM()
    monkeypatch.setattr(community_mod, "_get_store", lambda graph: store)
    monkeypatch.setattr(community_mod, "_get_summary_llm", lambda: llm)

    await summarize_community_activity(SummarizeCommunityParams(
        community_id="7", level=1, member_count=1,
    ))

    assert "Альфа" in (llm.seen_prompt or "")
    assert "Сущности сообщества" in (llm.seen_prompt or "")


@pytest.mark.asyncio
async def test_summarize_persists_without_vec_on_embed_failure(monkeypatch):
    store = _summ_store("3", 0, members=[{"name": "A", "description": "x"}])
    report_store = _RecReportStore()
    monkeypatch.setattr(
        community_mod, "build_community_report_vector_store", lambda s: report_store,
    )
    monkeypatch.setattr(community_mod, "_get_store", lambda graph: store)
    monkeypatch.setattr(community_mod, "_get_summary_llm", lambda: _FakeLLM())

    class _BoomEmbed:
        async def aget_text_embedding(self, _t):
            raise RuntimeError("embed down")

    monkeypatch.setattr(community_mod, "_get_embed_model", lambda: _BoomEmbed())

    out = await summarize_community_activity(SummarizeCommunityParams(
        community_id="3", level=0, member_count=2,
    ))
    assert out.persisted is True
    write = _report_write(store, "3", 0)
    assert write is not None
    # no vector anywhere: never on the vertex, and no Milvus upsert.
    assert "report_vec" not in write["statement"]
    assert report_store.upserts == []


class _FakeReportStore:
    """Records ``upsert`` calls; ``knn`` must never be called on the write path."""

    def __init__(self, raise_=False):
        self.upserts: list[list[dict]] = []
        self._raise = raise_

    def knn(self, query_vec, *, level, limit):
        raise AssertionError("the WRITE path must never knn")

    def upsert(self, reports):
        self.upserts.append(reports)
        if self._raise:
            raise RuntimeError("milvus down")


@pytest.mark.asyncio
async def test_summarize_upserts_report_vec_through_store(monkeypatch):
    store = _FakeStore(member_rows=[{"name": "A", "description": "x"}])
    report_store = _FakeReportStore()
    monkeypatch.setattr(community_mod, "_get_store", lambda graph: store)
    monkeypatch.setattr(community_mod, "_get_summary_llm", lambda: _FakeLLM())
    monkeypatch.setattr(
        community_mod, "build_community_report_vector_store", lambda s: report_store,
    )

    out = await summarize_community_activity(SummarizeCommunityParams(
        community_id="2", level=0, member_count=1,
    ))

    assert out.persisted is True
    assert len(report_store.upserts) == 1
    [report] = report_store.upserts[0]
    assert report["community_id"] == "2"
    assert report["level"] == 0
    assert report["summary"] == out.summary
    assert isinstance(report["embedding"], list)


@pytest.mark.asyncio
async def test_summarize_upsert_failopen_on_store_error(monkeypatch):
    store = _FakeStore(member_rows=[{"name": "A", "description": "x"}])
    report_store = _FakeReportStore(raise_=True)
    monkeypatch.setattr(community_mod, "_get_store", lambda graph: store)
    monkeypatch.setattr(community_mod, "_get_summary_llm", lambda: _FakeLLM())
    monkeypatch.setattr(
        community_mod, "build_community_report_vector_store", lambda s: report_store,
    )

    out = await summarize_community_activity(SummarizeCommunityParams(
        community_id="3", level=0, member_count=1,
    ))
    # the seam's upsert raised, but the activity stays fail-open: the
    # Neo4j report write still persisted and no exception escaped.
    assert out.persisted is True
    assert len(report_store.upserts) == 1


@pytest.mark.asyncio
async def test_summarize_skips_upsert_when_embed_failed(monkeypatch):
    store = _FakeStore(member_rows=[{"name": "A", "description": "x"}])
    report_store = _FakeReportStore()
    monkeypatch.setattr(community_mod, "_get_store", lambda graph: store)
    monkeypatch.setattr(community_mod, "_get_summary_llm", lambda: _FakeLLM())
    monkeypatch.setattr(
        community_mod, "build_community_report_vector_store", lambda s: report_store,
    )

    class _BoomEmbed:
        async def aget_text_embedding(self, _t):
            raise RuntimeError("embed down")

    monkeypatch.setattr(community_mod, "_get_embed_model", lambda: _BoomEmbed())

    out = await summarize_community_activity(SummarizeCommunityParams(
        community_id="4", level=0, member_count=1,
    ))
    assert out.persisted is True
    assert report_store.upserts == []


@pytest.mark.asyncio
async def test_summarize_failsafe_on_llm_error(monkeypatch):
    store = _FakeStore(member_rows=[{"name": "A", "description": "x"}])

    class _BoomLLM:
        async def acomplete(self, *_a, **_k):
            raise RuntimeError("llm down")

    monkeypatch.setattr(community_mod, "_get_store", lambda graph: store)
    monkeypatch.setattr(community_mod, "_get_summary_llm", lambda: _BoomLLM())

    out = await summarize_community_activity(SummarizeCommunityParams(
        community_id="1", member_count=2,
    ))
    assert out.summary == ""
    assert out.persisted is False


# ── map-reduce: huge community context is batched, never one giant call ──


def test_split_context_single_batch_when_under_budget():
    ctx = "Сущности сообщества:\n- A: x\n- B: y"
    assert community_mod._split_context_into_batches(ctx, budget=10_000) == [ctx]


def test_split_context_batches_and_keeps_header():
    ctx = "H:\n" + "\n".join(f"- item{i} padpadpad" for i in range(10))
    batches = community_mod._split_context_into_batches(ctx, budget=40)
    assert len(batches) >= 2
    # header replicated onto every batch so each map prompt is well-formed
    assert all(b.startswith("H:\n") for b in batches)
    # no item lost across the split
    joined = "\n".join(batches)
    for i in range(10):
        assert f"item{i}" in joined


@pytest.mark.asyncio
async def test_summarize_map_reduce_on_large_member_context(monkeypatch):
    # Tiny budget forces the map-reduce path on a handful of members —
    # proving a huge root community never sends ONE oversized prompt.
    monkeypatch.setattr(community_mod, "_CONTEXT_CHAR_BUDGET", 60)
    members = [{"name": f"E{i}", "description": "d" * 50} for i in range(6)]
    store = _summ_store("0", 0, members=members)
    llm = _FakeLLM(_report_json(title="Итог", summary="Сводная сводка."))
    monkeypatch.setattr(community_mod, "_get_store", lambda graph: store)
    monkeypatch.setattr(community_mod, "_get_summary_llm", lambda: llm)

    out = await summarize_community_activity(SummarizeCommunityParams(
        community_id="0", level=0, member_count=len(members),
    ))

    assert out.persisted is True
    assert out.summary == "Сводная сводка."
    # map (multiple batches) + reduce → strictly more than one LLM call,
    # and NO single prompt carried every member at once.
    assert len(llm.prompts) >= 3
    assert all("E0" not in p or "E5" not in p for p in llm.prompts)
    # every member reached some map prompt
    joined = "\n".join(llm.prompts)
    for i in range(6):
        assert f"E{i}" in joined


@pytest.mark.asyncio
async def test_summarize_single_call_when_context_fits(monkeypatch):
    # Under budget → exactly ONE LLM call (fast path unchanged).
    store = _FakeStore(member_rows=[
        {"name": "A", "description": "x"}, {"name": "B", "description": "y"},
    ])
    llm = _FakeLLM()
    monkeypatch.setattr(community_mod, "_get_store", lambda graph: store)
    monkeypatch.setattr(community_mod, "_get_summary_llm", lambda: llm)

    out = await summarize_community_activity(SummarizeCommunityParams(
        community_id="2", level=0, member_count=2,
    ))
    assert out.persisted is True
    assert len(llm.prompts) == 1


# ── payload limit: detect result must NOT carry member name lists ───


def test_detect_result_carries_no_member_lists():
    """The cross-Temporal detect result must be O(num communities): slim
    ``DetectedCommunity`` refs carrying ``member_count`` but NO member name
    list, so a large graph never trips Temporal's payload size limit
    ("Complete result exceeds size limit")."""
    from src.workflow.contracts import DetectedCommunity

    detect = DetectCommunitiesResult(communities=[
        DetectedCommunity(community_id="1", level=0, member_count=3),
    ])
    c = detect.communities[0]
    assert c.member_count == 3
    assert not hasattr(c, "members")


@pytest.mark.asyncio
async def test_detect_activity_strips_members_from_result(monkeypatch):
    """detect_communities_activity returns slim refs (member_count, no
    members) even though detect_communities yields full CommunityRefs —
    membership stays in Neo4j, only counts cross the activity boundary."""
    import src.graph.communities as communities_mod
    from src.workflow.contracts import CommunityRef, DetectCommunitiesParams
    from src.workflow.search.activities.community import detect_communities_activity

    async def fake_single(store, *, min_size, level=0, gamma=1.0):
        return [CommunityRef(
            community_id="9", level=0, members=["a", "b", "c", "d"])]

    monkeypatch.setattr(community_mod, "_get_store", lambda graph: object())
    monkeypatch.setattr(communities_mod, "detect_communities", fake_single)

    out = await detect_communities_activity(DetectCommunitiesParams(min_size=1))

    assert len(out.communities) == 1
    c = out.communities[0]
    assert c.community_id == "9"
    assert c.member_count == 4
    assert not hasattr(c, "members")


@pytest.mark.asyncio
async def test_summarize_reads_members_from_graph_by_community_id(monkeypatch):
    """summarize reads its members from Neo4j keyed by community_id (via
    IN_COMMUNITY) — NOT from a member-name list in the params payload."""
    store = _summ_store("2", 0, members=[
        {"name": "Ромашка", "description": "Поставщик."},
    ])
    llm = _FakeLLM()
    monkeypatch.setattr(community_mod, "_get_store", lambda graph: store)
    monkeypatch.setattr(community_mod, "_get_summary_llm", lambda: llm)

    out = await summarize_community_activity(
        SummarizeCommunityParams(community_id="2", level=0, member_count=1))

    assert out.persisted is True
    # members resolved from the graph keyed by community_id "2" (its vid,
    # via IN_COMMUNITY) — the statement carries no member-name list.
    member_call = next((c for c in store.calls if c == _member_go("2", 0)), None)
    assert member_call is not None, "member context query not issued"
    assert community_vid("2", 0) in member_call
    assert "Ромашка" not in member_call  # keyed by id, not by a name list
    assert "Ромашка" in (llm.seen_prompt or "")


@pytest.mark.asyncio
async def test_summarize_zero_member_count_skips_llm(monkeypatch):
    def _llm():
        raise AssertionError("must not build LLM for an empty community")

    monkeypatch.setattr(community_mod, "_get_store", lambda graph: _FakeStore())
    monkeypatch.setattr(community_mod, "_get_summary_llm", _llm)

    out = await summarize_community_activity(
        SummarizeCommunityParams(community_id="1", member_count=0))
    assert out.persisted is False


# ── pure workflow helper: detected → batchable summarize specs ──────


def test_build_summarize_specs_maps_each_community():
    detect = DetectCommunitiesResult(communities=[
        DetectedCommunity(community_id="1", level=0, member_count=3),
        DetectedCommunity(community_id="2", level=0, member_count=3),
    ])
    specs = build_summarize_specs(detect)
    assert [s.community_id for s in specs] == ["1", "2"]
    assert all(isinstance(s, SummarizeCommunityParams) for s in specs)
    assert specs[0].member_count == 3
    assert not hasattr(specs[0], "members")


def test_build_summarize_specs_empty():
    assert build_summarize_specs(DetectCommunitiesResult(communities=[])) == []


def test_build_summarize_specs_skips_carried_over_reports():
    # needs_report=False communities (carried over unchanged from a prior
    # build) are skipped — only those needing a (re)summary emit specs.
    detect = DetectCommunitiesResult(communities=[
        DetectedCommunity(community_id="1", level=0, member_count=3,
                          needs_report=True),
        DetectedCommunity(community_id="2", level=0, member_count=3,
                          needs_report=False),  # carried over → skip
        DetectedCommunity(community_id="3", level=1, member_count=2,
                          needs_report=True),
    ])
    specs = build_summarize_specs(detect)
    assert [s.community_id for s in specs] == ["1", "3"]


# ── pure helper: level grouping (finest-first) ──────────────────────


def test_group_specs_by_level_orders_finest_first():
    specs = [
        SummarizeCommunityParams(community_id="c0a", level=0, member_count=1),
        SummarizeCommunityParams(community_id="c1a", level=1, member_count=1),
        SummarizeCommunityParams(community_id="c2a", level=2, member_count=1),
        SummarizeCommunityParams(community_id="c1b", level=1, member_count=1),
        SummarizeCommunityParams(community_id="c0b", level=0, member_count=1),
    ]
    groups = group_specs_by_level(specs)
    # Finest (highest level number) first, coarsest (level 0) last.
    assert [g[0].level for g in groups] == [2, 1, 0]
    assert [s.community_id for s in groups[0]] == ["c2a"]
    assert [s.community_id for s in groups[1]] == ["c1a", "c1b"]
    assert [s.community_id for s in groups[2]] == ["c0a", "c0b"]


def test_group_specs_by_level_single_level():
    specs = [
        SummarizeCommunityParams(community_id="1", level=0, member_count=1),
        SummarizeCommunityParams(community_id="2", level=0, member_count=1),
    ]
    groups = group_specs_by_level(specs)
    assert len(groups) == 1
    assert [s.community_id for s in groups[0]] == ["1", "2"]


def test_group_specs_by_level_empty():
    assert group_specs_by_level([]) == []


# ── pure helper: structured-report parser ───────────────────────────


def test_parse_report_valid_json():
    text = (
        '{"title": "T", "summary": "S", '
        '"findings": [{"statement": "f1", "importance": 70}]}'
    )
    out = community_mod._parse_report(text)
    assert out["title"] == "T"
    assert out["summary"] == "S"
    assert out["findings"] == [{"statement": "f1", "importance": 70}]


def test_parse_report_strips_code_fence_and_prose():
    text = "Вот отчёт:\n```json\n" + _report_json("X", "Y", []) + "\n```\nготово"
    out = community_mod._parse_report(text)
    assert out["title"] == "X"
    assert out["summary"] == "Y"


def test_parse_report_garbage_falls_back_to_raw():
    out = community_mod._parse_report("just some prose, no json here")
    assert out["title"] == ""
    assert out["summary"] == "just some prose, no json here"
    assert out["findings"] == []


def test_parse_report_empty_string():
    out = community_mod._parse_report("")
    assert out == {"title": "", "summary": "", "findings": []}


def test_parse_report_tolerates_bad_finding_shapes():
    text = (
        '{"title": 5, "summary": "S", "findings": '
        '["not a dict", {"importance": 9}, {"statement": "ok", "importance": "x"}]}'
    )
    out = community_mod._parse_report(text)
    # non-str title → "", missing/blank statement dropped, non-int importance → 0
    assert out["title"] == ""
    assert out["summary"] == "S"
    assert out["findings"] == [{"statement": "ok", "importance": 0}]


@pytest.mark.asyncio
async def test_detect_activity_hierarchy_branch(monkeypatch):
    """max_levels>1 routes to detect_hierarchy, not detect_communities."""
    import src.graph.communities as communities_mod
    from src.workflow.contracts import CommunityRef, DetectCommunitiesParams
    from src.workflow.search.activities.community import detect_communities_activity

    calls = {"hierarchy": 0, "single": 0}

    async def fake_hierarchy(store, *, max_levels, min_size, gamma=1.0):
        calls["hierarchy"] += 1
        return [CommunityRef(community_id="1", level=0, members=["a", "b"])]

    async def fake_single(store, *, min_size, level=0, gamma=1.0):
        calls["single"] += 1
        return []

    monkeypatch.setattr(community_mod, "_get_store", lambda graph: object())
    monkeypatch.setattr(communities_mod, "detect_hierarchy", fake_hierarchy)
    monkeypatch.setattr(communities_mod, "detect_communities", fake_single)

    out = await detect_communities_activity(
        DetectCommunitiesParams(min_size=1, max_levels=3))
    assert calls == {"hierarchy": 1, "single": 0}
    assert [c.community_id for c in out.communities] == ["1"]
