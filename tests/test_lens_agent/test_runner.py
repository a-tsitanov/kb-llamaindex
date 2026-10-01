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
        assert (await w.store.get_payload(run.id, "c3")).payload["added"] == 2
        assert [r["summary"]["items"] for r in of(evs, "tool_result")][2:] == [2, 1]


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
        ret = tool_returns(seen[-1])[-1]
        assert ret.startswith("call_id=c1\n") and ret.endswith('more(call_id="c1", offset=100)')
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


async def wait_event(w, run_id, type_):
    for _ in range(200):
        if any(e.type == type_ for e in await w.store.list_events(run_id)):
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"no {type_} event")


def agent_tasks():
    """Unfinished pydantic-ai tasks (a background agent loop or a detached tool call)."""
    return [t for t in asyncio.all_tasks() if not t.done() and any(
        n in getattr(t.get_coro(), "__qualname__", "") for n in ("run_agent", "_call_tool"))]


async def test_cancel_stops_the_tool_call_and_nothing_follows_done():
    async with world() as w:
        w.model = scripted([("kb_slow", {})], "не дойдёт")
        run = await w.runner.submit(w.ws.id, "медленно", [])
        await wait_event(w, run.id, "tool_call")
        assert w.runner.cancel(run.id)
        await w.wait(run.id)
        assert agent_tasks() == []
        w.hits["_gate"].set()
        await asyncio.sleep(0.3)
        evs = await w.store.list_events(run.id)
        assert types(evs)[-1] == "done" and of(evs, "done") == [{"status": "cancelled"}]
        assert (await w.store.get_run(run.id)).status == "cancelled"
        (res,) = of(evs, "tool_result")  # the interrupted call is closed in the journal
        assert res["call_id"] == "c1" and res["ok"] is False and res["error"] == "отменено"


async def test_run_timeout_stops_the_tool_call_and_nothing_follows_done():
    async with world(run_timeout_s=0.3) as w:
        run, _ = await w.run(scripted([("kb_slow", {})], "не дойдёт"))
        assert run.status == "failed" and agent_tasks() == []
        w.hits["_gate"].set()
        await asyncio.sleep(0.3)
        evs = await w.store.list_events(run.id)
        assert types(evs)[-1] == "done" and of(evs, "done") == [{"status": "failed"}]


async def test_run_timeout_stops_the_model():
    from pydantic_ai.models.function import FunctionModel

    state = {}

    async def stream(messages, info):
        await asyncio.sleep(0.6)
        state["kept_running"] = True
        yield "поздно"

    async with world(run_timeout_s=0.2) as w:
        run, _ = await w.run(FunctionModel(stream_function=stream))
        assert run.status == "failed"
        await asyncio.sleep(0.8)
        assert state == {} and types(await w.store.list_events(run.id))[-1] == "done"


async def test_double_cancel_still_ends_with_one_done():
    async with world() as w:
        w.model = scripted([("kb_slow", {})], "не дойдёт")
        run = await w.runner.submit(w.ws.id, "медленно", [])
        await wait_event(w, run.id, "tool_call")
        assert w.runner.cancel(run.id)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert w.runner.cancel(run.id)
        await w.wait(run.id)
        evs = await w.store.list_events(run.id)
        assert of(evs, "done") == [{"status": "cancelled"}]
        assert (await w.store.get_run(run.id)).status == "cancelled"


async def test_cancel_then_drain_still_ends_with_one_done():
    async with world() as w:
        w.model = scripted([("kb_slow", {})], "не дойдёт")
        run = await w.runner.submit(w.ws.id, "медленно", [])
        await wait_event(w, run.id, "tool_call")
        assert w.runner.cancel(run.id)
        await asyncio.sleep(0)
        await w.runner.drain()
        evs = await w.store.list_events(run.id)
        assert of(evs, "done") == [{"status": "cancelled"}]
        assert (await w.store.get_run(run.id)).status == "cancelled"


def same_tool_call_id(*turns):
    """Like ``scripted``, but every tool call carries the same provider id (some backends
    restart their ids each turn)."""
    import json

    from pydantic_ai.messages import ModelResponse
    from pydantic_ai.models.function import DeltaToolCall, FunctionModel

    async def stream(messages, info):
        turn = turns[min(sum(isinstance(m, ModelResponse) for m in messages), len(turns) - 1)]
        if isinstance(turn, str):
            yield turn
            return
        yield {j: DeltaToolCall(name=n, json_args=json.dumps(a, ensure_ascii=False),
                                tool_call_id="call_0") for j, (n, a) in enumerate(turn)}

    return FunctionModel(stream_function=stream)


