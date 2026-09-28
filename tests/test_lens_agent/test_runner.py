import asyncio

from pydantic_ai.exceptions import ModelHTTPError

from src.lens_agent.config import McpEntry
from tests.test_lens_agent.helpers import BOARD_TOKEN, scripted, tool_returns, world


def objs(call_id="c2"):
    return [{"id": "E1", "type": "organization", "label": "Росатом", "call_id": call_id},
            {"id": "E2", "type": "person", "label": "Лихачёв", "call_id": call_id}]


def types(events):
    return [e.type for e in events]


def of(events, type_):
    return [e.data for e in events if e.type == type_]


async def test_happy_path_sources_injected_and_note_written():
    async with world() as w:
        run, evs = await w.run(scripted(
            [("board_get_board", {})],
            [("kb_find_entity", {"name": "Росатом"})],
            [("board_add_objects", {"objects": objs()})],
            [("board_add_relations", {"relations": [
                {"from": "kb:e2", "to": "kb:e1", "kind": "работает_в", "call_id": "c2"}]})],
            "Росатом возглавляет [[kb:e2]]."))
        assert run.status == "done" and run.usage["requests"] == 5
        assert types(evs)[0] == "run_started" and types(evs)[-2:] == ["final", "done"]
        assert of(evs, "run_started")[0]["mcp"] == [{"name": "kb", "status": "up"},
                                                    {"name": "board", "status": "up"}]
        calls = of(evs, "tool_call")
        assert [(c["call_id"], c["server"], c["tool"]) for c in calls] == [
            ("c1", "board", "get_board"), ("c2", "kb", "find_entity"),
            ("c3", "board", "add_objects"), ("c4", "board", "add_relations")]
        assert all(r["ok"] for r in of(evs, "tool_result"))
        assert "".join(d["delta"] for d in of(evs, "text")) == "Росатом возглавляет [[kb:e2]]."
        st = await w.board.state(w.ws.id)
        assert st.objects["kb:e1"].sources[0].model_dump() == {
            "server": "kb", "tool": "find_entity", "call_id": "c2", "run_id": run.id,
            "namespace": "kb"}
        assert len(st.relations) == 1
        assert [n.cites for n in st.notes] == [["kb:e2"]]
        assert (await w.store.get_payload(run.id, "c2")).payload["entities"][0]["id"] == "E1"


async def test_unknown_call_id_is_rejected_back_to_the_model():
    async with world() as w:
        seen = []
        run, _ = await w.run(scripted(
            [("board_add_objects", {"objects": [objs("c99")[0]]})],
            "нет данных", seen=seen))
        assert run.status == "done"
        assert "неизвестный call_id 'c99'" in tool_returns(seen[-1])[0]
        assert (await w.board.state(w.ws.id)).objects == {}


async def test_result_truncated_for_model_but_stored_in_full():
    async with world(result_chars=100) as w:
        seen = []
        run, evs = await w.run(scripted([("kb_big", {})], "ok", seen=seen))
        ret = tool_returns(seen[-1])[0]
        assert ret.startswith("call_id=c1\n") and ret.endswith("полный результат: call_id=c1")
        assert len(ret) < 200 and of(evs, "tool_result")[0]["truncated"] is True
        assert len((await w.store.get_payload(run.id, "c1")).payload) == 10_000


async def test_identical_call_served_from_cache_and_budget_is_soft():
    async with world(source_calls=1) as w:
        seen = []
        run, evs = await w.run(scripted(
            [("kb_find_entity", {"name": "Росатом"})],
            [("kb_find_entity", {"name": "Росатом"})],
            [("kb_big", {})],
            "итог", seen=seen))
        assert run.status == "done" and w.hits["find_entity"] == 1 and "big" not in w.hits
        rets = tool_returns(seen[-1])
        assert rets[1].startswith("(повтор вызова c1")
        assert rets[2].startswith("лимит вызовов источников исчерпан")
        results = of(evs, "tool_result")
        assert results[1]["cached_from"] == "c1" and results[2]["ok"] is False


async def test_tool_error_goes_back_to_model_and_shows_red():
    async with world() as w:
        seen = []
        run, evs = await w.run(scripted([("kb_boom", {})], "не вышло", seen=seen))
        assert run.status == "done"
        (res,) = of(evs, "tool_result")
        assert res["ok"] is False and "источник упал" in res["error"]


