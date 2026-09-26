"""Unit tests for community detection orchestration (Search R6).

Leiden compute is stubbed at the ``_leiden_rows`` seam (the leidenalg
backend); the :Community write-back is a recording fake patched in at
``build_community_writeback``.  We assert:

  * canned ``communityId`` / ``ids`` rows are grouped into ``CommunityRef``s,
  * the ``min_size`` floor drops tiny communities,
  * prune-before-merge ordering, hierarchy parent-first ordering and the
    incremental report carry-over reach the write-back,
  * any compute error → ``[]`` (fail-safe, no raise through the boundary).

The nGQL each write-back call issues is covered in
tests/test_graph/test_community_writeback.py.
"""

from __future__ import annotations

import asyncio

import pytest

import src.graph.communities as comm
from src.graph.communities import detect_communities


class _RecWriteback:
    """Records every write-back call (with kwargs) in order."""

    def __init__(self, old_report_rows=None):
        self.calls: list[tuple] = []
        self._old = list(old_report_rows or [])

    def ensure_schema(self):
        self.calls.append(("ensure_schema", {}))

    def read_old_reports(self):
        self.calls.append(("read_old_reports", {}))
        return self._old

    def prune_level(self, level):
        self.calls.append(("prune_level", {"level": level}))

    def prune_all(self):
        self.calls.append(("prune_all", {}))

    def merge_community(self, **kw):
        self.calls.append(("merge_community", kw))

    def merge_subcommunity(self, **kw):
        self.calls.append(("merge_subcommunity", kw))


class _Store:
    def structured_query(self, query, param_map=None):
        return []


@pytest.fixture
def leiden(monkeypatch):
    """Pin the leidenalg backend and stub its compute + the write-back seam.

    ``leiden(rows, old_report_rows=None) -> _RecWriteback``; ``leiden.seen``
    records the kwargs ``_leiden_rows`` was called with.
    """
    import src.graph.community_writeback as community_writeback

    monkeypatch.setattr(comm.settings.temporal, "community_backend", "leidenalg")
    seen: list[dict] = []

    def _setup(rows, old_report_rows=None):
        async def fake_rows(store, **kw):
            seen.append(kw)
            return rows

        wb = _RecWriteback(old_report_rows)
        monkeypatch.setattr(comm, "_leiden_rows", fake_rows)
        # detect_* import build_community_writeback lazily from the source
        # module, so that is the patch target (see the Task 4 note below).
        monkeypatch.setattr(
            community_writeback, "build_community_writeback", lambda store: wb)
        return wb

    _setup.seen = seen
    return _setup


def _kinds(wb):
    return [k for k, _ in wb.calls]


@pytest.mark.asyncio
async def test_detect_groups_members_by_community_id(leiden):
    rows = [
        {"name": "Иванов", "communityId": 7},
        {"name": "Петров", "communityId": 7},
        {"name": "Сидоров", "communityId": 7},
        {"name": "Ромашка", "communityId": 2},
        {"name": "СтройИнвест", "communityId": 2},
        {"name": "ТехноСтрой", "communityId": 2},
    ]
    leiden(rows)
    comms = await detect_communities(_Store(), min_size=3)

    by_id = {c.community_id: c for c in comms}
    assert set(by_id) == {"7", "2"}
    assert sorted(by_id["7"].members) == ["Иванов", "Петров", "Сидоров"]
    assert by_id["2"].member_count == 3


@pytest.mark.asyncio
async def test_detect_drops_communities_below_min_size(leiden):
    rows = [
        {"name": "A", "communityId": 1},
        {"name": "B", "communityId": 1},
        {"name": "C", "communityId": 1},
        {"name": "D", "communityId": 9},  # singleton — dropped
    ]
    leiden(rows)
    comms = await detect_communities(_Store(), min_size=3)
    assert [c.community_id for c in comms] == ["1"]


@pytest.mark.asyncio
async def test_detect_prunes_prior_level_before_merges(leiden):
    """A rebuild must delete the prior level's communities (scoped to the
    requested level) BEFORE re-creating them, so ghost nodes/summaries from a
    renumbered Leiden run don't linger."""
    rows = [
        {"name": "A", "communityId": 5},
        {"name": "B", "communityId": 5},
        {"name": "C", "communityId": 5},
    ]
    wb = leiden(rows)
    await detect_communities(_Store(), min_size=3, level=2)

    kinds = _kinds(wb)
    prune_idx = kinds.index("prune_level")
    first_merge_idx = kinds.index("merge_community")
    assert prune_idx < first_merge_idx
    # Scoped to the requested level only (never global).
    assert wb.calls[prune_idx][1] == {"level": 2}
    assert "prune_all" not in kinds


