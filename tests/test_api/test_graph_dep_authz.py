"""HTTP seam: ``graph_for(action)`` decides, and the §5 codes come out of it.

The table runs against the real ASGI app, so the order FastAPI actually uses
(auth -> graph dependency -> handler) is what is asserted, not a hand-rolled
imitation of it.

Every test pins the mode by ASSIGNING ``settings.authz.mode``, never with
``monkeypatch.setenv``: ``settings.authz`` is a cached_property on the
process-wide singleton, so the env is read once and never again.  Pinning is
also what keeps these outcomes independent of an ambient ``AUTHZ_MODE`` — the
suite is accepted both with the variable unset and with ``AUTHZ_MODE=enforce``
exported.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from loguru import logger

from src.api import auth, graph_dep
from src.config import settings
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.authz import ALL_ACTIONS, Action
from src.tenancy.context import new_graph_context
from src.tenancy.registry import GraphNotFound, GraphNotReady

# A read route, and one that stays read: spec §3.1 keeps GET /stats/messages
# on `resolve_graph`, so the rows below that expect "read not allowed" do not
# silently turn into "admin not allowed" when S6 labels the routes.
PATH = "/api/v1/stats/messages"
MISSING = graph_dep.GRAPH_NOT_FOUND_DETAIL

# What the registry knows: graph id -> owning tenant.  `ghost` is in neither.
_READY = {"mine": "t1", "narrow": "t1", "theirs": "t2"}
_NOT_READY = {"mine_prov": "t1", "theirs_prov": "t2"}

KEYS = {
    "full": ApiKeyRecord(owner="u", tenant_id="t1", scopes=ALL_ACTIONS, graph_ids=None),
    "writeonly": ApiKeyRecord(
        owner="w", tenant_id="t1", scopes=frozenset({"write"}), graph_ids=None
    ),
    "narrowed": ApiKeyRecord(owner="n", tenant_id="t1", scopes=ALL_ACTIONS, graph_ids=("mine",)),
}


class _Store:
    async def lookup(self, raw):
        return KEYS.get(raw)


class _Reg:
    async def get(self, gid):
        if gid in _NOT_READY:
            raise GraphNotReady(gid, "provisioning", _NOT_READY[gid])
        if gid not in _READY:
            raise GraphNotFound(gid)
        return new_graph_context(gid, tenant_id=_READY[gid])


@pytest.fixture
def seams(monkeypatch):
    """Key store and registry replaced; the mode is left to the test."""
    monkeypatch.setattr(auth, "get_api_key_store", lambda: _Store())
    monkeypatch.setattr(graph_dep, "get_graph_registry", lambda: _Reg())
    return monkeypatch


@pytest.fixture
def enforce(seams):
    seams.setattr(settings.authz, "mode", "enforce")
    return seams


@pytest.fixture
def log_lines():
    records: list[str] = []
    sink_id = logger.add(records.append, format="{message}", level="WARNING")
    yield records
    logger.remove(sink_id)


async def _call(headers):
    from src.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.get(PATH, headers=headers)


async def _call_ok(headers):
    """Same call with the handler's aggregation mocked out, so a pass shows as 200."""
    from src.storage.postgres import AsyncPostgres

    with patch.object(AsyncPostgres, "status_counts_by", new=AsyncMock(return_value=[])):
        return await _call(headers)


# Spec §5, top to bottom.  The route is a read route (`resolve_graph`), so
# `writeonly` is a key whose scopes miss the action this route asks for.
@pytest.mark.parametrize(
    ("headers", "code", "detail"),
    [
        ({}, 401, "Missing X-API-Key header"),
        ({"X-API-Key": "unknown"}, 403, "Invalid X-API-Key"),
        ({"X-API-Key": "full", "X-Graph": "Bad;Id"}, 400, "invalid X-Graph"),
        ({"X-API-Key": "full", "X-Graph": "ghost"}, 404, MISSING),
        ({"X-API-Key": "full", "X-Graph": "theirs"}, 404, MISSING),
        ({"X-API-Key": "full", "X-Graph": "mine_prov"}, 409, "graph 'mine_prov' is provisioning"),
        ({"X-API-Key": "full", "X-Graph": "theirs_prov"}, 404, MISSING),
        ({"X-API-Key": "writeonly", "X-Graph": "mine"}, 403, "read not allowed for this key"),
        ({"X-API-Key": "narrowed", "X-Graph": "narrow"}, 403, "read not allowed for this key"),
    ],
)
async def test_refusal_table(enforce, headers, code, detail):
    r = await _call(headers)
    assert (r.status_code, r.json()["detail"]) == (code, detail), r.text


