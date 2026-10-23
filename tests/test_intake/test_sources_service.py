"""move_source, leave_source, set_source_trust на фейках: ни Postgres, ни телеграма."""

from types import SimpleNamespace

import pytest

from src.intake.sources import service
from src.intake.sources.proposals import (
    CONNECT,
    LEAVE,
    MOVE,
    BadProposal,
    ProposalItem,
    ProposalStore,
)
from src.intake.sources.service import (
    AmbiguousMove,
    leave_source,
    move_source,
    set_source_trust,
)
from src.intake.sources.telegram import FloodWait, FolderNotEditable, FolderNotFound


class _Ops:
    def __init__(self, log, no_folder=(), fail=None):
        self.log = log
        self.no_folder = set(no_folder)
        # имя операции или пара (операция, папка) -> исключение
        self.fail = fail or {}

    def _maybe_fail(self, name, folder=None):
        if (name, folder) in self.fail:
            raise self.fail[(name, folder)]
        if name in self.fail:
            raise self.fail[name]

    async def add_to_folder(self, peer_id, folder):
        self.log.append(("add_folder", peer_id, folder))
        if folder in self.no_folder:
            raise FolderNotFound(folder)
        self._maybe_fail("add_folder", folder)

    async def remove_from_folder(self, peer_id, folder):
        self.log.append(("remove_folder", peer_id, folder))
        self._maybe_fail("remove_folder", folder)

    async def leave(self, peer_id):
        self.log.append(("leave", peer_id))
        self._maybe_fail("leave")

    # всё, что трогает курсор диалога / приём документов, — запись и провал
    async def history(self, peer_id, limit):
        self.log.append(("history", peer_id, limit))
        return []

    async def join(self, peer_id):
        self.log.append(("join", peer_id))


class _Repo:
    def __init__(self, log, fail_on=()):
        self.log = log
        self.rows = {}
        self.fail_on = set(fail_on)

    def seed(self, peer_id, group="news", state="active", trust=None):
        self.rows[peer_id] = {
            "slug": "chan", "title": "T", "group_name": group, "added_by": "bob",
            "state": state, "trust": trust, "note": "",
        }

    async def get(self, peer_id):
        row = self.rows.get(peer_id)
        return None if row is None else SimpleNamespace(**row, peer_id=peer_id)

    async def set_group(self, peer_id, group):
        self.log.append(("set_group", peer_id, group))
        if "set_group" in self.fail_on:
            raise RuntimeError("реестр недоступен")
        if peer_id not in self.rows:
            return False
        self.rows[peer_id]["group_name"] = group
        return True

    async def mark_left(self, peer_id):
        self.log.append(("mark_left", peer_id))
        if "mark_left" in self.fail_on:
            raise RuntimeError("реестр недоступен")
        if peer_id not in self.rows:
            return False
        self.rows[peer_id]["state"] = "left"
        return True

    async def set_trust(self, peer_id, trust):
        self.log.append(("set_trust", peer_id, trust))
        if peer_id not in self.rows:
            return False
        self.rows[peer_id]["trust"] = trust
        return True


@pytest.fixture
def ingest(monkeypatch):
    """Приём не должен вызываться вовсе: любой post_document — провал."""
    calls = []

    async def fake_post(*a, **kw):
        calls.append((a, kw))
        raise AssertionError("move/leave/trust не должны писать в приём")

    monkeypatch.setattr(service, "post_document", fake_post)
    return calls


def _kit(peer=1, group="news", extra=(), action=MOVE, **ops_kw):
    """`extra` — активные каналы реестра, которых НЕТ в предложении."""
    log = []
    store = ProposalStore()
    p = store.create([ProposalItem(peer, "chan", "T", group)], action)
    repo = _Repo(log)
    repo.seed(peer, group)
    for other in extra:
        repo.seed(other, group)
    return log, store, p, _Ops(log, **ops_kw), repo


