"""apply_proposal на фейковых TelegramOps, реестре и клиенте приёма."""

import datetime as dt

import pytest

from src.intake.client import FAILED, SENT, Result
from src.intake.sources import service
from src.intake.sources.proposals import BadProposal, ProposalItem, ProposalStore
from src.intake.sources.service import apply_proposal
from src.intake.sources.telegram import FloodWait, FolderNotFound


class _Msg:
    def __init__(self, id, text="текст", day=3):
        self.id = id
        self.message = text
        self.date = dt.datetime(2026, 10, day, 12, 0, tzinfo=dt.UTC)


class _Ops:
    def __init__(
        self, log, flood_on=None, flood_at="join", history=None, no_folder=(),
        leave_fails=False,
    ):
        self.log = log
        self.leave_fails = leave_fails
        self.flood_on = flood_on
        self.flood_at = flood_at
        self.hist = history if history is not None else {}
        self.no_folder = set(no_folder)

    def _maybe_flood(self, step, peer_id):
        if step == self.flood_at and peer_id == self.flood_on:
            raise FloodWait(30)

    async def join(self, peer_id):
        self._maybe_flood("join", peer_id)
        self.log.append(("join", peer_id))

    async def add_to_folder(self, peer_id, folder):
        if folder in self.no_folder:
            raise FolderNotFound(folder)
        self._maybe_flood("folder", peer_id)
        self.log.append(("folder", peer_id, folder))

    async def leave(self, peer_id):
        self.log.append(("leave", peer_id))
        if self.leave_fails:
            raise RuntimeError("leave упал")

    async def history(self, peer_id, limit):
        self._maybe_flood("history", peer_id)
        self.log.append(("history", peer_id, limit))
        return self.hist.get(peer_id, [])  # как у Telethon: новые первыми


class _Repo:
    """Реестр с той же семантикой UPSERT, что и у SourceRepository.add."""

    def __init__(self, log, fail_on=()):
        self.log = log
        self.rows = {}
        self.fail_on = set(fail_on)

    async def add(self, peer_id, slug, title, group_name, *, added_by):
        self.log.append(("add", peer_id))
        if peer_id in self.fail_on:
            raise RuntimeError("реестр недоступен")
        old = self.rows.get(peer_id, {})
        self.rows[peer_id] = {
            "slug": slug, "title": title, "group_name": group_name,
            "added_by": added_by, "state": "active",
            "trust": old.get("trust"), "note": old.get("note", ""),
        }


class _Posts(list):
    outcomes: dict


@pytest.fixture
def posts(monkeypatch):
    sent = _Posts()
    sent.outcomes = outcomes = {}

    async def fake_post(http, api_base, api_key, **kw):
        sent.append({"http": http, "api_base": api_base, "api_key": api_key, **kw})
        return Result(outcome=outcomes.get(kw["filename"], SENT))

    monkeypatch.setattr(service, "post_document", fake_post)
    return sent


def _item(peer_id, slug="chan", group="news"):
    return ProposalItem(peer_id=peer_id, slug=slug, title=f"T{peer_id}", group_name=group)


def _kit(items, **ops_kw):
    log = []
    store = ProposalStore()
    return log, store, store.create(items), _Ops(log, **ops_kw), _Repo(log)


async def _apply(store, ops, repo, p, code=None, peers=None, bootstrap=100):
    return await apply_proposal(
        store, ops, repo, p.id, p.code if code is None else code,
        peers if peers is not None else [i.peer_id for i in p.items],
        added_by="alice", bootstrap=bootstrap,
        http="HTTP", api_base="http://api", api_key="k",
    )


async def test_applies_in_order_with_folder_from_the_proposal(posts):
    log, store, p, ops, repo = _kit([_item(1, "alpha", "digest")])
    ops.hist[1] = [_Msg(12, "новое"), _Msg(11, "старое")]
    res = await _apply(store, ops, repo, p)
    assert log == [
        ("join", 1), ("folder", 1, "digest"), ("add", 1), ("history", 1, 100),
    ]
    assert repo.rows[1]["added_by"] == "alice"
    assert repo.rows[1]["group_name"] == "digest" and repo.rows[1]["slug"] == "alpha"
    assert res.connected == [1] and res.skipped == [] and res.bootstrapped == 2


async def test_bootstrap_documents_look_like_sweep_documents(posts):
    _log, store, p, ops, repo = _kit([_item(1, "alpha", "digest")])
    ops.hist[1] = [_Msg(12, "новое", day=4), _Msg(11, "старое", day=3)]
    await _apply(store, ops, repo, p)
    # старые первыми, как в sync_round
    assert [d["filename"] for d in posts] == ["tg_alpha_11.txt", "tg_alpha_12.txt"]
    first = posts[0]
    assert first["content"] == "старое".encode()
    assert first["data"] == {
        "document_date": "2026-10-03", "group": "digest", "channel": "alpha",
    }
    assert (first["http"], first["api_base"], first["api_key"]) == ("HTTP", "http://api", "k")


async def test_slugless_channel_is_named_by_peer_id(posts):
    _log, store, p, ops, repo = _kit([_item(-1001, slug="")])
    ops.hist[-1001] = [_Msg(5)]
    await _apply(store, ops, repo, p)
    assert posts[0]["filename"] == "tg_-1001_5.txt"
    assert posts[0]["data"]["channel"] == "-1001"


async def test_empty_messages_are_not_posted_and_failed_not_counted(posts):
    _log, store, p, ops, repo = _kit([_item(1, "alpha")])
    ops.hist[1] = [_Msg(3), _Msg(2, "   "), _Msg(1)]
    posts.outcomes["tg_alpha_1.txt"] = FAILED
    res = await _apply(store, ops, repo, p)
    assert [d["filename"] for d in posts] == ["tg_alpha_1.txt", "tg_alpha_3.txt"]
    assert res.bootstrapped == 1 and res.connected == [1]