async def test_repeated_provider_tool_call_id_gets_fresh_call_ids():
    async with world() as w:
        run, evs = await w.run(same_tool_call_id(
            [("kb_find_entity", {"name": "Росатом"})], [("kb_big", {})],
            [("board_add_objects", {"objects": objs("c1")[:1]})], "ok"))
        assert run.status == "done"
        assert [(c["call_id"], c["tool"]) for c in of(evs, "tool_call")] == [
            ("c1", "find_entity"), ("c2", "big"), ("c3", "add_objects")]
        assert (await w.store.get_payload(run.id, "c1")).tool == "find_entity"
        assert (await w.store.get_payload(run.id, "c2")).tool == "big"
        src = (await w.board.state(w.ws.id)).objects["kb:e1"].sources[0]
        assert (src.call_id, src.tool) == ("c1", "find_entity")


async def test_identical_calls_in_one_turn_hit_the_source_once():
    async with world() as w:
        seen = []
        run, evs = await w.run(scripted(
            [("kb_find_entity", {"name": "Р"}), ("kb_find_entity", {"name": "Р"})], "ok",
            seen=seen))
        assert run.status == "done" and w.hits["find_entity"] == 1
        rets = tool_returns(seen[-1])
        assert rets[0].startswith("call_id=c1") and rets[1].startswith("(повтор вызова c1")
        assert [r.get("cached_from") for r in of(evs, "tool_result")] == [None, "c1"]


async def test_several_tool_calls_in_one_turn():
    async with world() as w:
        run, evs = await w.run(scripted(
            [("kb_find_entity", {"name": "Р"}), ("kb_big", {}), ("board_get_board", {})],
            [("board_add_objects", {"objects": objs("c1")[:1]})], "ok"))
        assert run.status == "done"
        calls = [(c["call_id"], c["server"], c["tool"]) for c in of(evs, "tool_call")]
        assert calls[:3] == [("c1", "kb", "find_entity"), ("c2", "kb", "big"),
                             ("c3", "board", "get_board")]
        results = of(evs, "tool_result")
        assert sorted(r["call_id"] for r in results) == ["c1", "c2", "c3", "c4"]
        assert all(r["ok"] for r in results)
        src = (await w.board.state(w.ws.id)).objects["kb:e1"].sources[0]
        assert (src.server, src.tool, src.call_id) == ("kb", "find_entity", "c1")


async def test_board_call_id_cannot_be_cited_as_a_source():
    async with world() as w:
        seen = []
        run, _ = await w.run(scripted(
            [("board_get_board", {})],
            [("board_add_objects", {"objects": objs("c1")[:1]})], "ok", seen=seen))
        assert run.status == "done"
        assert "неизвестный call_id 'c1'" in tool_returns(seen[-1])[1]
        assert (await w.board.state(w.ws.id)).objects == {}


async def test_exhausted_tool_retries_fail_the_run_as_a_tool_error():
    async with world() as w:
        run, evs = await w.run(scripted([("kb_boom", {})]))  # the model never gives up
        assert run.status == "failed"
        (err,) = of(evs, "error")
        assert err["where"] == "tool" and "kb_boom" in err["message"]


async def test_failed_deterministic_note_is_reported(monkeypatch):
    from tests.test_lens_agent.helpers import AsgiMCPServer

    real = AsgiMCPServer.direct_call_tool

    async def direct_call_tool(self, name, args, *a, **kw):
        if name == "add_note":
            raise RuntimeError("доска не ответила")
        return await real(self, name, args, *a, **kw)

    monkeypatch.setattr(AsgiMCPServer, "direct_call_tool", direct_call_tool)
    async with world() as w:
        run, evs = await w.run(scripted("ответ"))
        assert run.status == "done" and types(evs)[-3:] == ["final", "error", "done"]
        (err,) = of(evs, "error")
        assert err["where"] == "tool" and err["message"].startswith("заметка не записана: ")
        assert "доска не ответила" in err["message"]