async def test_hard_request_limit_fails_the_run_and_keeps_the_board():
    async with world(request_limit=3) as w:
        run, evs = await w.run(scripted(
            [("kb_find_entity", {"name": "Росатом"})],
            [("board_add_objects", {"objects": objs("c1")[:1]})],
            [("board_get_board", {})]))
        assert run.status == "failed"
        assert of(evs, "error")[0]["where"] == "limit" and of(evs, "done") == [
            {"status": "failed"}]
        assert list((await w.board.state(w.ws.id)).objects) == ["kb:e1"]


async def test_model_error_fails_the_run():
    async with world() as w:
        run, evs = await w.run(scripted(ModelHTTPError(502, "large", "bad gateway")))
        assert run.status == "failed" and of(evs, "error")[0]["where"] == "model"


async def test_cancel_during_a_tool_call():
    async with world() as w:
        w.model = scripted([("kb_slow", {})], "не дойдёт")
        run = await w.runner.submit(w.ws.id, "медленно", [])
        for _ in range(100):
            if any(e.type == "tool_call" for e in await w.store.list_events(run.id)):
                break
            await asyncio.sleep(0.02)
        assert w.runner.cancel(run.id)
        await w.wait(run.id)
        evs = await w.store.list_events(run.id)
        assert of(evs, "done") == [{"status": "cancelled"}]
        assert (await w.store.get_run(run.id)).status == "cancelled"


async def test_down_source_is_reported_and_run_continues():
    mcp = [McpEntry(name="kb", url="http://kb/mcp", namespace="kb"),
           McpEntry(name="dead", url="http://dead/mcp"),
           McpEntry(name="board", url="http://lens/mcp/mcp", token=BOARD_TOKEN, role="board")]
    async with world(mcp=mcp) as w:
        run, evs = await w.run(scripted("ок"))
        assert run.status == "done"
        st = {m["name"]: m["status"] for m in of(evs, "run_started")[0]["mcp"]}
        assert st == {"kb": "up", "dead": "down", "board": "up"}


async def test_no_note_after_undo_and_model_note_not_duplicated():
    async with world() as w:
        await w.run(scripted([("kb_find_entity", {"name": "Р"})],
                             [("board_add_objects", {"objects": objs("c1")[:1]})], "первый"))
        assert list((await w.board.state(w.ws.id)).objects) == ["kb:e1"]
        run, _ = await w.run(scripted([("board_undo", {})], "отменил"))
        st = await w.board.state(w.ws.id)
        assert st.objects == {} and all(not n.key.endswith(run.id) for n in st.notes)
        await w.run(scripted([("board_add_note", {"text": "своя заметка"})], "ответ"))
        texts = [n.text for n in (await w.board.state(w.ws.id)).notes]
        assert texts.count("своя заметка") == 1 and "ответ" not in texts


async def test_mentions_resolved_into_the_prompt():
    async with world() as w:
        await w.run(scripted([("kb_find_entity", {"name": "Р"})],
                             [("board_add_objects", {"objects": objs("c1")[:1]})], "ok"))
        seen = []
        await w.run(scripted("ok", seen=seen), text="кто это?", mentions=["kb:e1"])
        prompt = seen[0][0].parts[-1].content
        assert "кто это?" in prompt and "kb:e1 — Росатом (organization)" in prompt


async def test_missing_board_fails_run():
    async with world(mcp=[McpEntry(name="kb", url="http://kb/mcp")]) as w:
        run, evs = await w.run(scripted("ok"))
        assert run.status == "failed" and "доска недоступна" in of(evs, "error")[0]["message"]


async def test_run_timeout_is_a_hard_limit():
    async with world(run_timeout_s=0.3) as w:
        run, evs = await w.run(scripted([("kb_slow", {})], "не дойдёт"))
        assert run.status == "failed"
        assert of(evs, "error")[0]["where"] == "limit" and "время запуска" in of(
            evs, "error")[0]["message"]


async def test_unknown_tool_is_journaled_and_model_retries():
    async with world() as w:
        run, evs = await w.run(scripted([("kb_no_such_tool", {})], "ладно"))
        assert run.status == "done" and of(evs, "error")[0]["where"] == "tool"