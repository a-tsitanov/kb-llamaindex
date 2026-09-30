"""The hook moves a board object only on an exact-level rename by the source."""
import pytest

from src.lens_agent.calls import RunCalls


def res(via, query="Росатом", name="Rosatom", status="ok"):
    return {"resolution": {"query": query, "status": status,
                           "chosen": {"name": name, "matched_via": via}}}


@pytest.mark.parametrize(("payload", "called"), [
    (res(["translit"]), True),
    (res(["legal_form+translit"], query="ГК «Росатом»"), True),
    (res(["casefold"], query="РОСАТОМ", name="Росатом"), False),  # same key: nothing to move
    (res(["word", "trigram"], query="Лихачев", name="Алексей Лихачёв"), False),  # a guess
    (res(["translit"], status="ambiguous"), False),
    ({"entities": []}, False),
])
async def test_redirect_only_on_exact_level_renames(payload, called):
    seen = []

    async def board(name, args):
        seen.append((name, args))
        return {"redirected": True, "from": args["from_key"], "key": args["to_key"]}
    rc = RunCalls("r", store=None, emitter=None)
    rc.board_direct = board
    note = await rc._redirect("kb", payload)
    assert bool(seen) is called and bool(note) is called
    if called:
        assert seen[0][1]["to_key"] == "kb:rosatom" and seen[0][1]["to_id"] == "Rosatom"
