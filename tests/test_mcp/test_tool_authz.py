"""MCP seam: the key is checked on EVERY tool call, not once at the handshake.

``current_graph(action)`` is the single choke point — a mutating tool declares
``Action.WRITE`` by passing it, everything else stays read — so these tests
drive the real tools and stub only the repositories behind them.

The mode is pinned by ASSIGNING ``settings.authz.mode``, never with
``monkeypatch.setenv``: ``settings.authz`` is a cached_property on the
process-wide singleton, so the env is read once and never again.  Pinning is
also what keeps these outcomes independent of an ambient ``AUTHZ_MODE`` — the
suite is accepted both with the variable unset and with ``AUTHZ_MODE=enforce``
exported.
"""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError
from loguru import logger

import src.mcp._shared as sh
from src.config import settings
from src.mcp import tools_server as ts
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.context import new_graph_context
from tests.test_mcp.test_current_graph import mint_token

TENANT = "t1"
READ_ONLY = ApiKeyRecord(owner="r", tenant_id=TENANT, scopes=frozenset({"read"}), graph_ids=None)
WRITE_ONLY = ApiKeyRecord(owner="w", tenant_id=TENANT, scopes=frozenset({"write"}), graph_ids=None)


class _Reg:
    async def get(self, gid):
        return new_graph_context(gid, tenant_id=TENANT)


class _Watch:
    """Watch repository that records every call it receives, so a refusal can
    be shown to stop BEFORE the repository, not after it."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def add_watch(self, owner, vid, name, *, kinds=None, note=""):
        self.calls.append("add_watch")

    async def remove_watch(self, owner, vid):
        self.calls.append("remove_watch")
        return True

    async def list_watch(self, owner):
        self.calls.append("list_watch")
        return []

    async def feed(self, owner, *, include_acked, limit):
        self.calls.append("feed")
        return []

    async def mark_seen(self, owner, ids):
        self.calls.append("mark_seen")

    async def ack(self, owner, *, event_ids=None, all_events=False):
        self.calls.append("ack")
        return 1


class _Search:
    async def search(self, query, *, mode="substring", label=None, limit=10):
        return []


@pytest.fixture
def seam(monkeypatch):
    """Registry, headers and the watch repositories stubbed; the caller's key
    and the mode are left to the test.  Returns ``as_key(rec, mode=...)``,
    which authenticates as ``rec`` (``None`` = no token at all) and hands back
    the watch repository to assert against."""
    watch = _Watch()
    monkeypatch.setattr(sh, "get_graph_registry", lambda: _Reg())
    monkeypatch.setattr(sh, "get_http_headers", lambda **kw: {"x-graph": "acme"})
    monkeypatch.setattr(ts, "_watch_repo", lambda graph: watch)
    monkeypatch.setattr(ts, "_entity_search", lambda graph: _Search())

    async def as_key(rec: ApiKeyRecord | None, *, mode: str = "enforce") -> _Watch:
        monkeypatch.setattr(settings.authz, "mode", mode)
        tok = None if rec is None else await mint_token(monkeypatch, rec)
        monkeypatch.setattr(sh, "get_access_token", lambda: tok)
        return watch

    return as_key


@pytest.fixture
def log_lines():
    records: list[str] = []
    sink_id = logger.add(records.append, format="{message}", level="WARNING")
    yield records
    logger.remove(sink_id)


async def test_read_tool_without_read_scope_is_refused(seam):
    watch = await seam(WRITE_ONLY)
    with pytest.raises(ToolError, match="forbidden: read not allowed"):
        await ts.kb_watchlist()
    assert watch.calls == []


@pytest.mark.parametrize(
    ("name", "call"),
    [
        ("kb_watch", lambda: ts.kb_watch("Блинов")),
        ("kb_unwatch", lambda: ts.kb_unwatch("Блинов")),
        ("kb_ack", lambda: ts.kb_ack([1])),
    ],
)
async def test_mutating_watch_tools_ask_for_write(seam, name, call):
    # The three tools that change state; the refusal lands before the
    # repository is touched, so nothing is half-written.
    watch = await seam(READ_ONLY)
    with pytest.raises(ToolError, match="forbidden: write not allowed"):
        await call()
    assert watch.calls == [], name


async def test_watch_feed_asks_for_write_because_it_marks_rows_seen(seam):
    """The feed looks like a read and is not: `_watch_feed` calls
    `mark_seen`, so a read-only key could clear another operator's feed on
    every poll.  The repository must not be reached at all."""
    watch = await seam(READ_ONLY)
    with pytest.raises(ToolError, match="forbidden: write not allowed"):
        await ts.kb_watch_feed()
    assert watch.calls == []


async def test_watch_feed_runs_with_a_write_key(seam):
    watch = await seam(WRITE_ONLY)
    assert await ts.kb_watch_feed() == {"count": 0, "cards": []}
    assert watch.calls == ["feed", "mark_seen"]


async def test_full_document_text_asks_for_download_original(seam, monkeypatch):
    """`read_full_document` hands out the raw source text — the same payload
    `GET /api/v1/documents/{id}?variant=text` gates behind
    `download_original`.  A `read` key must not get over MCP what it is
    refused over HTTP."""
    await seam(READ_ONLY)
    called: list[str] = []
    monkeypatch.setattr(ts, "_c", lambda graph: called.append("ctx") or object())
    with pytest.raises(ToolError, match="forbidden: download_original not allowed"):
        await ts.read_full_document("d1")
    assert called == []


async def test_no_access_token_skips_authz(seam):
    """stdio, and HTTP with KB_MCP_REQUIRE_AUTH=false: no token, hence no
    decision — the graph still resolves and the tool runs (spec §3.2)."""
    watch = await seam(None)
    assert await ts.kb_watchlist() == {"watches": []}
    assert watch.calls == ["list_watch"]


async def test_log_mode_allows_and_logs(seam, log_lines):
    # Dark launch: the line is written, the tool still runs.
    watch = await seam(WRITE_ONLY, mode="log")
    assert await ts.kb_watchlist() == {"watches": []}
    assert watch.calls == ["list_watch"]
    assert [ln for ln in log_lines if "would-deny" in ln and "reason=scope" in ln]


async def test_off_mode_allows_silently(seam, log_lines):
    watch = await seam(WRITE_ONLY, mode="off")
    assert await ts.kb_watchlist() == {"watches": []}
    assert watch.calls == ["list_watch"]
    assert [ln for ln in log_lines if "authz" in ln] == []
