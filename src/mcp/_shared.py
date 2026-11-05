"""Shared helpers for the two MCP servers (auth + DI bootstrap)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterable
from typing import Any, NamedTuple

from fastapi import HTTPException
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token, get_http_headers
from loguru import logger

from src.api.graph_dep import GRAPH_NOT_FOUND_DETAIL, choose_graph_id
from src.config import settings
from src.tenancy import authz
from src.tenancy.api_keys import ApiKeyRecord, get_api_key_store
from src.tenancy.authz import Action
from src.tenancy.context import DEFAULT_GRAPH_ID, DEFAULT_TENANT_ID, GraphContext
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

    The token is minted ONCE, when the connection authenticates, and it is
    still not bound to any graph: the graph is chosen per call by
    :func:`current_graph` (``X-Graph`` header).  What the token now carries
    is the key's RIGHTS, so that every tool call can be authorized on its own
    (spec 2026-10-18 §3.2) — checking at the handshake would let one
    long-lived MCP session keep rights across any number of graphs.  This
    supersedes ``docs/superpowers/plans/2026-10-17-project-boundaries.md:139``,
    which still described authentication-only tokens.

    mcp-search/-tools/-stats now wait for ``init`` (compose, S3), so the
    schema is migrated before the first lookup; the schema-independent loader
    in :mod:`src.tenancy.api_keys` is the second line of defence for the
    offline cluster, where ``depends_on`` is reset.

    Claims hold JSON primitives only — fastmcp may serialise or log them."""

    async def verify_token(self, token: str) -> AccessToken | None:
        rec = await get_api_key_store().lookup(token)
        if rec is None:
            return None
        scopes = sorted(rec.scopes)
        return AccessToken(
            token=token,
            client_id=rec.owner,
            scopes=scopes,
            claims={
                "owner": rec.owner,
                "tenant_id": rec.tenant_id,
                "scopes": scopes,
                "graph_ids": list(rec.graph_ids) if rec.graph_ids is not None else None,
            },
        )


def key_from_token(tok: AccessToken) -> ApiKeyRecord:
    """Rebuild the key record from the claims :meth:`RegistryTokenVerifier.verify_token`
    wrote — the inverse of that mapping, and the only reader of those claims.

    Reading the rights back off the token keeps the per-call decision free of
    a key-store round trip (and of its 30 s cache), which matters because the
    decision is taken on every tool call."""
    c = tok.claims
    graph_ids = c.get("graph_ids")
    return ApiKeyRecord(
        owner=c.get("owner") or tok.client_id,
        tenant_id=c.get("tenant_id") or DEFAULT_TENANT_ID,
        scopes=frozenset(c.get("scopes") or tok.scopes or ()),
        graph_ids=tuple(graph_ids) if graph_ids is not None else None,
    )


# Прежнее имя: тесты и старые вызовы читают его.
_record_from_token = key_from_token


class GraphResolution(NamedTuple):
    """Итог обращения к реестру: контекст, арендатор и отложенная ошибка."""

    ctx: GraphContext | None
    tenant: str | None
    deferred: ToolError | None

    def context_or_raise(self) -> GraphContext:
        """Бросить отложенную ошибку или вернуть контекст.  Зовётся только
        ПОСЛЕ решения о доступе."""
        if self.deferred is not None:
            raise self.deferred
        return self.ctx  # type: ignore[return-value]  # задан, пока deferred is None


async def resolve_graph(gid: str) -> GraphResolution:
    """Найти граф в реестре, НЕ бросая ошибку «нет графа / не готов».

    Контракт: отказ реестра возвращается как ``deferred`` и поднимается
    вызывающим только после его собственного решения о доступе
    (``guard`` или ``authorize``), чтобы ключ без права не узнал, есть ли
    граф и готов ли он.  Арендатор приходит в ``GraphContext`` или
    ``GraphNotReady`` — второго обращения к реестру не нужно; для
    несуществующего графа он ``None``.  Само решение здесь не принимается.
    """
    try:
        ctx = await get_graph_registry().get(gid)
    except GraphNotFound:
        return GraphResolution(None, None, ToolError(GRAPH_NOT_FOUND_DETAIL))
    except GraphNotReady as exc:
        return GraphResolution(
            None, exc.tenant_id, ToolError(f"graph {gid!r} is {exc.status}"),
        )
    return GraphResolution(ctx, ctx.tenant_id, None)


def _configured_mcp_graph() -> str:
    """Graph used when the request carries no ``X-Graph`` header
    (stdio, or an HTTP client that does not send one).

    Read from ``KB_MCP_GRAPH`` the same way ``KB_MCP_REQUIRE_AUTH`` is
    (plain env, not a settings field); default ``"default"``."""
    return os.environ.get("KB_MCP_GRAPH", "").strip() or DEFAULT_GRAPH_ID


_warned_no_token = False


def _warn_unauthenticated_once() -> None:
    """One line per process, not per tool call: stdio takes this branch on
    every single call and the log would be nothing else."""
    global _warned_no_token
    if not _warned_no_token:
        _warned_no_token = True
        logger.warning(
            "MCP tool call without an access token (stdio, or "
            "KB_MCP_REQUIRE_AUTH=false) — graph authorization skipped",
        )