def _only_account_calls(log):
    return [c for c in log if c[0] in {"history", "join"}]


# --- move_source ---

async def test_move_removes_from_old_adds_to_new_and_records_group(ingest):
    log, store, p, ops, repo = _kit(group="news")
    await move_source(store, ops, repo, p.id, p.code, 1, "digest")
    assert log == [
        ("add_folder", 1, "digest"), ("remove_folder", 1, "news"),
        ("set_group", 1, "digest"),
    ]
    assert repo.rows[1]["group_name"] == "digest"
    assert _only_account_calls(log) == [] and ingest == []


async def test_move_into_unknown_group_is_refused_before_telegram(ingest):
    log, store, p, ops, repo = _kit()
    with pytest.raises(ValueError):
        await move_source(store, ops, repo, p.id, p.code, 1, "memes")
    assert log == [] and repo.rows[1]["group_name"] == "news"
    # предложение не сожжено отказом по папке
    await move_source(store, ops, repo, p.id, p.code, 1, "digest")
    assert repo.rows[1]["group_name"] == "digest"


async def test_move_into_missing_telegram_folder_leaves_account_as_is(ingest):
    log, store, p, ops, repo = _kit(no_folder={"digest"})
    with pytest.raises(FolderNotFound):
        await move_source(store, ops, repo, p.id, p.code, 1, "digest")
    assert log == [("add_folder", 1, "digest")]
    assert repo.rows[1]["group_name"] == "news"


async def test_move_remove_old_not_found_completes_the_move(ingest):
    # канала в старой папке уже нет — это не провал переноса
    log, store, p, ops, repo = _kit(
        fail={("remove_folder", "news"): FolderNotFound("news")},
    )
    await move_source(store, ops, repo, p.id, p.code, 1, "digest")
    assert log == [
        ("add_folder", 1, "digest"), ("remove_folder", 1, "news"),
        ("set_group", 1, "digest"),
    ]
    assert repo.rows[1]["group_name"] == "digest"


async def test_move_ambiguous_remove_old_failure_is_not_undone(ingest):
    log, store, p, ops, repo = _kit(
        fail={("remove_folder", "news"): FloodWait(30)},
    )
    with pytest.raises(AmbiguousMove) as ei:
        await move_source(store, ops, repo, p.id, p.code, 1, "digest")
    assert log == [("add_folder", 1, "digest"), ("remove_folder", 1, "news")]
    assert repo.rows[1]["group_name"] == "news"
    msg = str(ei.value)
    assert "news" in msg and "digest" in msg and "повтор" in msg
    assert (ei.value.old, ei.value.new, ei.value.seconds) == ("news", "digest", 30)
    assert isinstance(ei.value.__cause__, FloodWait)


async def test_move_ambiguous_failure_without_floodwait_has_no_seconds(ingest):
    _log, store, p, ops, repo = _kit(
        fail={("remove_folder", "news"): ConnectionError("обрыв")},
    )
    with pytest.raises(AmbiguousMove) as ei:
        await move_source(store, ops, repo, p.id, p.code, 1, "digest")
    assert ei.value.seconds is None
    assert (ei.value.old, ei.value.new) == ("news", "digest")
    assert isinstance(ei.value.__cause__, ConnectionError)


async def test_move_remove_old_from_chatlist_fails_loudly_without_set_group(ingest):
    # общий список редактировать нельзя: канал по-прежнему в старой папке
    log, store, p, ops, repo = _kit(
        fail={("remove_folder", "news"): FolderNotEditable("news")},
    )
    with pytest.raises(FolderNotEditable) as ei:
        await move_source(store, ops, repo, p.id, p.code, 1, "digest")
    assert log == [("add_folder", 1, "digest"), ("remove_folder", 1, "news")]
    assert repo.rows[1]["group_name"] == "news"
    msg = str(ei.value)
    assert "общий" in msg and "news" in msg and "по-прежнему" in msg


