import asyncio

import pytest

from src.lens.board import BoardError, BoardLimits, BoardService
from src.lens.events import EventBus
from src.lens.store import MemoryLensStore


def src(call="c1"):
    return {"server": "kb-tools", "tool": "find_entity_by_name", "call_id": call,
            "namespace": "kb"}


def obj(oid, label=None, type_="organization", **kw):
    return {"id": oid, "label": label or oid, "type": type_, "source": src(), **kw}


class YieldingStore(MemoryLensStore):
    """Test store that yields control to force genuine asyncio interleaving."""
    async def list_ops(self, *a, **kw):
        await asyncio.sleep(0)
        return await super().list_ops(*a, **kw)

    async def append_ops(self, *a, **kw):
        await asyncio.sleep(0)
        return await super().append_ops(*a, **kw)


@pytest.fixture
async def board():
    store, bus = MemoryLensStore(), EventBus()
    b = BoardService(store, bus, BoardLimits(objects_per_call=3, objects_per_run=4))
    ws = await store.create_workspace("t")
    return b, ws.id, bus


async def test_add_objects_normalizes_keys_and_injects_run(board):
    b, ws, _ = board
    r = await b.add_objects(ws, "r1", [obj(" Росатом "), obj("РОСАТОМ")])
    assert r["keys"] == ["kb:росатом", "kb:росатом"] and r["added"] == 1
    o = await b.get_object(ws, "kb:росатом")
    assert o["sources"][0]["run_id"] == "r1" and o["type"] == "organization"


async def test_near_duplicate_by_label_reports_merged_into(board):
    b, ws, _ = board
    await b.add_objects(ws, "r1", [obj("ent_7", label="Росатом")])
    r = await b.add_objects(ws, "r2", [obj("Rosatom-id", label="  РОСАТОМ ")])
    assert r["added"] == 0 and r["merged"] == [{"id": "Rosatom-id", "merged_into": "kb:ent_7"}]


async def test_rejects_without_source_or_id(board):
    b, ws, _ = board
    r = await b.add_objects(ws, "r1", [{"id": "X", "label": "X"}, obj("", label="Y")])
    assert r["added"] == 0 and [x["reason"][:5] for x in r["rejected"]] == ["нет и", "нужны"]


async def test_unknown_type_becomes_other(board):
    b, ws, _ = board
    await b.add_objects(ws, "r1", [obj("X", type_="spaceship")])
    assert (await b.get_object(ws, "kb:x"))["type"] == "other"


async def test_add_objects_strips_reserved_attrs(board):
    b, ws, _ = board
    await b.add_objects(ws, "r1", [
        obj("A", attrs={"types_seen": "x", "kind_original": "y", "ok": 1})])
    o = await b.get_object(ws, "kb:a")
    assert o["attrs"] == {"ok": 1}


async def test_source_run_id_cannot_be_forged(board):
    b, ws, _ = board
    forged = {**src(), "run_id": "OTHER"}
    await b.add_objects(ws, "r1", [
        {"id": "A", "label": "A", "type": "organization", "source": forged},
        {"id": "B", "label": "B", "type": "organization", "source": src()}])
    o = await b.get_object(ws, "kb:a")
    assert o["sources"][0]["run_id"] == "r1"
    r = await b.add_relations(ws, "r1", [
        {"from": "kb:a", "to": "kb:b", "kind": "связан", "source": forged}])
    assert r["added"] == 1
    st = await b.state(ws)
    (rel,) = st.relations.values()
    assert rel.sources[0].run_id == "r1"


async def test_limits_per_call_and_per_run(board):
    b, ws, _ = board
    with pytest.raises(BoardError, match="за вызов"):
        await b.add_objects(ws, "r1", [obj(f"o{i}") for i in range(4)])
    await b.add_objects(ws, "r1", [obj("a"), obj("b"), obj("c")])
    with pytest.raises(BoardError, match="за запуск"):
        await b.add_objects(ws, "r1", [obj("d"), obj("e")])
    assert (await b.add_objects(ws, "r2", [obj("d")]))["added"] == 1


async def test_relations_need_both_ends_and_map_kind(board):
    b, ws, _ = board
    await b.add_objects(ws, "r1", [obj("A"), obj("B")])
    r = await b.add_relations(ws, "r1", [
        {"from": "kb:a", "to": "kb:b", "kind": "REGULATION", "source": src()},
        {"from": "kb:a", "to": "kb:zzz", "kind": "связан", "source": src()},
        {"from": "kb:a", "to": "kb:a", "kind": "связан", "source": src()},
        {"from": "kb:a", "to": "kb:b", "kind": "связан"},
    ])
    assert r["added"] == 1 and len(r["rejected"]) == 3
    st = await b.state(ws)
    (rel,) = st.relations.values()
    assert rel.kind == "related" and rel.attrs == {"kind_original": "REGULATION"}


async def test_note_canonicalizes_citations(board):
    b, ws, _ = board
    await b.add_objects(ws, "r1", [obj("A", label="Росатом"), obj("B", label="Квантовый проект")])
    await b.merge(ws, "r1", "kb:a", "kb:b")
    r = await b.add_note(ws, "r2", "См. [[kb:b]], [[Росатом]] и [[kb:несуществующий]].")
    st = await b.state(ws)
    assert st.notes[-1].text == "См. [[kb:a]], [[kb:a]] и несуществующий."
    assert r["cites"] == ["kb:a"]
    await b.add_note(ws, "r2", "замена")
    assert [n.text for n in (await b.state(ws)).notes] == ["замена"]