async def test_bootstrap_zero_reads_no_history(posts):
    log, store, p, ops, repo = _kit([_item(1)])
    res = await _apply(store, ops, repo, p, bootstrap=0)
    assert ("history", 1, 0) not in log and not any(c[0] == "history" for c in log)
    assert res.connected == [1] and res.bootstrapped == 0


async def test_wrong_code_touches_nothing(posts):
    log, store, p, ops, repo = _kit([_item(1)])
    with pytest.raises(BadProposal):
        await _apply(store, ops, repo, p, code="ZZZZZZ")
    assert log == [] and repo.rows == {} and posts == []


async def test_replay_is_rejected(posts):
    log, store, p, ops, repo = _kit([_item(1)])
    await _apply(store, ops, repo, p)
    log.clear()
    with pytest.raises(BadProposal):
        await _apply(store, ops, repo, p)
    assert log == []


async def test_floodwait_stops_traversal_and_keeps_the_first(posts):
    log, store, p, ops, repo = _kit(
        [_item(1, "a"), _item(2, "b"), _item(3, "c")], flood_on=2, flood_at="join",
    )
    ops.hist[1] = [_Msg(1)]
    res = await _apply(store, ops, repo, p)
    assert res.connected == [1]
    assert [pid for pid, _ in res.skipped] == [2, 3]
    assert all("подождать" in why for _, why in res.skipped)
    assert list(repo.rows) == [1]
    assert ("join", 3) not in log


async def test_floodwait_in_folder_rolls_back_the_join(posts):
    log, store, p, ops, repo = _kit([_item(1), _item(2)], flood_on=1, flood_at="folder")
    res = await _apply(store, ops, repo, p)
    assert res.connected == [] and [pid for pid, _ in res.skipped] == [1, 2]
    assert repo.rows == {}
    assert ("leave", 1) in log and ("join", 2) not in log


async def test_floodwait_during_bootstrap_keeps_the_peer_connected(posts):
    log, store, p, ops, repo = _kit([_item(1), _item(2)], flood_on=1, flood_at="history")
    res = await _apply(store, ops, repo, p)
    assert res.connected == [1] and [pid for pid, _ in res.skipped] == [2]
    assert list(repo.rows) == [1] and ("join", 2) not in log


async def test_missing_folder_rolls_back_and_skips_that_peer_only(posts):
    log, store, p, ops, repo = _kit(
        [_item(1, group="digest"), _item(2, group="news")], no_folder={"digest"},
    )
    res = await _apply(store, ops, repo, p)
    assert res.connected == [2]
    assert [pid for pid, _ in res.skipped] == [1]
    assert list(repo.rows) == [2]
    assert ("leave", 1) in log and ("leave", 2) not in log
    assert ("join", 2) in log


async def test_registry_failure_rolls_back_and_does_not_raise(posts):
    log, store, p, ops, repo = _kit([_item(1), _item(2)])
    repo.fail_on = {1}
    res = await _apply(store, ops, repo, p)
    assert res.connected == [2]
    assert [pid for pid, _ in res.skipped] == [1]
    assert "реестр недоступен" in dict(res.skipped)[1]
    assert ("leave", 1) in log and ("leave", 2) not in log
    assert list(repo.rows) == [2]


async def test_failed_rollback_asks_for_manual_cleanup(posts):
    log, store, p, ops, repo = _kit(
        [_item(1, group="digest")], no_folder={"digest"}, leave_fails=True,
    )
    res = await _apply(store, ops, repo, p)
    assert res.connected == [] and repo.rows == {}
    assert ("leave", 1) in log
    assert "ручная чистка" in dict(res.skipped)[1]


async def test_other_join_error_skips_the_peer_and_continues(posts):
    log, store, p, ops, repo = _kit([_item(1), _item(2)])

    async def boom(peer_id):
        if peer_id == 1:
            raise RuntimeError("канал закрыт")
        log.append(("join", peer_id))

    ops.join = boom
    res = await _apply(store, ops, repo, p)
    assert res.connected == [2] and "канал закрыт" in dict(res.skipped)[1]
    assert ("leave", 1) not in log  # вступления не было, откатывать нечего


async def test_history_floodwait_is_reported_in_partial(posts):
    _log, store, p, ops, repo = _kit([_item(1)], flood_on=1, flood_at="history")
    res = await _apply(store, ops, repo, p)
    assert res.connected == [1] and res.skipped == []
    assert [pid for pid, _ in res.partial] == [1]
    assert "подождать" in res.partial[0][1]


async def test_peer_ids_is_a_subset_filter_over_the_proposal(posts):
    log, store, p, ops, repo = _kit([_item(1), _item(2)])
    res = await _apply(store, ops, repo, p, peers=[2, 99])
    assert res.connected == [2]
    skipped = dict(res.skipped)
    assert 99 in skipped and "предложени" in skipped[99]
    assert ("join", 99) not in log and ("join", 1) not in log
    assert list(repo.rows) == [2]


async def test_left_channel_is_reactivated_keeping_operator_fields(posts):
    _log, store, p, ops, repo = _kit([_item(1, "new", "news")])
    repo.rows[1] = {
        "slug": "old", "title": "Old", "group_name": "digest", "added_by": "bob",
        "state": "left", "trust": 0.9, "note": "проверен",
    }
    await _apply(store, ops, repo, p)
    row = repo.rows[1]
    assert row["state"] == "active" and row["slug"] == "new"
    assert row["trust"] == 0.9 and row["note"] == "проверен"