async def test_move_registry_failure_puts_the_channel_back(ingest):
    log, store, p, ops, repo = _kit()
    repo.fail_on = {"set_group"}
    with pytest.raises(RuntimeError):
        await move_source(store, ops, repo, p.id, p.code, 1, "digest")
    assert log == [
        ("add_folder", 1, "digest"), ("remove_folder", 1, "news"),
        ("set_group", 1, "digest"),
        ("add_folder", 1, "news"), ("remove_folder", 1, "digest"),
    ]
    assert repo.rows[1]["group_name"] == "news"


async def test_move_undo_readd_failed_leaves_the_channel_in_neither_folder(ingest):
    log, store, p, ops, repo = _kit(
        fail={("add_folder", "news"): FloodWait(7)},
    )
    repo.fail_on = {"set_group"}
    with pytest.raises(AmbiguousMove) as ei:
        await move_source(store, ops, repo, p.id, p.code, 1, "digest")
    assert log[-2:] == [("add_folder", 1, "news"), ("remove_folder", 1, "digest")]
    msg = str(ei.value)
    assert "ни в одной" in msg and "news" in msg and "digest" in msg
    assert "в обеих" not in msg
    assert ei.value.seconds == 7 and (ei.value.old, ei.value.new) == ("news", "digest")
    assert isinstance(ei.value.__cause__, RuntimeError)
    assert repo.rows[1]["group_name"] == "news"


async def test_move_undo_remove_new_failed_leaves_the_channel_in_both_folders(ingest):
    _log, store, p, ops, repo = _kit(
        fail={("remove_folder", "digest"): ConnectionError("обрыв")},
    )
    repo.fail_on = {"set_group"}
    with pytest.raises(AmbiguousMove) as ei:
        await move_source(store, ops, repo, p.id, p.code, 1, "digest")
    msg = str(ei.value)
    assert "в обеих" in msg and "ни в одной" not in msg
    assert ei.value.seconds is None


async def test_move_both_undo_steps_failed_leaves_the_channel_only_in_the_new(ingest):
    _log, store, p, ops, repo = _kit(
        fail={
            ("add_folder", "news"): ConnectionError("обрыв"),
            ("remove_folder", "digest"): ConnectionError("обрыв"),
        },
    )
    repo.fail_on = {"set_group"}
    with pytest.raises(AmbiguousMove) as ei:
        await move_source(store, ops, repo, p.id, p.code, 1, "digest")
    msg = str(ei.value)
    assert "только в новой" in msg and "digest" in msg
    assert "в обеих" not in msg and "ни в одной" not in msg


async def test_move_undo_does_not_readd_where_the_channel_never_was(ingest):
    # снятие вернуло «папки нет / канала там нет»: возвращать в старую нечего
    log, store, p, ops, repo = _kit(
        fail={("remove_folder", "news"): FolderNotFound("news")},
    )
    repo.fail_on = {"set_group"}
    with pytest.raises(RuntimeError):
        await move_source(store, ops, repo, p.id, p.code, 1, "digest")
    assert ("add_folder", 1, "news") not in log
    assert log[-1] == ("remove_folder", 1, "digest")


async def test_move_undo_failure_message_says_old_was_not_restored_on_purpose(ingest):
    log, store, p, ops, repo = _kit(
        fail={
            ("remove_folder", "news"): FolderNotFound("news"),
            ("remove_folder", "digest"): ConnectionError("обрыв"),
        },
    )
    repo.fail_on = {"set_group"}
    with pytest.raises(AmbiguousMove) as ei:
        await move_source(store, ops, repo, p.id, p.code, 1, "digest")
    assert ("add_folder", 1, "news") not in log
    msg = str(ei.value)
    assert "не возвращали" in msg and "только в новой" in msg


async def test_connect_code_is_refused_by_move_and_burned(ingest):
    log, store, p, ops, repo = _kit(action=CONNECT)
    with pytest.raises(BadProposal):
        await move_source(store, ops, repo, p.id, p.code, 1, "digest")
    assert log == [] and repo.rows[1]["group_name"] == "news"
    with pytest.raises(BadProposal):
        await move_source(store, ops, repo, p.id, p.code, 1, "digest")