async def test_unchanged_board_read_is_answered_from_cache_with_a_nudge():
    async with world() as w:
        seen = []
        run, evs = await w.run(scripted(
            [("board_get_board", {"include_hidden": True})],
            [("board_get_board", {"limit": 50, "include_hidden": True})],
            [("kb_find_entity", {"name": "Р"})],
            [("board_add_objects", {"objects": objs("c3")[:1]})],
            [("board_get_board", {})],
            "ok", seen=seen))
        assert run.status == "done"
        rets = tool_returns(seen[-1])
        assert "доска не менялась" in rets[1] and "board_add_objects" in rets[1]
        results = of(evs, "tool_result")
        assert results[1]["cached_from"] == "c1"
        # after a write the board is read again for real
        assert "cached_from" not in results[4] and "kb:e1" in rets[4]


async def test_stalled_agent_is_stopped_early():
    async with world(stall_calls=3) as w:
        run, evs = await w.run(scripted(
            [("board_get_board", {})],
            [("board_get_board", {})]))  # repeats forever
        assert run.status == "failed"
        (err,) = of(evs, "error")
        assert err["where"] == "limit" and "зациклился" in err["message"]
        assert len(of(evs, "tool_call")) == 4  # 1 real read + 3 repeats, then stop
        assert run.usage and run.usage["requests"] == 4


async def test_similar_board_objects_are_named_in_the_prompt():
    async with world() as w:
        await w.run(scripted([("kb_find_entity", {"name": "Р"})],
                             [("board_add_objects", {"objects": objs("c1")[:1]})], "ok"))
        seen = []
        await w.run(scripted("ok", seen=seen), text="ростатом")
        prompt = seen[0][0].parts[-1].content
        assert "Похожие объекты на доске" in prompt and "kb:e1 — Росатом" in prompt


async def test_usage_is_kept_when_the_run_fails():
    async with world(run_timeout_s=0.5) as w:
        run, _ = await w.run(scripted([("kb_slow", {})], "не дойдёт"))
        assert run.status == "failed" and run.usage["requests"] == 1


async def test_writes_that_add_nothing_count_as_stalls():
    async with world(stall_calls=3, board_calls=100) as w:
        bad = [("board_add_objects", {"objects": objs("c99")[:1]})]
        run, evs = await w.run(scripted(bad, bad))  # rejected every time, forever
        assert run.status == "failed" and "зациклился" in of(evs, "error")[0]["message"]
        assert len(of(evs, "tool_call")) == 3


async def test_hidden_board_objects_are_found_as_similar():
    async with world() as w:
        await w.run(scripted([("kb_find_entity", {"name": "Р"})],
                             [("board_add_objects", {"objects": objs("c1")[:1]})], "ok"))
        await w.board.hide(w.ws.id, None, ["kb:e1"])
        seen = []
        await w.run(scripted("ok", seen=seen), text="ростатом")
        assert "kb:e1 — Росатом" in seen[0][0].parts[-1].content


async def test_object_id_is_taken_from_the_cited_source_result():
    async with world() as w:
        seen = []
        await w.run(scripted(
            [("kb_find_entity", {"name": "Росатом"})],
            [("board_add_objects", {"objects": [
                {"id": "rosatom", "type": "person", "label": "Росатом", "call_id": "c1"},
                {"id": "invented", "type": "person", "label": "Нет в источнике", "call_id": "c1"},
            ]})],
            "ok", seen=seen))
        st = await w.board.state(w.ws.id)
        # the model invented "rosatom"/person; the row for label «Росатом» gives id E1 and its type
        assert set(st.objects) == {"kb:e1"}
        assert st.objects["kb:e1"].attrs["source_id"] == "E1"
        assert st.objects["kb:e1"].type == "organization"
        # nothing matched in the source: rejected, with the nearest rows to pick from
        ret = tool_returns(seen[-1])[-1]
        assert "Нет в источнике" in ret and "nearest" in ret


async def test_mentioned_object_carries_its_source_id_into_the_prompt():
    async with world() as w:
        await w.run(scripted([("kb_find_entity", {"name": "Р"})],
                             [("board_add_objects", {"objects": [
                                 {"id": "x", "type": "person", "label": "Лихачёв",
                                  "call_id": "c1"}]})], "ok"))
        seen = []
        await w.run(scripted("ok", seen=seen), text="с кем связан?", mentions=["kb:e2"])
        prompt = seen[0][0].parts[-1].content
        assert "kb:e2 — Лихачёв (person), в источнике: E2" in prompt


