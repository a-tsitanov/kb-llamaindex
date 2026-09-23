import asyncio

from src.lens.agent import Agent, resolve_citations, same_as_candidates
from src.lens.events import EventBus
from src.lens.llm import ChatReply, ToolCallReq
from src.lens.mcp_hub import ToolInfo, ToolResult
from src.lens.model import ObjectEl
from src.lens.normalizer import Normalizer
from src.lens.planner import Planner, PlannerFinal
from src.lens.state import fold
from src.lens.store import MemoryLensStore
from tests.test_lens.fakes import FakeLLM

INFO = ToolInfo(
    server="kb-tools",
    name="find",
    description="Find",
    input_schema={"type": "object", "properties": {}},
    namespace="kb",
)
SPEC = {
    "objects": [
        {
            "name": "org",
            "each": "$.results[*]",
            "id": "$.qid",
            "label": "$.name",
            "type": "organization",
        }
    ]
}


class FakeHub:
    def __init__(self, results):
        self.results = list(results)

    async def refresh(self):
        return None

    def catalog(self):
        return [INFO]

    def find(self, q):
        return INFO if q == INFO.qualified else None

    async def call(self, server, tool, args):
        return self.results.pop(0)


def build(chat, json_replies, results):
    store, bus = MemoryLensStore(), EventBus()
    llm = FakeLLM(chat_replies=chat, json_replies=json_replies)
    hub = FakeHub(results)
    planner = Planner(
        llm, hub, store, model="m", max_steps=4, sample_chars=2000
    )
    normalizer = Normalizer(
        llm,
        store,
        model="m",
        vocabulary=["organization"],
        aggregate_threshold=25,
        sample_chars=2000,
    )
    return (
        Agent(store=store, bus=bus, planner=planner, normalizer=normalizer),
        store,
        bus,
    )


def call_reply():
    return ChatReply(
        text=None,
        tool_calls=[
            ToolCallReq(id="t1", name="kb-tools__find", arguments={})
        ],
    )


def drain_queue(q):
    return [q.get_nowait() for _ in range(q.qsize())]


async def test_search_input_produces_objects_cited_note_and_events():
    agent, store, bus = build(
        [
            call_reply(),
            ChatReply(text="Нашёл Росатом [[kb:Q1]] и ещё [[kb:FAKE]]."),
        ],
        [SPEC],
        [ToolResult(payload={"results": [{"qid": "Q1", "name": "Росатом"}]})],
    )
    ws = await store.create_workspace("t")
    q = bus.subscribe(ws.id)
    iid = await agent.submit(ws.id, "Росатом", [])
    await agent.drain()
    st = fold(await store.list_ops(ws.id))
    assert list(st.objects) == ["kb:Q1"]
    note = st.notes[0]
    assert note.text == "Нашёл Росатом [[kb:Q1]] и ещё."
    assert note.cites == ["kb:Q1"] and len(note.calls) == 1
    events = drain_queue(q)
    assert {"status", "ops"} <= {e["type"] for e in events}
    assert events[-1] == {"type": "input_done", "input_id": iid, "status": "done"}
    assert (await store.get_input(iid))["status"] == "done"


async def test_tool_error_becomes_raw_view():
    agent, store, _ = build(
        [call_reply(), ChatReply(text="Источник недоступен.")],
        [SPEC],
        [ToolResult(payload=None, is_error=True, error="kaput")],
    )
    ws = await store.create_workspace("t")
    await agent.submit(ws.id, "Росатом", [])
    await agent.drain()
    st = fold(await store.list_ops(ws.id))
    (raw,) = [v for v in st.views.values() if v["kind"] == "raw"]
    assert "kaput" in raw["reason"]


async def test_command_input_skips_planner_and_replies():
    agent, store, bus = build([], [], [])
    ws = await store.create_workspace("t")
    q = bus.subscribe(ws.id)
    await agent.submit(ws.id, "отмени", [])
    await agent.drain()
    ev = q.get_nowait()
    assert ev["type"] == "reply" and ev["text"] == "Нечего отменять."


async def test_planner_crash_marks_input_failed():
    agent, store, bus = build([], [], [])

    async def boom(**kw):
        raise RuntimeError("llm down")
        yield  # pragma: no cover

    agent.planner.run = boom
    ws = await store.create_workspace("t")
    q = bus.subscribe(ws.id)
    iid = await agent.submit(ws.id, "Росатом", [])
    await agent.drain()
    assert (await store.get_input(iid))["status"] == "failed"
    assert drain_queue(q)[-1]["status"] == "failed"


def _blocking_planner(agent, started: asyncio.Event):
    async def slow(**kw):
        started.set()
        await asyncio.Event().wait()  # never finishes on its own
        yield PlannerFinal("never")  # pragma: no cover

    agent.planner.run = slow


async def test_pin_does_not_wait_for_running_search():
    agent, store, _ = build([], [], [])
    started = asyncio.Event()
    _blocking_planner(agent, started)
    ws = await store.create_workspace("t")
    await agent.submit(ws.id, "долгий поиск", [])
    await started.wait()
    (op,) = await asyncio.wait_for(
        agent.pin(ws.id, "kb:1", 10.0, 20.0), timeout=1
    )
    assert op.kind == "pin" and op.input_id is None
    await agent.submit(ws.id, "стоп", [])
    await agent.drain()


async def test_stop_cancels_running_input():
    agent, store, bus = build([], [], [])
    started = asyncio.Event()
    _blocking_planner(agent, started)
    ws = await store.create_workspace("t")
    q = bus.subscribe(ws.id)
    iid = await agent.submit(ws.id, "долгий поиск", [])
    await started.wait()
    await agent.submit(ws.id, "стоп", [])
    await agent.drain()
    assert (await store.get_input(iid))["status"] == "cancelled"
    texts = [
        e.get("text") for e in drain_queue(q) if e["type"] == "reply"
    ]
    assert (
        "Останавливаю текущий запрос." in texts
        and "Остановлено." in texts
    )


async def test_open_workspace_or_fall_back_to_search():
    agent, store, bus = build(
        [ChatReply(text="ничего")], [], []
    )
    ws = await store.create_workspace("Росатом/Китай")
    q = bus.subscribe(ws.id)
    await agent.submit(ws.id, "открой росатом", [])
    await agent.drain()
    (ev,) = [
        e for e in drain_queue(q) if e["type"] == "open_workspace"
    ]
    assert ev["workspace_id"] == ws.id
    await agent.submit(ws.id, "открой данные по Тяньвань", [])
    await agent.drain()
    assert (
        agent.planner.llm.chat_calls
    ), "unknown workspace must go to the planner"


def test_same_as_candidates_cross_namespace_only():
    existing = {
        "fofa:x": ObjectEl(
            key="fofa:x", type="organization", label="РОСАТОМ"
        ),
        "kb:Q7": ObjectEl(
            key="kb:Q7", type="organization", label="Росатом"
        ),
    }
    new = [
        ObjectEl(key="kb:Q1", type="organization", label="«Росатом»")
    ]
    rels = same_as_candidates(new, existing)
    assert [(r.from_key, r.to_key, r.kind) for r in rels] == [
        ("kb:Q1", "fofa:x", "same_as?")
    ]


def test_resolve_citations():
    text, cites = resolve_citations(
        "A [[kb:1]], B [[x:2]] и A [[kb:1]]", {"kb:1"}
    )
    assert text == "A [[kb:1]], B и A [[kb:1]]" and cites == ["kb:1"]
