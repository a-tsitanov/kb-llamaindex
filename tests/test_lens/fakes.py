"""Scripted fakes shared by Lens tests."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from src.lens.llm import ChatReply


@asynccontextmanager
async def lifespan_of(app):
    """httpx.ASGITransport does not run the ASGI lifespan; the mounted MCP app needs it."""
    started, stopped, inbox = asyncio.Event(), asyncio.Event(), asyncio.Queue()

    async def send(msg):
        {"lifespan.startup.complete": started, "lifespan.shutdown.complete": stopped}.get(
            msg["type"], asyncio.Event()).set()

    task = asyncio.create_task(app({"type": "lifespan"}, inbox.get, send))
    await inbox.put({"type": "lifespan.startup"})
    await started.wait()
    try:
        yield
    finally:
        await inbox.put({"type": "lifespan.shutdown"})
        await stopped.wait()
        await task


def mcp_client(app, url: str, headers: dict) -> Client:
    """fastmcp Client talking to an in-process ASGI app (no sockets)."""
    def factory(headers=None, timeout=None, auth=None, **_):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test", headers=headers,
                                 timeout=timeout, auth=auth)
    return Client(StreamableHttpTransport(url=url, headers=headers,
                                          httpx_client_factory=factory))


class FakeLLM:
    def __init__(self, chat_replies=None, json_replies=None):
        self.chat_replies = list(chat_replies or [])
        self.json_replies = list(json_replies or [])
        self.chat_calls: list[dict] = []
        self.json_calls: list[dict] = []

    async def chat(self, *, model, messages, tools=None, tool_choice=None):
        self.chat_calls.append({"model": model, "messages": list(messages), "tools": tools,
                                "tool_choice": tool_choice})
        if not self.chat_replies:
            return ChatReply(text="(no more scripted replies)")
        return self.chat_replies.pop(0)

    async def json(self, *, model, messages):
        self.json_calls.append({"model": model, "messages": list(messages)})
        reply = self.json_replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
