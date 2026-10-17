"""Bind each HTTP request to exactly one graph (spec §2)."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from src.api.auth import require_api_key
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.context import DEFAULT_GRAPH_ID, GraphContext, InvalidGraphId, validate_graph_id
from src.tenancy.registry import GraphNotFound, GraphNotReady, get_graph_registry


def choose_graph_id(x_graph: str | None) -> str:
    """Graph selection is by ``X-Graph`` only (absent -> ``default``).

    No per-key authorization here: any valid key may use any graph
    (spec amendment 2026-10-17)."""
    if x_graph is None:
        return DEFAULT_GRAPH_ID
    try:
        validate_graph_id(x_graph)
    except InvalidGraphId:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid X-Graph") from None
    return x_graph


async def resolve_graph(
    _key: ApiKeyRecord = Depends(require_api_key),
    x_graph: str | None = Header(default=None, alias="X-Graph"),
) -> GraphContext:
    gid = choose_graph_id(x_graph)
    try:
        return await get_graph_registry().get(gid)
    except GraphNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"graph {gid!r} not found") from None
    except GraphNotReady as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"graph {gid!r} is {exc.status}") from None
