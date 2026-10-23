"""Шов доступа MCP фидера: право `sources` на ровно один граф.

Сам шов — `src/mcp/_shared.py`; здесь только его применение к фидеру.
Токен, заголовок `X-Graph` и выбор графа читаются теми же средствами, что и
у остальных MCP, логика токена не копируется.
"""

from __future__ import annotations

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token, get_http_headers

from src.api.graph_dep import GRAPH_NOT_FOUND_DETAIL
from src.mcp._shared import key_from_token, resolve_graph
from src.tenancy.authz import Action, authorize
from src.tenancy.context import GraphContext


async def require_sources_access(feeder_graph_id: str) -> GraphContext:
    """Вернуть контекст графа фидера или бросить ``ToolError``.

    Зовётся ``authorize``, а НЕ ``guard``.  ``guard`` подчиняется
    ``AUTHZ_MODE``: в режиме ``log`` он пропускает отказ, в ``off`` не
    смотрит правила вовсе.  Для чтения это окно раскатки, а здесь за
    инструментом настоящий аккаунт Telegram: ключ, у которого есть лишь
    ``read``/``write``, не должен им распоряжаться ни на каком стенде.
    ``authorize`` решает всегда.

    Порядок: токен обязателен (без него — отказ, в отличие от stdio-веток
    чтения); чужой граф отсекается ДО обращения к реестру; затем реестр,
    затем решение, и только после него — ошибка готовности графа, чтобы
    чужой арендатор не узнал о графе по тексту ошибки.
    """
    token = get_access_token()
    if token is None:
        raise ToolError("authentication required: sources tools need an API key")
    key = key_from_token(token)
    x_graph = get_http_headers(include={"x-graph"}).get("x-graph")
    if x_graph and x_graph != feeder_graph_id:
        raise ToolError("foreign graph: this server works only with the feeder's graph")

    resolved = await resolve_graph(feeder_graph_id)

    decision = authorize(key, feeder_graph_id, resolved.tenant, Action.SOURCES)
    if not decision.allowed:
        if decision.reason in ("scope", "graph"):
            raise ToolError(f"forbidden: {Action.SOURCES} not allowed")
        raise ToolError(GRAPH_NOT_FOUND_DETAIL)
    return resolved.context_or_raise()