async def test_relations_accept_object_ids_and_infer_a_missing_call_id():
    async with world() as w:
        await w.run(scripted(
            [("kb_find_entity", {"name": "Росатом"})],
            [("board_add_objects", {"objects": objs("c1")})],
            # ids instead of keys, and no call_id: both ends came from c1
            [("board_add_relations", {"relations": [
                {"from": "E2", "to": "kb:e1", "kind": "работает_в"}]})],
            "ok"))
        st = await w.board.state(w.ws.id)
        (rel,) = st.relations.values()
        assert (rel.from_key, rel.to_key, rel.kind) == ("kb:e2", "kb:e1", "работает_в")
        assert rel.sources[0].call_id == "c1"


async def test_relation_without_any_known_source_is_still_rejected():
    async with world() as w:
        seen = []
        await w.run(scripted(
            [("board_add_relations", {"relations": [
                {"from": "kb:x", "to": "kb:y", "kind": "связан"}]})],
            "ok", seen=seen))
        assert "нет связи" in tool_returns(seen[-1])[0]
        assert (await w.board.state(w.ws.id)).relations == {}


async def test_rows_view_with_coverage_resolution_and_paging():
    async with world(result_chars=1200) as w:
        seen = []
        _, evs = await w.run(scripted(
            [("kb_neighbours", {"entity_name": "Росатом"})],
            [("more", {"call_id": "c1", "offset": 12})],
            [("board_add_objects", {"objects": [{"call_id": "c1", "row": 13}]})],
            "ok", seen=seen))
        first, page = tool_returns(seen[-1])[:2]
        assert "⚠ «Росатом» в базе называется «Rosatom» (совпадение: translit)" in first
        assert "[0] Rosatom (Organization) — госкорпорация" in first
        assert "[1] Сосед 0 (Person)" in first and "| 1.0 strong" in first
        assert "из 61" in first and 'more(call_id="c1", offset=' in first
        assert "Сосед 0 —WORKS_AT→ Rosatom" in first and "[60]" not in first
        assert page.splitlines()[1].startswith("сущности 12–") and "[12] Сосед 11" in page
        assert w.hits["neighbours"] == 1  # paging reads the stored payload
        st = await w.board.state(w.ws.id)
        assert [o.label for o in st.objects.values()] == ["Сосед 12"]
        more_call = [e for e in of(evs, "tool_call") if e["tool"] == "more"]
        assert more_call and more_call[0]["server"] == "lens"


async def test_more_with_an_unknown_call_id_is_an_error():
    async with world() as w:
        seen = []
        await w.run(scripted([("more", {"call_id": "c9"})], "ok", seen=seen))
        assert "нет результата источника" in tool_returns(seen[-1])[0]


async def test_object_under_a_renamed_kb_name_is_redirected_and_the_model_told():
    async with world() as w:
        src = {"server": "kb", "tool": "find_entity", "call_id": "c1", "namespace": "kb"}
        await w.board.add_objects(w.ws.id, "old", [{"id": "Росатом", "label": "Росатом",
                                                     "type": "organization", "source": src}])
        await w.board.pin(w.ws.id, "kb:росатом", 1, 2)
        seen, tools = [], []
        await w.run(scripted([("kb_neighbours", {"entity_name": "Росатом"})], "ok",
                             seen=seen, tools=tools), text="с кем связан?",
                    mentions=["kb:росатом"])
        assert "доска: объект kb:росатом теперь kb:rosatom" in tool_returns(seen[-1])[0]
        st = await w.board.state(w.ws.id)
        assert "kb:rosatom" in st.objects and "kb:росатом" not in st.objects
        assert st.pins["kb:rosatom"] == {"x": 1, "y": 2}
        assert "board_redirect" not in tools[0] and "more" in tools[0]


async def test_no_redirect_when_the_asked_name_is_not_on_the_board():
    async with world() as w:
        seen = []
        await w.run(scripted([("kb_neighbours", {"entity_name": "Росатом"})], "ok",
                             seen=seen))
        assert "доска:" not in tool_returns(seen[-1])[0]
        assert (await w.board.state(w.ws.id)).objects == {}