async def current_graph(action: Action = Action.READ) -> GraphContext:
    """Resolve the graph this tool call is bound to, and authorize ``action`` on it.

    Graph = ``X-Graph`` request header if present, else ``KB_MCP_GRAPH``
    (default ``"default"``).  Same for HTTP with or without auth; stdio has
    no HTTP request, hence no header, hence ``KB_MCP_GRAPH``.  The token
    never restricts WHICH graph may be named — it decides whether the named
    one may be used.

    Checked on every call, never once at the handshake: one MCP session
    outlives any number of ``X-Graph`` values (spec 2026-10-18 §3.2).

    Resolution and decision are ordered exactly as in the HTTP seam
    (:func:`src.api.graph_dep.graph_for`): the registry's own refusal is held
    back until after the decision, so a foreign graph that happens to be
    ``provisioning`` cannot admit its existence with a readiness error.  The
    tenant travels in ``GraphContext``/``GraphNotReady``, so no second trip
    to the registry is needed.

    Every refusal (invalid slug, unknown graph, not ready, not authorized)
    raises ``ToolError`` — there is no silent fallback to the default graph
    (R-A4)."""
    # Токен читается ДО выбора графа: ключ, сужённый до одного графа
    # (фидер), задаёт его сам — тем же правилом, что и HTTP-шов.  Иначе
    # ``KB_MCP_GRAPH`` увёл бы такой ключ в чужой граф и дал бы отказ там,
    # где клиент ничего не выбирал.
    token = get_access_token()
    key = key_from_token(token) if token is not None else None
    x_graph = get_http_headers(include={"x-graph"}).get("x-graph")
    try:
        gid = choose_graph_id(x_graph, key, default=_configured_mcp_graph())
    except HTTPException as exc:
        raise ToolError(str(exc.detail)) from None
    resolved = await resolve_graph(gid)
    tenant = resolved.tenant
    if token is None:
        # No token at all: stdio (no HTTP request) or HTTP with
        # KB_MCP_REQUIRE_AUTH=false.  There is no key to decide about, and
        # refusing here would break both documented deployments, so the call
        # proceeds exactly as before this feature (spec §3.2).
        _warn_unauthenticated_once()
    else:
        decision = authz.guard(key, gid, tenant, action)
        if not decision.allowed:
            if decision.reason in ("scope", "graph"):
                # The graph is the key's own; only the right is missing.
                raise ToolError(f"forbidden: {action} not allowed")
            # Someone else's graph answers as one that does not exist.
            raise ToolError(GRAPH_NOT_FOUND_DETAIL)
    return resolved.context_or_raise()


def current_principal() -> str:
    """``owner`` ключа этого вызова, или пусто без токена.

    Нужен подписке наблюдения: `watch.owner` — корзина ЛЕНТЫ и сегодня
    равен константе 'default', а доставке нужно имя, которое есть в
    ``public.api_keys``, иначе право проверить не по чему.  Пусто
    означает stdio (или HTTP с выключенной аутентификацией) — такая
    подписка остаётся ленточной, push ей не положен.
    """
    token = get_access_token()
    if token is None:
        return ""
    return key_from_token(token).owner


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


DOWNLOAD_HINT = (
    "When available, download_url links to the source document; use it when citing."
)


def document_download_url(doc_id: Any, graph: GraphContext) -> str | None:
    template = settings.api.document_url
    if not template or (not graph.is_default and "{graph_id}" not in template):
        return None
    try:
        return template.format(doc_id=str(uuid.UUID(str(doc_id))), graph_id=graph.id)
    except (ValueError, TypeError, AttributeError, KeyError, IndexError):
        return None


async def document_links(doc_ids: Iterable[Any], graph: GraphContext) -> dict[str, dict[str, str]]:
    from src.intake.repository import IntakeRepository

    wanted = {str(d): document_download_url(d, graph) for d in doc_ids if d}
    wanted = {key: url for key, url in wanted.items() if url}
    if not wanted:
        return {}
    canonical = {key: str(uuid.UUID(key)) for key in wanted}
    try:
        paths = await IntakeRepository(graph=graph).paths_by_ids(sorted(set(canonical.values())))
    except Exception as exc:
        logger.warning("document_links: file names unavailable: {e}", e=exc)
        paths = {}
    result = {}
    for key, url in wanted.items():
        path, original = paths.get(canonical[key], ("", None))
        name = (original or path or "").rsplit("/", 1)[-1]
        result[key] = {"download_url": url, **({"file_name": name} if name else {})}
    return result


async def attach_document_links(items: list[dict[str, Any]], graph: GraphContext) -> list[dict[str, Any]]:
    links = await document_links((item.get("doc_id") for item in items), graph)
    documents: dict[str, dict[str, Any]] = {}
    for item in items:
        doc = str(item.get("doc_id") or "")
        if doc in links:
            item.update(links[doc])
            documents.setdefault(doc, {"doc_id": doc, **links[doc]})
    return list(documents.values())
