"""Connections to all configured MCP servers + a merged tool catalog.

A server that is down (not yet listening at startup, restarted mid-session) is
reconnected lazily: ``refresh()`` retries down servers (at most once per
``backoff_s``) and a transport failure during ``call()`` marks the server down and
retries once after reconnecting.  One dead server never breaks the others.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from loguru import logger

from src.lens.config import McpServerConfig


@dataclass
class ToolInfo:
    server: str
    name: str
    description: str
    input_schema: dict
    namespace: str = ""

    @property
    def qualified(self) -> str:
        return f"{self.server}__{self.name}"


@dataclass
class ToolResult:
    payload: Any
    is_error: bool = False
    error: str | None = None


def _default_client(cfg: McpServerConfig) -> Client:
    headers = {}
    if cfg.token is not None:
        headers["Authorization"] = f"Bearer {cfg.token.get_secret_value()}"
    return Client(StreamableHttpTransport(url=cfg.url, headers=headers))


def _maybe_json(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return v
    return v


def extract_payload(result: Any) -> Any:
    """``structured_content`` (fastmcp wraps non-dict returns as ``{"result": x}`` —
    unwrapped, JSON strings parsed); else JSON of the text blocks; else ``{"text": ...}``."""
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        if isinstance(structured, dict) and set(structured) == {"result"}:
            inner = _maybe_json(structured["result"])
            return inner if isinstance(inner, (dict, list)) else {"text": inner}
        return structured
    texts = [getattr(c, "text", "") for c in (getattr(result, "content", None) or [])]
    joined = "\n".join(t for t in texts if t)
    parsed = _maybe_json(joined)
    return parsed if isinstance(parsed, (dict, list)) else {"text": joined}


class McpHub:
    def __init__(
        self,
        servers: list[McpServerConfig],
        client_factory: Callable[[McpServerConfig], Any] | None = None,
        *,
        timeout_s: float = 120.0,
        backoff_s: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._configs = {c.name: c for c in servers}
        self._factory = client_factory or _default_client
        self._timeout_s, self._backoff_s, self._clock = timeout_s, backoff_s, clock
        self._stacks: dict[str, AsyncExitStack] = {}
        self._clients: dict[str, Any] = {}
        self._tools: dict[str, ToolInfo] = {}
        self._status: dict[str, str] = {}
        self._last_try: dict[str, float] = {}

    async def _connect(self, name: str) -> bool:
        cfg = self._configs[name]
        self._last_try[name] = self._clock()
        stack = AsyncExitStack()
        try:
            client = await stack.enter_async_context(self._factory(cfg))
            tools = await client.list_tools()
        except Exception as e:  # one dead server must not kill the hub
            await stack.aclose()
            logger.warning("lens: MCP server {} unavailable: {}", name, e)
            self._status[name] = f"down: {e}"
            return False
        self._stacks[name], self._clients[name] = stack, client
        self._status[name] = "up"
        for t in tools:
            info = ToolInfo(server=name, name=t.name, description=t.description or "",
                            input_schema=dict(t.inputSchema or {}), namespace=cfg.ns)
            self._tools[info.qualified] = info
        return True

    async def _disconnect(self, name: str, reason: str) -> None:
        self._clients.pop(name, None)
        self._tools = {q: t for q, t in self._tools.items() if t.server != name}
        self._status[name] = f"down: {reason}"
        stack = self._stacks.pop(name, None)
        if stack is not None:
            try:
                await stack.aclose()
            except Exception as e:  # a broken session may fail to close; ignore
                logger.debug("lens: closing {} failed: {}", name, e)

    async def start(self) -> None:
        for name in self._configs:
            await self._connect(name)

    async def refresh(self) -> None:
        """Retry servers that are down, respecting the backoff."""
        now = self._clock()
        for name in self._configs:
            if name in self._clients:
                continue
            if now - self._last_try.get(name, float("-inf")) >= self._backoff_s:
                await self._connect(name)

    async def close(self) -> None:
        for name in list(self._stacks):
            await self._disconnect(name, "closed")

    def catalog(self) -> list[ToolInfo]:
        return list(self._tools.values())

    def find(self, qualified: str) -> ToolInfo | None:
        return self._tools.get(qualified)

    def status(self) -> dict[str, str]:
        return dict(self._status)

    async def call(self, server: str, tool: str, args: dict) -> ToolResult:
        if server not in self._configs:
            return ToolResult(payload=None, is_error=True, error=f"unknown server {server!r}")
        for attempt in range(2):
            client = self._clients.get(server)
            if client is None and not await self._connect(server):
                return ToolResult(payload=None, is_error=True,
                                  error=f"server {server!r} not connected")
            client = self._clients[server]
            try:
                res = await client.call_tool(tool, args, timeout=self._timeout_s,
                                             raise_on_error=False)
            except Exception as e:  # transport failure: reconnect once, then give up
                await self._disconnect(server, str(e))
                if attempt == 1:
                    return ToolResult(payload=None, is_error=True, error=str(e))
                continue
            payload = extract_payload(res)
            if getattr(res, "is_error", False):
                return ToolResult(payload=payload, is_error=True,
                                  error=str(payload.get("text", payload))
                                  if isinstance(payload, dict) else str(payload))
            return ToolResult(payload=payload)
        return ToolResult(payload=None, is_error=True, error="unreachable")
