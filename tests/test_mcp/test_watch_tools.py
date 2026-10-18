"""Entity-watch MCP tool helpers (tools_server) over stub repositories."""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.graph.nebula_store import entity_vid
from src.mcp import tools_server as ts
from src.tenancy.context import new_graph_context

G = new_graph_context("acme")
DOC = "d0c5e6a0-0000-0000-0000-000000000001"


class _Search:
    def __init__(self, exact=(), substring=()):
        self.exact = list(exact)
        self.substring = list(substring)
        self.calls: list[str] = []

    async def search(self, query, *, mode="substring", label=None, limit=10):
        self.calls.append(mode)
        return self.exact if mode == "exact" else self.substring


class _Watch:
    def __init__(self, feed_rows=(), watches=()):
        self.added: list[tuple] = []
        self.removed: list[tuple] = []
        self.seen: list[tuple] = []
        self.acked: list[tuple] = []
        self._feed = list(feed_rows)
        self._watches = list(watches)

    async def add_watch(self, owner, vid, name, *, kinds=None, note=""):
        self.added.append((owner, vid, name, kinds, note))

    async def remove_watch(self, owner, vid):
        self.removed.append((owner, vid))
        return True

    async def list_watch(self, owner):
        return self._watches

    async def feed(self, owner, *, include_acked, limit):
        self.feed_args = (owner, include_acked, limit)
        return self._feed

    async def mark_seen(self, owner, ids):
        self.seen.append((owner, ids))

    async def ack(self, owner, *, event_ids=None, all_events=False):
        self.acked.append((owner, event_ids, all_events))
        return len(event_ids or []) or 7


@pytest.fixture
def repos(monkeypatch):
    def _set(search=None, watch=None):
        search = search or _Search()
        watch = watch or _Watch()
        def _scoped(repo):
            def _get(graph):
                # every helper reaches the repositories through the tool's graph
                assert graph is G
                return repo
            return _get

        monkeypatch.setattr(ts, "_entity_search", _scoped(search))
        monkeypatch.setattr(ts, "_watch_repo", _scoped(watch))
        return search, watch
    return _set


def _ent(name, label="Person", mc=3):
    return {"vid": entity_vid(name), "name": name, "label": label,
            "description": "", "mention_count": mc}


# ── kb_watch ─────────────────────────────────────────────────────────


async def test_watch_exact_name_subscribes(repos):
    _, watch = repos(search=_Search(exact=[_ent("Блинов Андрей Степанович")]))
    out = await ts._watch("Блинов Андрей Степанович", None, "КУСП 805", graph=G)
    assert out["status"] == "watching"
    assert watch.added == [("default", entity_vid("Блинов Андрей Степанович"),
                            "Блинов Андрей Степанович", [], "КУСП 805")]


async def test_watch_single_fuzzy_hit_subscribes(repos):
    _, watch = repos(search=_Search(substring=[_ent("Блинов Андрей Степанович")]))
    out = await ts._watch("Блинов", None, "", graph=G)
    assert out["status"] == "watching" and len(watch.added) == 1


async def test_watch_ambiguous_returns_candidates_without_subscribing(repos):
    _, watch = repos(search=_Search(substring=[_ent("Блинов А.С."), _ent("Блинов Андрей Степанович")]))
    out = await ts._watch("Блинов", None, "", graph=G)
    assert out["status"] == "ambiguous"
    assert [c["name"] for c in out["candidates"]] == ["Блинов А.С.", "Блинов Андрей Степанович"]
    assert watch.added == []


async def test_watch_not_found(repos):
    repos()
    out = await ts._watch("Никто", None, "", graph=G)
    assert out["status"] == "not_found"


async def test_watch_rejects_unknown_kinds(repos):
    _, watch = repos(search=_Search(exact=[_ent("A")]))
    out = await ts._watch("A", ["new_mention", "gossip"], "", graph=G)
    assert "error" in out and watch.added == []


# ── kb_unwatch / kb_watchlist ────────────────────────────────────────


async def test_unwatch_by_name_or_vid(repos):
    vid = entity_vid("Блинов")
    _, watch = repos(watch=_Watch(watches=[{"entity_vid": vid, "entity_name": "Блинов"}]))
    assert (await ts._unwatch("Блинов", graph=G))["status"] == "removed"
    assert (await ts._unwatch(vid, graph=G))["status"] == "removed"
    assert watch.removed == [("default", vid), ("default", vid)]


async def test_unwatch_unknown(repos):
    repos()
    assert (await ts._unwatch("Никто", graph=G))["status"] == "not_watched"


async def test_watchlist_is_json_safe(repos):
    created = datetime(2026, 10, 15, 10, 0, tzinfo=UTC)
    repos(watch=_Watch(watches=[{"entity_vid": "v", "entity_name": "Блинов", "kinds": [],
                                 "muted_until": None, "note": "", "created_at": created}]))
    out = await ts._watchlist(graph=G)
    assert out["watches"][0]["created_at"] == created.isoformat()