async def test_request_names_are_resolved_before_the_model_starts():
    async with world() as w:
        seen, tools = [], []
        _, evs = await w.run(scripted("ok", seen=seen, tools=tools),
                             text="Выведи людей, связанных с Росатомом")
        prompt = seen[0][0].parts[-1].content
        assert "Имена из запроса, найденные в источниках" in prompt
        assert "«Росатомом» → «Rosatom» (Organization, kb; совпадение: stem+translit)" in prompt
        assert of(evs, "resolved")[0]["names"][0]["name"] == "Rosatom"
        assert "kb_resolve_names" not in tools[0] and "kb_find_entity" in tools[0]


async def test_a_failing_pre_resolution_does_not_stop_the_run():
    async with world() as w:
        seen = []
        run, _ = await w.run(scripted("ok", seen=seen), text="сломай Росатом")
        assert run.status == "done" and "Имена из запроса" not in seen[0][0].parts[-1].content


async def test_no_data_after_one_attempt_is_sent_back_once():
    async with world() as w:
        seen = []
        run, evs = await w.run(scripted(
            [("kb_find_entity", {"name": "Роснано"})],
            "Нет информации о руководителе.",
            [("kb_neighbours", {"entity_name": "Роснано"})],
            "Нет данных о руководителе.",
            seen=seen), text="кто руководитель роснано?")
        assert run.status == "done"
        retry = [p.content for m in seen[2] for p in getattr(m, "parts", [])
                 if p.part_kind == "retry-prompt"]
        assert retry and "попробуй ещё один способ" in str(retry[0])
        assert of(evs, "final")[0]["answer"] == "Нет данных о руководителе."


async def test_no_data_retry_is_not_repeated_after_the_second_answer():
    async with world() as w:
        run, evs = await w.run(scripted(
            "Ничего не найдено.", "Ничего не найдено, источники пусты."))
        assert run.status == "done"
        assert of(evs, "final")[0]["answer"] == "Ничего не найдено, источники пусты."


async def test_answer_keys_must_be_on_the_board():
    async with world() as w:
        seen = []
        _, evs = await w.run(scripted(
            [("kb_find_entity", {"name": "Росатом"})],
            [("board_add_objects", {"objects": objs("c1")[:1]})],
            "Это [[kb:e1]] и [[kb:выдумка]].",
            "Это [[kb:e1]].",
            seen=seen))
        retry = [str(p.content) for m in seen[3] for p in getattr(m, "parts", [])
                 if p.part_kind == "retry-prompt"]
        assert retry and "[[kb:выдумка]]" in retry[0] and "[[kb:e1]]" not in retry[0]
        assert of(evs, "final")[0]["answer"] == "Это [[kb:e1]]."


async def test_a_label_in_brackets_is_sent_back_with_its_key():
    async with world() as w:
        seen = []
        _, evs = await w.run(scripted(
            [("kb_find_entity", {"name": "Росатом"})],
            [("board_add_objects", {"objects": objs("c1")[:1]})],
            "Это [[E1]].",
            "Это [[kb:e1]].",
            seen=seen))
        retry = [str(p.content) for m in seen[3] for p in getattr(m, "parts", [])
                 if p.part_kind == "retry-prompt"]
        assert retry and "[[E1]] → [[kb:e1]]" in retry[0]
        assert of(evs, "final")[0]["answer"] == "Это [[kb:e1]]."


async def test_a_board_key_passed_to_a_source_becomes_its_source_name():
    async with world() as w:
        src = {"server": "kb", "tool": "find_entity", "call_id": "c1", "namespace": "kb"}
        await w.board.add_objects(w.ws.id, "old", [{
            "id": "Сентябрьская встреча", "label": "Сентябрьская встреча", "type": "event",
            "attrs": {"source_id": "Сентябрьская встреча"}, "source": src}])
        seen = []
        await w.run(scripted([("kb_neighbours", {"entity_name": "kb:сентябрьская встреча"})],
                             "ok", seen=seen))
        # the fake source echoes what it was asked in its resolution block
        assert "«Сентябрьская встреча» в базе называется «Rosatom»" in tool_returns(seen[-1])[0]


async def test_a_broken_reference_format_is_sent_back_once():
    async with world() as w:
        seen = []
        _, evs = await w.run(scripted("Нашёл [[0] Визит в США (EventOrAction)].",
                                      "Нашёл визит в США.", seen=seen))
        retry = [str(p.content) for m in seen[1] for p in getattr(m, "parts", [])
                 if p.part_kind == "retry-prompt"]
        assert retry and "[[0]" in retry[0]
        assert of(evs, "final")[0]["answer"] == "Нашёл визит в США."