async def test_connect_code_is_refused_by_leave_and_burned(ingest):
    log, store, p, ops, repo = _kit(action=CONNECT)
    with pytest.raises(BadProposal):
        await leave_source(store, ops, repo, p.id, p.code, 1)
    assert log == [] and repo.rows[1]["state"] == "active"
    with pytest.raises(BadProposal):
        await leave_source(store, ops, repo, p.id, p.code, 1)


async def test_move_code_is_refused_by_leave(ingest):
    log, store, p, ops, repo = _kit(action=MOVE)
    with pytest.raises(BadProposal):
        await leave_source(store, ops, repo, p.id, p.code, 1)
    assert log == []


async def test_move_code_for_another_channel_is_refused_and_burned(ingest):
    log, store, p, ops, repo = _kit(extra=(2,))
    with pytest.raises(BadProposal):
        await move_source(store, ops, repo, p.id, p.code, 2, "digest")
    assert log == [] and repo.rows[2]["group_name"] == "news"
    with pytest.raises(BadProposal):  # код погашен
        await move_source(store, ops, repo, p.id, p.code, 1, "digest")
    assert log == []


async def test_move_unknown_or_left_channel_does_not_burn_the_code(ingest):
    log, store, p, ops, repo = _kit(extra=(2,))
    repo.rows[2]["state"] = "left"
    for other in (99, 2):
        with pytest.raises(LookupError):
            await move_source(store, ops, repo, p.id, p.code, other, "digest")
    assert log == []
    await move_source(store, ops, repo, p.id, p.code, 1, "digest")
    assert repo.rows[1]["group_name"] == "digest"


async def test_move_refuses_unknown_peer(ingest):
    log, store, p, ops, repo = _kit()
    with pytest.raises(LookupError):
        await move_source(store, ops, repo, p.id, p.code, 99, "digest")
    assert log == []


async def test_move_refuses_left_channel(ingest):
    log, store, p, ops, repo = _kit()
    repo.rows[1]["state"] = "left"
    with pytest.raises(LookupError):
        await move_source(store, ops, repo, p.id, p.code, 1, "digest")
    assert log == []


async def test_move_to_the_same_folder_is_a_noop(ingest):
    log, store, p, ops, repo = _kit(group="news")
    await move_source(store, ops, repo, p.id, p.code, 1, "news")
    assert log == []


async def test_move_needs_the_code(ingest):
    log, store, p, ops, repo = _kit()
    with pytest.raises(BadProposal):
        await move_source(store, ops, repo, p.id, "ZZZZZZ", 1, "digest")
    assert log == [] and repo.rows[1]["group_name"] == "news"


async def test_move_replay_is_rejected(ingest):
    log, store, p, ops, repo = _kit()
    await move_source(store, ops, repo, p.id, p.code, 1, "digest")
    log.clear()
    with pytest.raises(BadProposal):
        await move_source(store, ops, repo, p.id, p.code, 1, "analytics")
    assert log == []


# --- leave_source ---

async def test_leave_leaves_marks_left_and_ignores_ingest(ingest):
    log, store, p, ops, repo = _kit(action=LEAVE)
    repo.rows[1]["trust"] = 0.7
    await leave_source(store, ops, repo, p.id, p.code, 1)
    assert log == [("leave", 1), ("mark_left", 1)]
    assert repo.rows[1]["state"] == "left" and repo.rows[1]["trust"] == 0.7
    assert ingest == [] and _only_account_calls(log) == []


async def test_leave_telegram_failure_keeps_the_row_active(ingest):
    log, store, p, ops, repo = _kit(action=LEAVE, fail={"leave": FloodWait(5)})
    with pytest.raises(FloodWait):
        await leave_source(store, ops, repo, p.id, p.code, 1)
    assert log == [("leave", 1)] and repo.rows[1]["state"] == "active"


