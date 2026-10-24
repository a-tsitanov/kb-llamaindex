"""ProposalStore: одноразовое предложение с кодом подтверждения."""

import pytest

from src.intake.sources.proposals import (
    CONNECT,
    LEAVE,
    MOVE,
    BadProposal,
    ProposalItem,
    ProposalStore,
    SourceInputError,
)


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _item(peer_id=1, group="news"):
    return ProposalItem(peer_id=peer_id, slug="chan", title="Chan", group_name=group)


def test_code_is_six_unambiguous_chars():
    store = ProposalStore()
    for _ in range(50):
        code = store.create([_item()], CONNECT).code
        assert len(code) == 6
        assert not set(code) & set("0OIl1")


def test_take_with_right_code_returns_the_proposal():
    store = ProposalStore()
    p = store.create([_item(1), _item(2, "digest")], CONNECT)
    got = store.take(p.id, p.code, CONNECT)
    assert got.id == p.id and [i.peer_id for i in got.items] == [1, 2]


def test_second_take_is_rejected():
    store = ProposalStore()
    p = store.create([_item()], CONNECT)
    store.take(p.id, p.code, CONNECT)
    with pytest.raises(BadProposal):
        store.take(p.id, p.code, CONNECT)


def test_wrong_code_is_rejected_and_burns_the_proposal():
    store = ProposalStore()
    p = store.create([_item()], CONNECT)
    with pytest.raises(BadProposal):
        store.take(p.id, "ZZZZZZ", CONNECT)
    # перебор кода не должен быть возможен: после промаха предложение мертво
    with pytest.raises(BadProposal):
        store.take(p.id, p.code, CONNECT)


def test_unknown_id_is_rejected():
    with pytest.raises(BadProposal):
        ProposalStore().take("nope", "ABCDEF", CONNECT)


def test_expired_proposal_is_rejected():
    clock = _Clock()
    store = ProposalStore(ttl_s=900, clock=clock)
    p = store.create([_item()], CONNECT)
    clock.now += 901
    with pytest.raises(BadProposal):
        store.take(p.id, p.code, CONNECT)


def test_not_yet_expired_proposal_is_taken():
    clock = _Clock()
    store = ProposalStore(ttl_s=900, clock=clock)
    p = store.create([_item()], CONNECT)
    clock.now += 899
    assert store.take(p.id, p.code, CONNECT).id == p.id


@pytest.mark.parametrize("group", ["", "sport", "News"])
def test_group_outside_group_set_is_refused(group):
    with pytest.raises(ValueError):
        ProposalStore().create([_item(group=group)], CONNECT)


def test_empty_proposal_is_refused():
    with pytest.raises(ValueError):
        ProposalStore().create([], CONNECT)


def test_non_ascii_lookalike_code_is_bad_proposal_not_typeerror():
    store = ProposalStore()
    p = store.create([_item()], CONNECT)
    with pytest.raises(BadProposal):
        store.take(p.id, "АВСDEF", CONNECT)  # кириллические А, В, С


def test_proposal_remembers_its_action():
    p = ProposalStore().create([_item()], MOVE)
    assert p.action == MOVE


def test_action_literals_are_the_agreed_ones():
    assert (CONNECT, MOVE, LEAVE) == ("connect", "move", "leave")


@pytest.mark.parametrize("action", ["", "join", "Connect", "delete"])
def test_unknown_action_is_refused_on_create(action):
    with pytest.raises(ValueError):
        ProposalStore().create([_item()], action)


def test_mismatched_action_is_rejected_and_burns_the_proposal():
    store = ProposalStore()
    p = store.create([_item()], CONNECT)
    with pytest.raises(BadProposal, match="действ"):
        store.take(p.id, p.code, LEAVE)
    # код, нацеленный на чужое действие, — злоупотребление: предложение погашено
    with pytest.raises(BadProposal):
        store.take(p.id, p.code, CONNECT)


def test_leave_does_not_validate_the_group():
    store = ProposalStore()
    assert store.create([ProposalItem(1, "@a", "A", "drifted")], LEAVE).action == LEAVE


def test_connect_and_move_still_validate_the_group():
    store = ProposalStore()
    for action in (CONNECT, MOVE):
        with pytest.raises(SourceInputError):
            store.create([ProposalItem(1, "@a", "A", "drifted")], action)
