"""Shared helpers for the two MCP servers (auth + DI bootstrap)."""

from __future__ import annotations

import os
from typing import Any

from fastapi import HTTPException
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_http_headers
from loguru import logger

from src.api.graph_dep import choose_graph_id
from src.config import settings
from src.tenancy.api_keys import get_api_key_store
from src.tenancy.context import DEFAULT_GRAPH_ID, GraphContext
from src.tenancy.registry import GraphNotFound, GraphNotReady, get_graph_registry


def _auth_required() -> bool:
    """True unless KB_MCP_REQUIRE_AUTH is explicitly disabled."""
    return os.environ.get(
        "KB_MCP_REQUIRE_AUTH", "true",
    ).lower() not in {"0", "false", "no"}


def parse_args() -> dict[str, Any]:
    """Tiny argparse — fastmcp's runtime takes `transport`, `host`,
    `port` via kwargs.  We support `--transport stdio|http|sse` plus the
    standard host/port for the network transports.  `http` is Streamable
    HTTP (the modern MCP transport; endpoint `/mcp`); `sse` is the legacy
    Server-Sent-Events transport.
    """
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument(
        "--transport", choices=["stdio", "http", "sse"], default="stdio",
    )
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=9001)
    args, _ = p.parse_known_args()
    return {
        "transport": args.transport,
        "host": args.host,
        "port": args.port,
    }


def assert_api_key_env_set() -> None:
    """Startup notice.  Auth (when on) validates bearer tokens against the
    API-key registry (``public.api_keys`` + legacy env keys), so an empty
    ``API_KEYS`` env is fine when keys live in the DB (R-P6)."""
    if not _auth_required():
        logger.warning(
            "MCP auth DISABLED via KB_MCP_REQUIRE_AUTH=false — "
            "anyone reaching this port can call tools",
        )
        return
    if not settings.api.keys_list:
        logger.info("MCP auth: API_KEYS env empty — relying on public.api_keys only")


class RegistryTokenVerifier(TokenVerifier):
    """Bearer token = API key, looked up in the API-key registry
    (``public.api_keys`` with the legacy env ``API_KEYS`` fallback).

    Authentication only: the token is not bound to any graph.  The graph
    is chosen per request by :func:`current_graph` (``X-Graph`` header);
    per-graph authorization lives in another layer (spec amendment
    2026-10-17)."""

    async def verify_token(self, token: str) -> AccessToken | None:
        rec = await get_api_key_store().lookup(token)
        if rec is None:
            return None
        return AccessToken(
            token=token,
            client_id=rec.owner,
            scopes=[],
            claims={"owner": rec.owner},
        )


def _configured_mcp_graph() -> str:
    """Graph used when the request carries no ``X-Graph`` header
    (stdio, or an HTTP client that does not send one).

    Read from ``KB_MCP_GRAPH`` the same way ``KB_MCP_REQUIRE_AUTH`` is
    (plain env, not a settings field); default ``"default"``."""
    return os.environ.get("KB_MCP_GRAPH", "").strip() or DEFAULT_GRAPH_ID


async def current_graph() -> GraphContext:
    """Resolve the graph this tool call is bound to.

    Graph = ``X-Graph`` request header if present, else ``KB_MCP_GRAPH``
    (default ``"default"``).  Same for HTTP with or without auth; stdio has
    no HTTP request, hence no header, hence ``KB_MCP_GRAPH``.  The token
    (if any) only authenticates — it never restricts the graph.

    The graph is always resolved through the registry.  Every refusal
    (invalid slug, unknown graph, not ready) raises ``ToolError`` — there
    is no silent fallback to the default graph (R-A4)."""
    x_graph = get_http_headers(include={"x-graph"}).get("x-graph")
    if x_graph is None:
        gid = _configured_mcp_graph()
    else:
        try:
            gid = choose_graph_id(x_graph)
        except HTTPException as exc:
            raise ToolError(str(exc.detail)) from None
    try:
        return await get_graph_registry().get(gid)
    except GraphNotFound:
        raise ToolError(f"graph {gid!r} not found") from None
    except GraphNotReady as exc:
        raise ToolError(f"graph {gid!r} is {exc.status}") from None


def build_sse_auth() -> RegistryTokenVerifier | None:
    """FastMCP auth provider for HTTP transports: a ``RegistryTokenVerifier``
    unless ``KB_MCP_REQUIRE_AUTH`` is disabled.  Keys come from the registry
    (DB + legacy env), so an empty env no longer disables auth (R-P6).
    The verifier authenticates only (no graph claims).  Evaluated once at
    import time; stdio is unaffected."""
    if not _auth_required():
        return None
    return RegistryTokenVerifier()


def log_banner(server_name: str, transport: str, host: str, port: int) -> None:
    if transport == "stdio":
        logger.info("MCP server '{n}' starting  transport=stdio", n=server_name)
    else:
        logger.info(
            "MCP server '{n}' starting  transport={t}  host={h}  port={p}",
            n=server_name, t=transport, h=host, p=port,
        )