async def test_leave_refuses_unknown_peer(ingest):
    log, store, p, ops, repo = _kit(action=LEAVE)
    with pytest.raises(LookupError):
        await leave_source(store, ops, repo, p.id, p.code, 99)
    assert log == []


async def test_leave_needs_the_code(ingest):
    log, store, p, ops, repo = _kit(action=LEAVE)
    with pytest.raises(BadProposal):
        await leave_source(store, ops, repo, p.id, "ZZZZZZ", 1)
    assert log == [] and repo.rows[1]["state"] == "active"


async def test_leave_code_for_another_channel_is_refused_and_burned(ingest):
    log, store, p, ops, repo = _kit(action=LEAVE, extra=(2,))
    with pytest.raises(BadProposal):
        await leave_source(store, ops, repo, p.id, p.code, 2)
    assert log == [] and repo.rows[2]["state"] == "active"
    with pytest.raises(BadProposal):
        await leave_source(store, ops, repo, p.id, p.code, 1)
    assert log == []


async def test_leave_unknown_or_left_channel_does_not_burn_the_code(ingest):
    log, store, p, ops, repo = _kit(action=LEAVE, extra=(2,))
    repo.rows[2]["state"] = "left"
    for other in (99, 2):
        with pytest.raises(LookupError):
            await leave_source(store, ops, repo, p.id, p.code, other)
    assert log == []
    await leave_source(store, ops, repo, p.id, p.code, 1)
    assert log == [("leave", 1), ("mark_left", 1)]
    assert repo.rows[1]["state"] == "left"


# --- set_source_trust ---

async def test_set_trust_writes_and_returns_the_row(ingest):
    log = []
    repo = _Repo(log)
    repo.seed(1)
    row = await set_source_trust(repo, 1, 0.9)
    assert repo.rows[1]["trust"] == 0.9 and row.trust == 0.9 and row.peer_id == 1
    assert ingest == []


@pytest.mark.parametrize("bad", [1.5, -0.1, float("nan"), float("inf")])
async def test_set_trust_out_of_range_is_refused(bad):
    log = []
    repo = _Repo(log)
    repo.seed(1, trust=0.4)
    with pytest.raises(ValueError):
        await set_source_trust(repo, 1, bad)
    assert log == [] and repo.rows[1]["trust"] == 0.4


@pytest.mark.parametrize("edge", [0.0, 1.0])
async def test_set_trust_accepts_the_bounds(edge):
    repo = _Repo([])
    repo.seed(1)
    assert (await set_source_trust(repo, 1, edge)).trust == edge


async def test_set_trust_unknown_peer_is_refused():
    log = []
    repo = _Repo(log)
    with pytest.raises(LookupError):
        await set_source_trust(repo, 99, 0.5)
    assert ("set_trust", 99, 0.5) not in log


async def test_set_trust_none_falls_back_to_the_group():
    repo = _Repo([])
    repo.seed(1, trust=0.9)
    row = await set_source_trust(repo, 1, None)
    assert row.trust is None and repo.rows[1]["trust"] is None


@pytest.mark.parametrize("bad", [True, False, "0.5"])
async def test_set_trust_rejects_bool_and_non_numbers(bad):
    log = []
    repo = _Repo(log)
    repo.seed(1, trust=0.4)
    with pytest.raises(ValueError):
        await set_source_trust(repo, 1, bad)
    assert log == [] and repo.rows[1]["trust"] == 0.4


async def test_set_trust_works_on_a_left_channel():
    # доверие действует вперёд, поэтому ставится и вышедшему каналу
    log = []
    repo = _Repo(log)
    repo.seed(1, state="left")
    row = await set_source_trust(repo, 1, 0.3)
    assert log == [("set_trust", 1, 0.3)]
    assert row.trust == 0.3 and row.state == "left"