async def test_foreign_graph_is_indistinguishable_from_missing(enforce):
    # A different body, or a body naming the slug, would be an existence
    # oracle: that is why the 409 of a FOREIGN not-ready graph is a 404 too.
    ghost = await _call({"X-API-Key": "full", "X-Graph": "ghost"})
    foreign = await _call({"X-API-Key": "full", "X-Graph": "theirs"})
    foreign_prov = await _call({"X-API-Key": "full", "X-Graph": "theirs_prov"})
    assert ghost.status_code == foreign.status_code == foreign_prov.status_code == 404
    assert ghost.content == foreign.content == foreign_prov.content
    assert "theirs" not in foreign.text and "theirs_prov" not in foreign_prov.text


async def test_own_ready_graph_passes(enforce):
    r = await _call_ok({"X-API-Key": "full", "X-Graph": "mine"})
    assert r.status_code == 200, r.text


async def test_own_narrowed_graph_passes(enforce):
    r = await _call_ok({"X-API-Key": "narrowed", "X-Graph": "mine"})
    assert r.status_code == 200, r.text


async def test_log_mode_lets_foreign_graph_through(seams, log_lines):
    # The dark-launch window: the line is written, the request still runs.
    seams.setattr(settings.authz, "mode", "log")
    r = await _call_ok({"X-API-Key": "full", "X-Graph": "theirs"})
    assert r.status_code == 200, r.text
    assert [line for line in log_lines if "would-deny" in line and "reason=tenant" in line]


async def test_off_mode_lets_foreign_graph_through_silently(seams, log_lines):
    seams.setattr(settings.authz, "mode", "off")
    r = await _call_ok({"X-API-Key": "full", "X-Graph": "theirs"})
    assert r.status_code == 200, r.text
    assert [line for line in log_lines if "authz" in line] == []


async def test_not_ready_own_graph_still_409_in_log_mode(seams):
    # Readiness is not an authorization verdict; it survives every mode.
    seams.setattr(settings.authz, "mode", "log")
    r = await _call({"X-API-Key": "full", "X-Graph": "mine_prov"})
    assert (r.status_code, r.json()["detail"]) == (409, "graph 'mine_prov' is provisioning")


@pytest.mark.parametrize(
    ("dep_name", "scopes", "allowed"),
    [
        ("resolve_graph", {"read"}, True),
        ("resolve_graph", {"write"}, False),
        ("resolve_graph_write", {"write"}, True),
        ("resolve_graph_write", {"read"}, False),
        # read does NOT imply download_original (spec A4), in both directions
        ("resolve_graph_download", {"download_original"}, True),
        ("resolve_graph_download", {"read"}, False),
        ("resolve_graph_admin", {"admin"}, True),
        ("resolve_graph_admin", {"read", "write"}, False),
    ],
)
async def test_each_dependency_asks_for_its_own_action(seams, dep_name, scopes, allowed):
    seams.setattr(settings.authz, "mode", "enforce")
    key = ApiKeyRecord(owner="k", tenant_id="t1", scopes=frozenset(scopes), graph_ids=None)
    dep = getattr(graph_dep, dep_name)
    if allowed:
        assert (await dep(key, "mine")).id == "mine"
        return
    with pytest.raises(HTTPException) as ei:
        await dep(key, "mine")
    assert ei.value.status_code == 403
    assert ei.value.detail.endswith(" not allowed for this key")
    assert "mine" not in ei.value.detail  # no slug in a 403 either


def test_the_four_dependencies_are_one_object_each():
    # Routes must import these, not call `graph_for` in the Depends(): FastAPI
    # caches a dependency per request by the identity of its callable, so a
    # fresh object per route would resolve the graph twice.
    deps = (
        graph_dep.resolve_graph,
        graph_dep.resolve_graph_write,
        graph_dep.resolve_graph_download,
        graph_dep.resolve_graph_admin,
    )
    assert len({id(d) for d in deps}) == 4
    assert graph_dep.graph_for(Action.READ) is not graph_dep.resolve_graph
