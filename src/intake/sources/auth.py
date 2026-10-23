"""Шов доступа MCP фидера: право `sources` на ровно один граф.

Сам шов — `src/mcp/_shared.py`; здесь только его применение к фидеру.
Токен, заголовок `X-Graph` и выбор графа читаются теми же средствами, что и
у остальных MCP, логика токена не копируется.
"""

from __future__ import annotations

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token, get_http_headers

from src.api.graph_dep import GRAPH_NOT_FOUND_DETAIL
from src.mcp._shared import _record_from_token
from src.tenancy.authz import Action, authorize
from src.tenancy.context import GraphContext
from src.tenancy.registry import GraphNotFound, GraphNotReady, get_graph_registry


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
    key = _record_from_token(token)
    x_graph = get_http_headers(include={"x-graph"}).get("x-graph")
    if x_graph and x_graph != feeder_graph_id:
        raise ToolError("foreign graph: this server works only with the feeder's graph")

    ctx: GraphContext | None = None
    tenant: str | None = None
    deferred: ToolError | None = None
    try:
        ctx = await get_graph_registry().get(feeder_graph_id)
    except GraphNotFound:
        deferred = ToolError(GRAPH_NOT_FOUND_DETAIL)
    except GraphNotReady as exc:
        tenant = exc.tenant_id
        deferred = ToolError(f"graph {feeder_graph_id!r} is {exc.status}")
    else:
        tenant = ctx.tenant_id

    decision = authorize(key, feeder_graph_id, tenant, Action.SOURCES)
    if not decision.allowed:
        if decision.reason in ("scope", "graph"):
            raise ToolError(f"forbidden: {Action.SOURCES} not allowed")
        raise ToolError(GRAPH_NOT_FOUND_DETAIL)
    if deferred is not None:
        raise deferred
    return ctx  # type: ignore[return-value]  # задан, пока deferred is None