@pytest.mark.asyncio
async def test_detect_failsafe_on_store_error_returns_empty(monkeypatch):
    monkeypatch.setattr(comm.settings.temporal, "community_backend", "leidenalg")

    def boom(store, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(comm, "extract_entity_edges", boom)
    comms = await detect_communities(_Store(), min_size=3)
    assert comms == []


@pytest.mark.asyncio
async def test_detect_none_store_returns_empty():
    assert await detect_communities(None, min_size=3) == []


def test_members_hash_order_insensitive():
    from src.graph.communities import members_hash
    assert members_hash(["B","A"]) == members_hash(["A","B"])
    assert len(members_hash(["A"])) == 64


def test_group_by_levels_maps_dendrogram_and_parents():
    from src.graph.communities import _group_by_levels
    # node → intermediateCommunityIds (finest..coarsest). 3 nodes, 2 levels.
    rows = [
        {"name":"a","ids":[10, 1]},
        {"name":"b","ids":[10, 1]},
        {"name":"c","ids":[11, 1]},
    ]
    levels = _group_by_levels(rows, min_size=1, max_levels=10)
    # level 0 = coarsest (id 1) holds a,b,c; level 1 (finer) has {a,b}=10, {c}=11
    l0 = {c.community_id: set(c.members) for c in levels if c.level == 0}
    l1 = {c.community_id: set(c.members) for c in levels if c.level == 1}
    assert l0 == {"1": {"a","b","c"}}
    assert l1 == {"10": {"a","b"}, "11": {"c"}}
    # parent of finer 10/11 is coarser 1
    assert all(c.parent_id == "1" for c in levels if c.level == 1)


@pytest.mark.asyncio
async def test_detect_hierarchy_materialises_levels_and_parents(leiden):
    """detect_hierarchy must prune-all before merging, write level-0
    communities with their member links, and wire level>0 PARENT_OF edges
    with the parent written FIRST (the coarsest-first invariant)."""
    from src.graph.communities import detect_hierarchy

    # 3 nodes, 2 levels (finest..coarsest): a,b in finer 10; c in finer 11;
    # all three in coarse community 1.
    rows = [
        {"name": "a", "ids": [10, 1]},
        {"name": "b", "ids": [10, 1]},
        {"name": "c", "ids": [11, 1]},
    ]
    wb = leiden(rows)
    comms = await detect_hierarchy(_Store(), max_levels=10, min_size=1)

    assert {(c.level, c.community_id) for c in comms} == {(0, "1"), (1, "10"), (1, "11")}

    kinds = _kinds(wb)
    # prune-ALL precedes the first community write
    prune_idx = kinds.index("prune_all")
    first_merge_idx = min(
        i for i, k in enumerate(kinds) if k in ("merge_community", "merge_subcommunity"))
    assert prune_idx < first_merge_idx

    # level 0 = entity member links; level>0 = PARENT_OF; parent first
    in_comm_idx = kinds.index("merge_community")
    parent_idx = kinds.index("merge_subcommunity")
    assert in_comm_idx < parent_idx   # coarsest-first: parent before child

    # the PARENT_OF write carries the coarser parent id + the child level
    parent_params = next(p for k, p in wb.calls if k == "merge_subcommunity")
    assert parent_params.get("parent_id") == "1"
    assert parent_params.get("level") == 1

    # level>0 write also links members (non-empty member list)
    assert parent_params.get("members")


# --- Phase 2b: incremental report carry-over -----------------------------


@pytest.mark.asyncio
async def test_read_old_reports_maps_level_and_hash(monkeypatch):
    """``_read_old_reports`` returns ``{(level, members_hash): {...}}`` from
    the prior build's ``:Community`` nodes."""
    import src.graph.community_writeback as community_writeback
    from src.graph.communities import _read_old_reports

    old_rows = [
        {"level": 0, "h": "hash-A", "report": '{"title":"A"}',
         "title": "A", "summary": "sum A", "report_vec": [0.1, 0.2]},
        {"level": 1, "h": "hash-B", "report": '{"title":"B"}',
         "title": "B", "summary": "sum B", "report_vec": None},
        {"level": 0, "h": None, "report": "x"},  # no hash → skipped
    ]
    wb = _RecWriteback(old_rows)
    monkeypatch.setattr(community_writeback, "build_community_writeback", lambda store: wb)
    old = await _read_old_reports(_Store())

    assert set(old) == {(0, "hash-A"), (1, "hash-B")}
    assert old[(0, "hash-A")]["report"] == '{"title":"A"}'
    assert old[(0, "hash-A")]["title"] == "A"
    assert old[(0, "hash-A")]["summary"] == "sum A"
    assert old[(0, "hash-A")]["report_vec"] == [0.1, 0.2]


@pytest.mark.asyncio
async def test_read_old_reports_none_store_returns_empty():
    from src.graph.communities import _read_old_reports
    assert await _read_old_reports(None) == {}


@pytest.mark.asyncio
async def test_detect_hierarchy_carries_unchanged_report(leiden):
    """A community whose ``(level, members_hash)`` matches a prior build's
    report keeps that report (``needs_report=False`` + report carried into
    the write); a community whose hash is NOT in the old map stays
    ``needs_report=True`` with no carried report."""
    from src.graph.communities import detect_hierarchy, members_hash

    # 3 nodes, 2 levels.  level-0 coarse community "1" = {a,b,c};
    # level-1 finer "10"={a,b}, "11"={c}.
    rows = [
        {"name": "a", "ids": [10, 1]},
        {"name": "b", "ids": [10, 1]},
        {"name": "c", "ids": [11, 1]},
    ]
    # Carry-over only for the level-0 community (members a,b,c).
    l0_hash = members_hash(["a", "b", "c"])
    old_rows = [
        {"level": 0, "h": l0_hash, "report": '{"title":"L0"}',
         "title": "L0", "summary": "sum L0", "report_vec": [0.3],
         "summarized_at": 1234567890},
        # A stale (level,hash) that is NOT among the detected ones — ignored.
        {"level": 1, "h": "stale-hash", "report": '{"x":1}',
         "title": "x", "summary": "y", "report_vec": None,
         "summarized_at": 1},
    ]
    wb = leiden(rows, old_rows)
    comms = await detect_hierarchy(_Store(), max_levels=10, min_size=1)

    by = {(c.level, c.community_id): c for c in comms}
    # level-0 community carried its report → not flagged for re-summarisation.
    assert by[(0, "1")].needs_report is False
    # level-1 communities had no matching prior report → still need one.
    assert by[(1, "10")].needs_report is True
    assert by[(1, "11")].needs_report is True

    # The old-reports read happened BEFORE the prune-all wipe.
    kinds = _kinds(wb)
    assert kinds.index("read_old_reports") < kinds.index("prune_all")

    # The level-0 write carries the report; the level-1 writes do not.
    l0_carry = next(p for k, p in wb.calls if k == "merge_community")["carry"]
    assert l0_carry.get("report") == '{"title":"L0"}'
    assert l0_carry.get("title") == "L0"
    assert l0_carry.get("summary") == "sum L0"
    assert l0_carry.get("report_vec") == [0.3]
    # The ORIGINAL summarisation time is carried (not re-stamped to now).
    assert l0_carry.get("summarized_at") == 1234567890

    l1_merges = [p for k, p in wb.calls if k == "merge_subcommunity"]
    assert l1_merges  # sanity
    for p in l1_merges:
        assert p["carry"].get("report") is None
        assert p["carry"].get("title") is None
        assert p["carry"].get("summary") is None
        assert p["carry"].get("report_vec") is None


# ── #4 follow-up: gamma (resolution) knob ────────────────────────────


@pytest.mark.asyncio
async def test_detect_forwards_gamma_to_leiden(leiden):
    rows = [
        {"name": "A", "communityId": 1},
        {"name": "B", "communityId": 1},
        {"name": "C", "communityId": 1},
    ]
    leiden(rows)
    await detect_communities(_Store(), min_size=3, gamma=3.0)
    assert leiden.seen and leiden.seen[0]["gamma"] == 3.0


@pytest.mark.asyncio
async def test_detect_hierarchy_forwards_gamma_to_leiden(leiden):
    from src.graph.communities import detect_hierarchy

    rows = [
        {"name": "A", "communityId": 1, "ids": [1, 1]},
        {"name": "B", "communityId": 1, "ids": [1, 1]},
        {"name": "C", "communityId": 1, "ids": [1, 1]},
    ]
    leiden(rows)
    await detect_hierarchy(_Store(), max_levels=2, min_size=3, gamma=2.0)
    assert leiden.seen and leiden.seen[0]["gamma"] == 2.0
    assert leiden.seen[0]["max_levels"] == 2


def test_detect_communities_params_carry_gamma_no_concurrency():
    from src.workflow.contracts import DetectCommunitiesParams

    p = DetectCommunitiesParams()
    assert p.gamma == 1.0
    assert "concurrency" not in DetectCommunitiesParams.model_fields
    p2 = DetectCommunitiesParams(gamma=2.0)
    assert p2.gamma == 2.0
    # In-flight Temporal payloads serialised before the GDS knob was removed
    # still carry ``concurrency``; the model ignores extra keys.
    legacy = DetectCommunitiesParams.model_validate(
        {"min_size": 5, "gamma": 1.5, "concurrency": 8},
    )
    assert legacy.min_size == 5 and legacy.gamma == 1.5


def test_detect_functions_have_no_concurrency_param():
    import inspect

    from src.graph.communities import detect_communities, detect_hierarchy

    assert "concurrency" not in inspect.signature(detect_communities).parameters
    assert "concurrency" not in inspect.signature(detect_hierarchy).parameters


def test_community_leiden_settings_defaults():
    from src.config import settings

    assert settings.temporal.community_leiden_gamma == 1.0
    assert not hasattr(settings.temporal, "community_leiden_concurrency")


# ── Task 4: BUILD write-back routed through the CommunityWriteback seam ──


class _FakeWriteback:
    def __init__(self):
        self.calls = []
    def ensure_schema(self): self.calls.append(("ensure_schema",))
    def read_old_reports(self):
        self.calls.append(("read_old_reports",))
        return []
    def prune_level(self, level): self.calls.append(("prune_level", level))
    def prune_all(self): self.calls.append(("prune_all",))
    def merge_community(self, **kw): self.calls.append(("merge_community", kw["community_id"], kw["level"]))
    def merge_subcommunity(self, **kw): self.calls.append(("merge_subcommunity", kw["community_id"], kw["level"]))


def test_detect_communities_routes_writeback_through_seam(monkeypatch):
    monkeypatch.setattr(comm.settings.temporal, "community_backend", "leidenalg")

    def fake_extract(store, *, batch_size=50_000):
        edges = [("a", "b", 5.0), ("b", "c", 5.0), ("a", "c", 5.0),
                 ("x", "y", 5.0), ("y", "z", 5.0), ("x", "z", 5.0), ("c", "x", 0.1)]
        return edges, list("abcxyz")
    monkeypatch.setattr(comm, "extract_entity_edges", fake_extract)

    fake = _FakeWriteback()
    # detect_communities does a LAZY per-call `from src.graph.community_writeback
    # import build_community_writeback` (module-level would create an import
    # cycle — community_writeback.py imports Cypher constants FROM
    # communities.py). That local import re-resolves fresh from the SOURCE
    # module on every call, so the patch target is the source module, not
    # `comm` (unlike `extract_entity_edges`, which IS a genuine module-level
    # import in communities.py and so is patchable via `comm` directly).
    import src.graph.community_writeback as community_writeback
    monkeypatch.setattr(community_writeback, "build_community_writeback", lambda store: fake)

    class _Store:
        def structured_query(self, cypher, param_map=None): return []
    refs = asyncio.run(comm.detect_communities(_Store(), min_size=2, level=0))
    assert len(refs) == 2
    kinds = [c[0] for c in fake.calls]
    assert kinds[0] == "ensure_schema"
    assert ("prune_level", 0) in fake.calls
    assert kinds.count("merge_community") == 2      # two cliques, single level
    assert "prune_all" not in kinds


# ── write-back failure must ABORT detection, not be swallowed ──────────────
#
# Regression: a failing :Community write was logged at WARNING and detection
# returned the refs anyway.  The caller (detect_communities_activity) then fanned
# out one summarize_community_activity per ref — 1891 LLM calls whose reports
# could not persist, because `UPDATE VERTEX ON Community` needs a vertex the
# aborted write never inserted.  Silent, expensive, total data loss.


class _ExplodingWriteback(_FakeWriteback):
    def merge_community(self, **kw):
        raise RuntimeError("nGQL failed: SyntaxError: Query is too large")
    def merge_subcommunity(self, **kw):
        raise RuntimeError("nGQL failed: SyntaxError: Query is too large")


def _patch_two_cliques(monkeypatch, writeback):
    monkeypatch.setattr(comm.settings.temporal, "community_backend", "leidenalg")

    def fake_extract(store, *, batch_size=50_000):
        edges = [("a", "b", 5.0), ("b", "c", 5.0), ("a", "c", 5.0),
                 ("x", "y", 5.0), ("y", "z", 5.0), ("x", "z", 5.0), ("c", "x", 0.1)]
        return edges, list("abcxyz")
    monkeypatch.setattr(comm, "extract_entity_edges", fake_extract)
    import src.graph.community_writeback as community_writeback
    monkeypatch.setattr(
        community_writeback, "build_community_writeback", lambda store: writeback)

    class _Store:
        def structured_query(self, cypher, param_map=None): return []
    return _Store()


def test_detect_communities_raises_when_writeback_fails(monkeypatch):
    store = _patch_two_cliques(monkeypatch, _ExplodingWriteback())
    with pytest.raises(RuntimeError, match="Query is too large"):
        asyncio.run(comm.detect_communities(store, min_size=2, level=0))


def test_detect_hierarchy_raises_when_writeback_fails(monkeypatch):
    store = _patch_two_cliques(monkeypatch, _ExplodingWriteback())
    with pytest.raises(RuntimeError, match="Query is too large"):
        asyncio.run(comm.detect_hierarchy(store, max_levels=2, min_size=2))