async def test_note_citations_skip_hidden_objects(board):
    b, ws, _ = board
    await b.add_objects(ws, "r1", [obj("A", label="Rosatom")])
    await b.hide(ws, "r1", ["kb:a"])
    r = await b.add_note(ws, "r2", "см. [[kb:a]] и [[Rosatom]].")
    assert r["cites"] == []
    st = await b.state(ws)
    assert st.notes[-1].text == "см. a и Rosatom."


async def test_undo_reverts_previous_run_not_current(board):
    b, ws, _ = board
    await b.add_objects(ws, "r1", [obj("A")])
    await b.add_objects(ws, "r2", [obj("B")])
    r = await b.undo(ws, "r3")
    assert r["reverted_run"] == "r2" and r["operations"] == 1
    assert set((await b.state(ws)).objects) == {"kb:a"}
    assert (await b.add_note(ws, "r3", "x")) == {"skipped": "в этом запуске была отмена — заметка не нужна"}
    assert (await b.undo(ws, "r4"))["reverted_run"] == "r1"
    assert (await b.undo(ws, "r5"))["message"] == "нечего отменять"


async def test_get_board_orders_by_touch_and_keeps_pinned_and_run(board):
    b, ws, _ = board
    await b.add_objects(ws, "r1", [obj("old"), obj("pinned")])
    await b.pin(ws, "kb:pinned", 1, 2)
    await b.add_objects(ws, "r2", [obj("new")])
    await b.add_objects(ws, "r3", [obj("mine")])
    await b.add_relations(ws, "r3", [{"from": "kb:mine", "to": "kb:old", "kind": "связан",
                                      "source": src()}])
    g = await b.get_board(ws, "r3", limit=2)
    keys = [o["key"] for o in g["objects"]]
    assert set(keys) == {"kb:pinned", "kb:mine"} and g["total"] == 4
    assert g["relations"] == []
    g = await b.get_board(ws, "r3", limit=4)
    assert g["relations"] == [{"from": "kb:mine", "to": "kb:old", "kind": "связан"}]


async def test_hide_show_find_and_merge_errors(board):
    b, ws, _ = board
    await b.add_objects(ws, "r1", [obj("A", label="Си Цзиньпин"), obj("B", label="Россия")])
    assert await b.find_on_board(ws, "Си") == [{"key": "kb:a", "label": "Си Цзиньпин"}]
    assert (await b.hide(ws, "r2", ["kb:a", "kb:nope"])) == {"changed": 1}
    assert await b.find_on_board(ws, "Си") == []
    assert (await b.show(ws, "r3", ["kb:a"])) == {"changed": 1}
    with pytest.raises(BoardError):
        await b.merge(ws, "r4", "kb:a", "kb:nope")


async def test_writes_publish_board_events(board):
    b, ws, bus = board
    q = bus.subscribe(ws)
    await b.add_objects(ws, "r1", [obj("A")])
    op = await b.pin(ws, "kb:a", 5, 6)
    events = [q.get_nowait() for _ in range(q.qsize())]
    assert [e["ops"][0]["kind"] for e in events] == ["add_objects", "pin"]
    assert op.input_id is None


async def test_parallel_calls_in_one_workspace_do_not_duplicate():
    # Use YieldingStore to force genuine asyncio interleaving
    store, bus = YieldingStore(), EventBus()
    b = BoardService(store, bus, BoardLimits(objects_per_call=3, objects_per_run=4))
    ws = await store.create_workspace("t")
    r1, r2 = await asyncio.gather(
        b.add_objects(ws.id, "r1", [obj("id-1", label="Росатом")]),
        b.add_objects(ws.id, "r1", [obj("id-2", label="РОСАТОМ")]))
    assert r1["added"] + r2["added"] == 1
    assert len((await b.state(ws.id)).objects) == 1


async def test_near_duplicate_with_type_other_matches_any_type(board):
    b, ws, _ = board
    await b.add_objects(ws, "r1", [obj("likhachev", label="Алексей Лихачёв", type_="person")])
    r = await b.add_objects(ws, "r2", [obj("Алексей Лихачёв", label="Алексей Лихачёв",
                                           type_="other")])
    assert r["merged"] == [{"id": "Алексей Лихачёв", "merged_into": "kb:likhachev"}]
    await b.add_objects(ws, "r3", [obj("tass", label="ТАСС", type_="other")])
    r = await b.add_objects(ws, "r4", [obj("tass-org", label="ТАСС", type_="organization")])
    assert r["merged"] == [{"id": "tass-org", "merged_into": "kb:tass"}]
    st = await b.state(ws)
    assert st.objects["kb:tass"].type == "organization"  # "other" is refined, not kept
    assert st.objects["kb:likhachev"].type == "person"
    assert "types_seen" not in st.objects["kb:likhachev"].attrs
    # two specific different types are still different entities
    r = await b.add_objects(ws, "r5", [obj("likh-place", label="Алексей Лихачёв",
                                           type_="location")])
    assert r["added"] == 1
