"""Bind each HTTP request to exactly one graph, and authorize it (spec §3.1).

One dependency per action, built by :func:`graph_for` and exported as four
module-level objects.  A route picks the one matching what it does; the
decision itself belongs to :mod:`src.tenancy.authz`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, Header, HTTPException, status

from src.api.auth import require_api_key
from src.tenancy import authz
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.authz import Action
from src.tenancy.context import DEFAULT_GRAPH_ID, GraphContext, InvalidGraphId, validate_graph_id
from src.tenancy.registry import GraphNotFound, GraphNotReady, get_graph_registry

# One body for "no such graph" and for "someone else's graph" (spec §5).
# It names no slug: a 404 that echoed the id of one but not of the other
# would be an existence oracle for every graph in the installation.
GRAPH_NOT_FOUND_DETAIL = "graph not found"


def choose_graph_id(
    x_graph: str | None,
    key: ApiKeyRecord | None = None,
    *,
    default: str = DEFAULT_GRAPH_ID,
) -> str:
    """Graph selection: ``X-Graph`` if given, else the key's own graph when it
    has exactly one, else ``default``.

    ``default`` — то, чем кончается выбор, когда ни заголовка, ни сужения
    нет.  Шов MCP передаёт сюда ``KB_MCP_GRAPH``, чтобы правило выбора
    существовало в одном месте, а не в двух похожих.

    Про фидерный ключ.  Ключ, сужённый до ОДНОГО графа
    (``api_keys.graph_ids``), без заголовка попадал бы на ``default``,
    которого в его списке нет, и получал бы отказ на ровном месте — грабли
    на каждый новый фидер.  Поэтому единственный граф ключа и есть его
    умолчание.  Двух графов это не касается: подставлять один из них было
    бы догадкой за клиента.

    Это умолчание, а НЕ ограничение: названный заголовком граф не
    подменяется никогда, иначе ключ не смог бы получить честный отказ по
    чужому графу, и 404 с 403 перестали бы различаться.  Решение о доступе
    по-прежнему принимает ``authz.guard`` — здесь его нет, потому что ту же
    функцию зовёт шов MCP (``src/mcp/_shared.py``) со своим способом
    отвечать об ошибке.
    """
    if x_graph is None:
        if key is not None and key.graph_ids is not None and len(key.graph_ids) == 1:
            return key.graph_ids[0]
        return default
    try:
        validate_graph_id(x_graph)
    except InvalidGraphId:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid X-Graph") from None
    return x_graph


def graph_for(action: Action) -> Callable[..., Awaitable[GraphContext]]:
    """Build the graph dependency for routes performing ``action``.

    The resolution error is held back until after the decision: a graph of
    another tenant must answer exactly as a graph that does not exist, so a
    foreign ``provisioning`` graph may not admit itself with a 409.  Hence
    the order: resolve (keeping the would-be error), decide, and only then
    raise what the registry had to say.
    """

    async def resolve(
        key: ApiKeyRecord = Depends(require_api_key),
        x_graph: str | None = Header(default=None, alias="X-Graph"),
    ) -> GraphContext:
        gid = choose_graph_id(x_graph, key)
        ctx: GraphContext | None = None
        tenant: str | None = None
        deferred: HTTPException | None = None
        try:
            ctx = await get_graph_registry().get(gid)
        except GraphNotFound:
            deferred = HTTPException(status.HTTP_404_NOT_FOUND, GRAPH_NOT_FOUND_DETAIL)
        except GraphNotReady as exc:
            tenant = exc.tenant_id
            deferred = HTTPException(status.HTTP_409_CONFLICT, f"graph {gid!r} is {exc.status}")
        else:
            tenant = ctx.tenant_id
        decision = authz.guard(key, gid, tenant, action)
        if not decision.allowed:
            if decision.reason in ("scope", "graph"):
                # The graph is the key's own: there is nothing to hide, but
                # the slug still stays out of the body for uniformity.
                raise HTTPException(status.HTTP_403_FORBIDDEN, f"{action} not allowed for this key")
            raise HTTPException(status.HTTP_404_NOT_FOUND, GRAPH_NOT_FOUND_DETAIL)
        if deferred is not None:
            raise deferred
        return ctx  # type: ignore[return-value]  # set whenever `deferred` is None

    return resolve


# Four objects, built once: FastAPI caches a dependency per request by the
# identity of its callable, so a `Depends(graph_for(...))` per route would
# resolve the graph twice on a router that also declares one.
resolve_graph = graph_for(Action.READ)
resolve_graph_write = graph_for(Action.WRITE)
resolve_graph_download = graph_for(Action.DOWNLOAD_ORIGINAL)
resolve_graph_admin = graph_for(Action.ADMIN)
