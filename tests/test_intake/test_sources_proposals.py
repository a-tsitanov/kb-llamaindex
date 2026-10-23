"""ProposalStore: одноразовое предложение с кодом подтверждения."""

import pytest

from src.intake.sources.proposals import BadProposal, ProposalItem, ProposalStore


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
        code = store.create([_item()]).code
        assert len(code) == 6
        assert not set(code) & set("0OIl1")


def test_take_with_right_code_returns_the_proposal():
    store = ProposalStore()
    p = store.create([_item(1), _item(2, "digest")])
    got = store.take(p.id, p.code)
    assert got.id == p.id and [i.peer_id for i in got.items] == [1, 2]


def test_second_take_is_rejected():
    store = ProposalStore()
    p = store.create([_item()])
    store.take(p.id, p.code)
    with pytest.raises(BadProposal):
        store.take(p.id, p.code)


def test_wrong_code_is_rejected_and_burns_the_proposal():
    store = ProposalStore()
    p = store.create([_item()])
    with pytest.raises(BadProposal):
        store.take(p.id, "ZZZZZZ")
    # перебор кода не должен быть возможен: после промаха предложение мертво
    with pytest.raises(BadProposal):
        store.take(p.id, p.code)


def test_unknown_id_is_rejected():
    with pytest.raises(BadProposal):
        ProposalStore().take("nope", "ABCDEF")


def test_expired_proposal_is_rejected():
    clock = _Clock()
    store = ProposalStore(ttl_s=900, clock=clock)
    p = store.create([_item()])
    clock.now += 901
    with pytest.raises(BadProposal):
        store.take(p.id, p.code)


def test_not_yet_expired_proposal_is_taken():
    clock = _Clock()
    store = ProposalStore(ttl_s=900, clock=clock)
    p = store.create([_item()])
    clock.now += 899
    assert store.take(p.id, p.code).id == p.id


@pytest.mark.parametrize("group", ["", "sport", "News"])
def test_group_outside_group_set_is_refused(group):
    with pytest.raises(ValueError):
        ProposalStore().create([_item(group=group)])


def test_empty_proposal_is_refused():
    with pytest.raises(ValueError):
        ProposalStore().create([])


def test_non_ascii_lookalike_code_is_bad_proposal_not_typeerror():
    store = ProposalStore()
    p = store.create([_item()])
    with pytest.raises(BadProposal):
        store.take(p.id, "АВСDEF")  # кириллические А, В, С