# ── kb_watch_feed ────────────────────────────────────────────────────


def _row(i, kind, doc, *, name="Блинов", detail=None, why="w", at=0):
    return {"id": i, "entity_vid": entity_vid(name), "entity_name": name, "kind": kind,
            "doc_id": doc, "doc_date": date(2024, 3, 12) if doc else None,
            "detail": detail or {}, "why": why,
            "detected_at": datetime(2026, 10, 15, 9, 45 + at, tzinfo=UTC),
            "seen_at": None, "acked_at": None,
            "doc_path": f"s3://kb-uploads/{doc}/Протокол допроса.docx" if doc else None}


def test_feed_cards_group_events_by_document_newest_first():
    rows = [
        _row(3, "new_connection", DOC, detail={"other": "Самойлов"}, at=2),
        _row(2, "new_identifier", DOC, detail={"other": "+79161234567"}, at=1),
        _row(1, "contradiction", None, at=0),
    ]
    cards = ts.build_feed_cards(rows)
    assert len(cards) == 2
    first = cards[0]
    assert first["doc_id"] == DOC
    assert first["doc_title"] == "Протокол допроса.docx"
    assert first["doc_date"] == "2024-03-12"
    assert first["link"] == f"/api/v1/documents/{DOC}"
    assert [e["id"] for e in first["events"]] == [3, 2]
    assert first["events"][0]["entity"] == "Блинов"
    assert cards[1]["doc_id"] is None and cards[1]["link"] is None


def test_feed_card_link_follows_configured_template(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(
        settings.monitor, "document_link",
        "http://10.10.113.12:8090/api/documents/{doc_id}?variant=original",
    )
    cards = ts.build_feed_cards([_row(1, "new_mention", DOC)])
    assert cards[0]["link"] == f"http://10.10.113.12:8090/api/documents/{DOC}?variant=original"


async def test_feed_marks_returned_events_seen(repos):
    _, watch = repos(watch=_Watch(feed_rows=[_row(5, "new_mention", DOC)]))
    out = await ts._watch_feed(False, 20, graph=G)
    assert out["count"] == 1 and len(out["cards"]) == 1
    assert watch.feed_args == ("default", False, 20)
    assert watch.seen == [("default", [5])]


# ── kb_ack ───────────────────────────────────────────────────────────


async def test_ack_ids(repos):
    _, watch = repos()
    out = await ts._ack([1, 2], False, graph=G)
    assert out == {"acked": 2}
    assert watch.acked == [("default", [1, 2], False)]


async def test_ack_all(repos):
    repos()
    assert (await ts._ack(None, True, graph=G))["acked"] == 7


async def test_ack_needs_ids_or_all(repos):
    repos()
    assert "error" in await ts._ack(None, False, graph=G)


# ── every graph (the monitor sweep covers default + every ready graph) ──

_WATCH_TOOL_CALLS = [
    ("kb_watch", ("Иванов",), {}),
    ("kb_unwatch", ("Иванов",), {}),
    ("kb_watchlist", (), {}),
    ("kb_watch_feed", (), {}),
    ("kb_ack", (), {"all": True}),
]


@pytest.mark.parametrize("tool,args,kwargs", _WATCH_TOOL_CALLS)
async def test_watch_tools_accept_non_default_graph(monkeypatch, tool, args, kwargs):
    # `action` is what the tool asks to be authorized for; which tool asks for
    # which is pinned in tests/test_mcp/test_tool_authz.py.
    async def _acme(action=None):
        return G

    graphs: list[str] = []

    def _repo(graph):
        graphs.append(graph.id)
        raise RuntimeError("repo reached")

    monkeypatch.setattr(ts, "current_graph", _acme)
    monkeypatch.setattr(ts, "_entity_search", _repo)
    monkeypatch.setattr(ts, "_watch_repo", _repo)
    with pytest.raises(RuntimeError, match="repo reached"):
        await getattr(ts, tool)(*args, **kwargs)
    # the repository is reached, scoped to the non-default graph
    assert graphs and set(graphs) == {"acme"}


async def test_watch_tools_run_on_default_graph(monkeypatch):
    from src.tenancy.context import default_graph_context

    async def _default(action=None):
        return default_graph_context()

    watch = _Watch(watches=[{"entity_vid": "v", "entity_name": "X"}])
    monkeypatch.setattr(ts, "current_graph", _default)
    monkeypatch.setattr(ts, "_watch_repo", lambda graph: watch)
    assert (await ts.kb_watchlist())["watches"] == [{"entity_vid": "v", "entity_name": "X"}]
    assert (await ts.kb_ack(all=True)) == {"acked": 7}
