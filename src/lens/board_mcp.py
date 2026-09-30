"""Board MCP: the agent's view of the board (thin wrappers over ``BoardService``).

Mounted in the Lens app at ``/mcp``. lens-agent calls it with ``Authorization: Bearer
<LENS_BOARD_MCP_TOKEN>`` plus ``X-Workspace`` / ``X-Run`` set per run, so the model can
never pick the workspace or pose as another run.

Trust contract for ``source``: the board takes ``source`` inside ``add_objects`` /
``add_relations`` items at face value (BoardService only forces ``run_id`` to the calling
run — see ``board.py::_source``; it does not otherwise validate ``server``/``tool``/
``namespace``). lens-agent MUST strip any model-supplied ``source`` from tool-call
arguments before they reach here and build the real one itself from its own call registry;
the model must only ever be allowed to pass ``call_id``.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers

from src.lens.board import BoardError, BoardService


class BearerGuard:
    """ASGI wrapper: HTTP requests need the bearer token; lifespan passes through."""

    def __init__(self, app: Any, token: str):
        self.app, self._token = app, token.encode()
        self.lifespan = getattr(app, "lifespan", None)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            if not self._ok(scope):
                body = json.dumps({"detail": "invalid or missing bearer token"}).encode()
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": body})
                return
        elif scope["type"] == "websocket":
            # The MCP app has no websocket routes; refuse rather than let an unauthenticated
            # websocket handshake reach it.
            await send({"type": "websocket.close", "code": 1008})
            return
        elif scope["type"] != "lifespan":
            return  # unknown scope type: deny by doing nothing
        await self.app(scope, receive, send)

    def _ok(self, scope) -> bool:
        auth = dict(scope.get("headers") or []).get(b"authorization", b"")
        scheme, _, value = auth.partition(b" ")
        return (bool(self._token) and scheme.lower() == b"bearer"
                and hmac.compare_digest(value.strip(), self._token))


def build_board_mcp(board_of: Callable[[], BoardService]) -> FastMCP:
    """``board_of`` is resolved per call: the host app builds its BoardService in its
    lifespan, after the MCP app is mounted."""
    mcp = FastMCP(name="lens-board")

    async def ctx() -> tuple[BoardService, str, str]:
        board = board_of()
        h = get_http_headers()
        ws, run = h.get("x-workspace", "").strip(), h.get("x-run", "").strip()
        if not ws or not run:
            raise ToolError("нет заголовков X-Workspace / X-Run")
        if await board.store.get_workspace(ws) is None:
            raise ToolError(f"нет расследования {ws!r}")
        return board, ws, run

    async def call(fn, *args):  # BoardError → message the agent can act on
        try:
            return await fn(*args)
        except BoardError as e:
            raise ToolError(str(e)) from e

    @mcp.tool
    async def get_board(limit: int = 50, include_hidden: bool = False) -> dict:
        """Объекты на доске (свежие первыми; закреплённые и объекты этого запуска всегда
        включены), связи между ними и скрытые ключи. Смотри сюда перед добавлением."""
        board, ws, run = await ctx()
        return await board.get_board(ws, run, max(1, min(limit, 200)), include_hidden)

    @mcp.tool
    async def find_on_board(query: str) -> list[dict]:
        """Найти объекты доски по названию (нормализованное совпадение слов)."""
        board, ws, _ = await ctx()
        return await board.find_on_board(ws, query)

    @mcp.tool
    async def get_object(key: str) -> dict:
        """Карточка объекта: тип, название, описание, атрибуты, источники."""
        board, ws, _ = await ctx()
        o = await board.get_object(ws, key)
        if o is None:
            raise ToolError(f"нет объекта {key!r} на доске")
        return o

    @mcp.tool
    async def add_objects(objects: list[dict[str, Any]]) -> dict:
        """Добавить объекты из результатов источников: [{call_id, row}] или [{call_id, id}].
        call_id — вызов инструмента-источника; row — номер строки [N] в его результате,
        id — точно как в строке (или label).
        Название, тип и описание берутся из источника; сущности не из результата отклоняются.
        Не больше 50 за вызов. Возвращает ключи (key) для связей и заметки."""
        board, ws, run = await ctx()
        return await call(board.add_objects, ws, run, objects)

    @mcp.tool
    async def add_relations(relations: list[dict[str, Any]]) -> dict:
        """Связи между объектами доски: [{from, to, call_id}], from/to — ключи.
        Проходят только связи, которые есть в результате источника; вид связи берётся оттуда."""
        board, ws, run = await ctx()
        return await call(board.add_relations, ws, run, relations)

    @mcp.tool
    async def add_note(text: str) -> dict:
        """Короткий ответ на доске; объекты упоминай как [[key]]. Одна заметка на запуск."""
        board, ws, run = await ctx()
        return await call(board.add_note, ws, run, text)

    @mcp.tool
    async def hide(keys: list[str]) -> dict:
        """Скрыть объекты (ничего не удаляется)."""
        board, ws, run = await ctx()
        return await board.hide(ws, run, keys)

    @mcp.tool
    async def show(keys: list[str]) -> dict:
        """Вернуть скрытые объекты."""
        board, ws, run = await ctx()
        return await board.show(ws, run, keys)

    @mcp.tool
    async def undo() -> dict:
        """Отменить изменения предыдущего запроса (не текущего)."""
        board, ws, run = await ctx()
        return await call(board.undo, ws, run)

    return mcp


def board_mcp_app(board_of: Callable[[], BoardService], token: str) -> BearerGuard:
    """ASGI app to mount at ``/mcp`` (endpoint ``/mcp/mcp``); its ``lifespan`` must run
    inside the host app's lifespan."""
    return BearerGuard(build_board_mcp(board_of).http_app(path="/mcp"), token)
