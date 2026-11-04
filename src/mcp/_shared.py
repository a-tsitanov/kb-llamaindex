"""Shared helpers for the MCP servers (auth + DI bootstrap + document links)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from loguru import logger

from src.config import settings

if TYPE_CHECKING:
    from fastmcp.server.auth import StaticTokenVerifier


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


def build_sse_auth() -> StaticTokenVerifier | None:
    """Build a FastMCP auth provider for HTTP/SSE transports.

    Returns a ``StaticTokenVerifier`` seeded with the configured API
    keys when ``KB_MCP_REQUIRE_AUTH`` is on and keys exist; otherwise
    ``None`` (auth disabled — stdio/desktop usage).  The verifier
    validates the incoming ``Authorization: Bearer <key>`` header
    against the configured key set.  Enforced only on HTTP/SSE
    transports; stdio is unaffected.

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
    from fastmcp.server.auth import StaticTokenVerifier
    return StaticTokenVerifier(
        tokens={
            k: {"sub": "kb-mcp-client", "client_id": "kb"}
            for k in keys
        },
    )


# ── document download links ────────────────────────────────────────
# Every doc_id an MCP tool returns carries `download_url` (the ORIGINAL
# uploaded file, settings.api.document_url template) + `file_name`, so the
# chat agent can show a clickable link right away.

DOWNLOAD_HINT = (
    "Each document comes with `download_url` (the original uploaded file) and "
    "`file_name`: whenever you cite or mention a document, show the user that "
    "link as a clickable link."
)


def _uuid_or_none(doc_id: Any) -> str | None:
    """Canonical UUID string, or None for a non-UUID id (e.g. a legacy
    file_path fallback) that has no downloadable document."""
    try:
        return str(uuid.UUID(str(doc_id)))
    except (ValueError, TypeError, AttributeError):
        return None


def document_download_url(doc_id: Any) -> str | None:
    """Template-only download URL (no DB); None when links are off or the id
    is not a UUID."""
    template = settings.api.document_url
    canonical = _uuid_or_none(doc_id) if template else None
    return template.format(doc_id=canonical) if canonical else None


async def document_links(doc_ids: Iterable[Any]) -> dict[str, dict[str, str]]:
    """``{doc_id: {"download_url", "file_name"}}`` for the UUID ids among
    ``doc_ids``, keyed by the id exactly as passed. ONE Postgres query for the
    file names (basename of original_path, else path). Fail-soft: a DB error
    still yields the template links, just without ``file_name``. Empty
    ``API_DOCUMENT_URL`` → ``{}``."""
    if not settings.api.document_url:
        return {}
    wanted: dict[str, str] = {}  # id as passed → canonical uuid
    for d in doc_ids:
        canonical = _uuid_or_none(d) if d else None
        if canonical:
            wanted[str(d)] = canonical
    if not wanted:
        return {}
    paths: dict[str, tuple[str, str | None]] = {}
    try:
        from src.storage.postgres import AsyncPostgres
        paths = await AsyncPostgres().paths_by_ids(sorted(set(wanted.values())))
    except Exception as exc:
        logger.warning("document_links: file names unavailable: {e}", e=exc)
    out: dict[str, dict[str, str]] = {}
    for given, canonical in wanted.items():
        link = {"download_url": settings.api.document_url.format(doc_id=canonical)}
        path, original = paths.get(canonical, ("", None))
        name = (original or path or "").rsplit("/", 1)[-1]
        if name:
            link["file_name"] = name
        out[given] = link
    return out


async def attach_document_links(
    items: list[dict[str, Any]], key: str = "doc_id",
) -> list[dict[str, Any]]:
    """Add ``download_url`` / ``file_name`` in place to every dict whose
    ``key`` is a known document; returns the de-duplicated
    ``[{doc_id, file_name, download_url}]`` list in item order (empty when
    links are off)."""
    links = await document_links(i.get(key) for i in items)
    documents: dict[str, dict[str, Any]] = {}
    for item in items:
        doc = item.get(key)
        link = links.get(str(doc)) if doc else None
        if link is None:
            continue
        item.update(link)
        documents.setdefault(str(doc), {"doc_id": str(doc), **link})
    return list(documents.values())


def log_banner(server_name: str, transport: str, host: str, port: int) -> None:
    if transport == "stdio":
        logger.info("MCP server '{n}' starting  transport=stdio", n=server_name)
    else:
        logger.info(
            "MCP server '{n}' starting  transport={t}  host={h}  port={p}",
            n=server_name, t=transport, h=host, p=port,
        )
