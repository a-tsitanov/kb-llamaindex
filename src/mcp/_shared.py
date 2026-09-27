"""Shared helpers for the two MCP servers (auth + DI bootstrap)."""

from __future__ import annotations

import os
from typing import Any

from fastapi import HTTPException
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token, get_http_headers
from loguru import logger

from src.api.graph_dep import choose_graph_id
from src.config import settings
from src.tenancy.api_keys import ApiKeyRecord, get_api_key_store
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
    """Best-effort startup check.

    When ``KB_MCP_REQUIRE_AUTH=true``, exits with a clear message if
    no API_KEYS are configured — protects ops from accidentally
    exposing an open MCP server.
    """
    if not _auth_required():
        logger.warning(
            "MCP auth DISABLED via KB_MCP_REQUIRE_AUTH=false — "
            "anyone reaching this port can call tools",
        )
        return
    keys = settings.api.keys_list
    if not keys:
        raise SystemExit(
            "MCP startup: API_KEYS env is empty — refusing to expose "
            "tools without auth.  Set API_KEYS=... or "
            "KB_MCP_REQUIRE_AUTH=false to opt out.",
        )


def is_valid_key(provided: str) -> bool:
    """Match against the configured API key list."""
    if not _auth_required():
        return True
    if not provided:
        return False
    return provided in settings.api.keys_list


class RegistryTokenVerifier(TokenVerifier):
    """Bearer token = API key, looked up in the API-key registry
    (``public.api_keys`` with the legacy env ``API_KEYS`` fallback).

    The resulting ``AccessToken.claims`` carry the key's graphs so every
    tool call can bind itself to one graph via :func:`current_graph`
    (R-A4)."""

    async def verify_token(self, token: str) -> AccessToken | None:
        rec = await get_api_key_store().lookup(token)
        if rec is None:
            return None
        return AccessToken(
            token=token,
            client_id=rec.owner,
            scopes=[],
            claims={
                "owner": rec.owner,
                "graph_ids": list(rec.graph_ids),
                "is_admin": rec.is_admin,
            },
        )


def _configured_mcp_graph() -> str:
    """Graph used when there is no access token (stdio / auth disabled).

    Read from ``KB_MCP_GRAPH`` the same way ``KB_MCP_REQUIRE_AUTH`` is
    (plain env, not a settings field); default ``"default"``."""
    return os.environ.get("KB_MCP_GRAPH", "").strip() or DEFAULT_GRAPH_ID


async def current_graph() -> GraphContext:
    """Resolve the graph this tool call is bound to.

    * HTTP with a verified token: same rules as the REST API
      (``choose_graph_id`` over the token's claims + ``X-Graph`` header).
    * No token (stdio, or auth disabled): the configured ``KB_MCP_GRAPH``.

    The graph is always resolved through the registry.  Every refusal
    raises ``ToolError`` — there is no silent fallback to the default
    graph (R-A4)."""
    tok = get_access_token()
    if tok is None:
        gid = _configured_mcp_graph()
    else:
        c = tok.claims or {}
        if "graph_ids" not in c:
            raise ToolError("access token carries no graph claims")
        key = ApiKeyRecord(
            owner=str(c.get("owner", "")),
            graph_ids=tuple(c["graph_ids"]),
            is_admin=bool(c.get("is_admin", False)),
        )
        headers = get_http_headers(include={"x-graph"})
        try:
            gid = choose_graph_id(key, headers.get("x-graph"))
        except HTTPException as exc:
            raise ToolError(str(exc.detail)) from None
    try:
        return await get_graph_registry().get(gid)
    except GraphNotFound:
        raise ToolError(f"graph {gid!r} not found") from None
    except GraphNotReady as exc:
        raise ToolError(f"graph {gid!r} is {exc.status}") from None


def build_sse_auth() -> RegistryTokenVerifier | None:
    """Build a FastMCP auth provider for HTTP/SSE transports.

    Returns a ``RegistryTokenVerifier`` when ``KB_MCP_REQUIRE_AUTH`` is
    on and env API keys exist; otherwise ``None`` (auth disabled —
    stdio/desktop usage).  The verifier validates the incoming
    ``Authorization: Bearer <key>`` header against the API-key registry
    (DB keys + legacy env keys) and carries the key's graphs as claims.
    Enforced only on HTTP/SSE transports; stdio is unaffected.

    The result is computed once at import time (when the server module
    is loaded), not lazily per request.
    """
    if not _auth_required():
        return None
    keys = settings.api.keys_list
    if not keys:
        logger.warning(
            "build_sse_auth: KB_MCP_REQUIRE_AUTH is on but API_KEYS is "
            "empty — SSE transport will start WITHOUT auth.  Set API_KEYS "
            "or KB_MCP_REQUIRE_AUTH=false.",
        )
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
