"""Entity-watch MCP tool helpers (tools_server) over stub repositories."""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.graph.name_resolution import Candidate, Resolution
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

    async def add_watch(self, owner, vid, name, *, kinds=None, note="",
                        webhook_url="", created_by=""):
        self.added.append((owner, vid, name, kinds, note, webhook_url, created_by))

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


class _Resolver:
    def __init__(self, res):
        self.res = res
        self.calls: list[tuple] = []

    async def resolve(self, name, k=5):
        self.calls.append((name, k))
        return self.res


def _cand(name, via=("casefold",), score=0.9, label="Person", mc=3):
    return Candidate(name=name, score=score, matched_via=list(via),
                     matched_text=name, label=label, mention_count=mc)


@pytest.fixture
def repos(monkeypatch):
    def _set(search=None, watch=None, resolver=None):
        # без резолвера — прежний путь через зеркало
        async def _res(graph):
            return resolver

        monkeypatch.setattr(ts, "_resolver", _res)
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
                            "Блинов Андрей Степанович", [], "КУСП 805", "", "")]


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


# ── kb_watch через резолвер имён ─────────────────────────────────────


@pytest.mark.parametrize("typed,via,score", [
    ("Полякова", ["case-stem"], 0.82),
    ("Поляков С.Н.", ["initials"], 0.88),
    ("Likhachev", ["translit"], 0.8),
])
async def test_watch_resolver_subscribes_to_canonical(repos, typed, via, score):
    canon = "Поляков Сергей Николаевич"
    resolver = _Resolver(Resolution(query=typed, chosen=_cand(canon, via, score)))
    search, watch = repos(search=_Search(exact=[_ent(canon, mc=9)]), resolver=resolver)
    out = await ts._watch(typed, None, "", graph=G)
    assert out["status"] == "watching"
    assert out["entity"] == {"vid": entity_vid(canon), "name": canon,
                             "label": "Person", "mention_count": 9}
    assert out["matched_via"] == via and out["score"] == round(score, 3)
    assert watch.added[0][1:3] == (entity_vid(canon), canon)
    assert resolver.calls == [(typed, 10)]
    assert search.calls == ["exact"]  # один точный запрос за vid


async def test_watch_resolver_ambiguous_subscribes_to_nothing(repos):
    res = Resolution(query="Поляков", chosen=_cand("Поляков А.", ["prefix"], 0.7),
                     alternatives=[_cand("Поляков Б.", ["prefix"], 0.69, mc=5)],
                     ambiguous=True)
    _, watch = repos(resolver=_Resolver(res))
    out = await ts._watch("Поляков", None, "", graph=G)
    assert out["status"] == "ambiguous" and out["query"] == "Поляков"
    assert [c["name"] for c in out["candidates"]] == ["Поляков А.", "Поляков Б."]
    assert out["candidates"][0]["matched_via"] == ["prefix"]
    assert out["candidates"][1]["score"] == 0.69
    assert out["candidates"][1]["mention_count"] == 5
    assert watch.added == []


async def test_watch_resolver_not_found_passes_alternatives(repos):
    res = Resolution(query="Икс", alternatives=[_cand("Икс-Групп", ["trigram"], 0.4)])
    _, watch = repos(resolver=_Resolver(res))
    out = await ts._watch("Икс", None, "", graph=G)
    assert out["status"] == "not_found" and out["query"] == "Икс"
    assert [c["name"] for c in out["candidates"]] == ["Икс-Групп"]
    assert watch.added == []


async def test_watch_resolver_not_found_without_alternatives(repos):
    _, watch = repos(resolver=_Resolver(Resolution(query="Икс")))
    out = await ts._watch("Икс", None, "", graph=G)
    assert out == {"status": "not_found", "query": "Икс"} and watch.added == []


async def test_watch_vid_falls_back_to_graph_identity(repos):
    canon = "ГК «Росатом»"
    res = Resolution(query="Росатом", chosen=_cand(canon, ["legal-form"], 0.9, "Organization"))
    _, watch = repos(search=_Search(), resolver=_Resolver(res))  # зеркало пусто
    out = await ts._watch("Росатом", None, "", graph=G)
    assert out["status"] == "watching"
    assert watch.added[0][1] == entity_vid(canon)
    assert out["entity"]["vid"] == entity_vid(canon)
    assert out["entity"]["label"] == "Organization"


async def test_watch_without_resolver_one_exact_hit(repos):
    _, watch = repos(search=_Search(exact=[_ent("Блинов")]), resolver=None)
    out = await ts._watch("Блинов", None, "", graph=G)
    assert out["status"] == "watching" and "matched_via" not in out
    assert len(watch.added) == 1


async def test_watch_without_resolver_ambiguous_substring(repos):
    search, watch = repos(search=_Search(substring=[_ent("Блинов А"), _ent("Блинов Б")]))
    out = await ts._watch("Блинов", None, "", graph=G)
    assert out["status"] == "ambiguous" and search.calls == ["exact", "substring"]
    assert watch.added == []


# ── kb_unwatch / kb_watchlist ────────────────────────────────────────


async def test_unwatch_by_name_or_vid(repos):
    vid = entity_vid("Блинов")
    _, watch = repos(watch=_Watch(watches=[{"entity_vid": vid, "entity_name": "Блинов"}]))
    assert (await ts._unwatch("Блинов", graph=G))["status"] == "removed"
    assert (await ts._unwatch(vid, graph=G))["status"] == "removed"
    assert watch.removed == [("default", vid), ("default", vid)]


async def test_unwatch_accepts_the_form_the_watch_was_made_with(repos):
    """Подписка хранит каноническое имя; снимать её должно получаться тем же
    написанием, каким ставили — иначе подписку не убрать своими словами."""
    from src.graph.name_resolution import Candidate, Resolution

    canonical = "Поляков Сергей Николаевич"
    vid = entity_vid(canonical)

    class _Resolver:
        async def resolve(self, name, **kw):
            return Resolution(
                query=name,
                chosen=Candidate(name=canonical, score=0.93,
                                 matched_via=["stem"], label="Person"),
            )

    _, watch = repos(
        watch=_Watch(watches=[{"entity_vid": vid, "entity_name": canonical}]),
        resolver=_Resolver(),
    )
    out = await ts._unwatch("Полякова", graph=G)
    assert out["status"] == "removed" and out["entity"] == canonical
    assert out["matched_via"] == ["stem"] and out["score"] == 0.93
    assert watch.removed == [("default", vid)]


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
