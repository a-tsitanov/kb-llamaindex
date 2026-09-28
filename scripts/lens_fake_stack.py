"""Dev-only fake Lens stack: board (memory) + lens-agent (scripted model, no LLM) + fake KB.

For web work without the real stack:
    uv run python scripts/lens_fake_stack.py      # :18010 board, :18011 kb, :18020 agent
    cd web && LENS_BOARD_URL=http://127.0.0.1:18010 LENS_AGENT_URL=http://127.0.0.1:18020 npm run dev
API key in the page settings: dev.  Every request replays the same scripted run.
"""
import asyncio

import uvicorn
from pydantic import SecretStr

from src.lens.app import LensDeps
from src.lens.app import create_app as lens_app
from src.lens.config import lens_settings
from src.lens.events import EventBus
from src.lens.store import MemoryLensStore
from src.lens_agent.app import AgentDeps
from src.lens_agent.app import create_app as agent_app
from src.lens_agent.config import AgentSettings, McpEntry
from src.lens_agent.runner import Runner
from src.lens_agent.store import MemoryAgentStore
from tests.test_lens_agent.helpers import kb_source, scripted

lens_settings.api_keys = "dev"
lens_settings.stream_secret = SecretStr("s3cret")
lens_settings.board_mcp_token = SecretStr("btok")


def model():
    return scripted(
        [("board_get_board", {})],
        [("kb_find_entity", {"name": "Росатом"})],
        [("board_add_objects", {"objects": [
            {"id": "E1", "type": "organization", "label": "Росатом", "call_id": "c2",
             "description": "госкорпорация"},
            {"id": "E2", "type": "person", "label": "Лихачёв", "call_id": "c2"}]})],
        [("board_add_relations", {"relations": [
            {"from": "kb:e2", "to": "kb:e1", "kind": "работает_в", "call_id": "c2"}]})],
        "Росатом возглавляет [[kb:e2]]; на доске два объекта.")


async def main():
    board = lens_app(LensDeps(store=MemoryLensStore(), bus=EventBus()))
    kb, _ = kb_source()
    kb_http = kb.http_app(path="/mcp")
    settings = AgentSettings(mcp=[
        McpEntry(name="kb", url="http://127.0.0.1:18011/mcp", namespace="kb"),
        McpEntry(name="board", url="http://127.0.0.1:18010/mcp/mcp", token="btok", role="board")])
    store, bus = MemoryAgentStore(), EventBus()
    agent = agent_app(AgentDeps(store=store, bus=bus, settings=settings,
                                runner=Runner(store, bus, settings, model)))
    servers = [uvicorn.Server(uvicorn.Config(a, host="127.0.0.1", port=p, log_level="warning"))
               for a, p in ((board, 18010), (kb_http, 18011), (agent, 18020))]
    await asyncio.gather(*(s.serve() for s in servers))


asyncio.run(main())
