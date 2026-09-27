"""Bind each HTTP request to exactly one graph (spec §2)."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from src.api.auth import require_api_key
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.context import GraphContext, InvalidGraphId, validate_graph_id
from src.tenancy.registry import GraphNotFound, GraphNotReady, get_graph_registry


def choose_graph_id(key: ApiKeyRecord, x_graph: str | None) -> str:
    if x_graph is None:
        if len(key.graph_ids) == 1:
            return key.graph_ids[0]
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Graph header required for this key")
    try:
        validate_graph_id(x_graph)
    except InvalidGraphId:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "graph not allowed for this key") from None
    if key.is_admin or x_graph in key.graph_ids:
        return x_graph
    raise HTTPException(status.HTTP_403_FORBIDDEN, "graph not allowed for this key")


async def resolve_graph(
    key: ApiKeyRecord = Depends(require_api_key),
    x_graph: str | None = Header(default=None, alias="X-Graph"),
) -> GraphContext:
    gid = choose_graph_id(key, x_graph)
    try:
        return await get_graph_registry().get(gid)
    except GraphNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"graph {gid!r} not found") from None
    except GraphNotReady as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"graph {gid!r} is {exc.status}") from None
