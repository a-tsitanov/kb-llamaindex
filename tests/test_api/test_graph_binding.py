"""End-to-end (ASGI) checks that routes bind to the request graph (Task 9)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import auth, graph_dep
from src.config import settings
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.context import default_graph_context, new_graph_context
from tests.test_intake.test_dedup import no_duplicate

# These tests are about BINDING — which graph a route works in — so the key
# is deliberately one no route's action can refuse: `full` carries all four
# actions in tenant `default`, exactly what an `API_KEYS` entry still yields.
# Who may do what lives in test_graph_dep_authz.py (the seam) and
# test_route_actions.py (the label each route declares).
USER = ApiKeyRecord.full("u")
ADMIN = USER  # the same key: routes differ by the action they ask for, not by key kind
READER = ApiKeyRecord(owner="r", tenant_id="default", scopes=frozenset({"read"}), graph_ids=None)


class _Store:
    def __init__(self, rec):
        self.rec = rec

    async def lookup(self, k):
        return self.rec if k == "k" else None


class _Reg:
    async def get(self, gid):
        return default_graph_context() if gid == "default" else new_graph_context(gid)


@pytest.fixture
def as_key(monkeypatch):
    def _set(rec):
        monkeypatch.setattr(auth, "get_api_key_store", lambda: _Store(rec))
        monkeypatch.setattr(graph_dep, "get_graph_registry", lambda: _Reg())
    return _set


async def _post(path, **kw):
    from src.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.post(path, **kw)



async def test_admin_routes_require_key():
    for path in ("/admin/graph/stats", "/admin/monitor/sweep", "/admin/wiki/rebuild",
                 "/api/v1/admin/communities/rebuild"):
        assert (await _post(path)).status_code == 401, path


async def test_admin_routes_reject_invalid_key(as_key):
    as_key(USER)
    for path in ("/admin/graph/stats", "/admin/monitor/sweep", "/admin/wiki/rebuild",
                 "/api/v1/admin/communities/rebuild"):
        r = await _post(path, headers={"X-API-Key": "wrong"})
        assert r.status_code == 403, path


async def test_admin_routes_accept_plain_valid_key(as_key):
    """A key holding `admin` passes every admin endpoint (no separate key kind)."""
    from src.api.routes import admin, graph_admin

    as_key(USER)

    async def _stats(store):
        return {}

    client = MagicMock()
    client.start_workflow = AsyncMock(return_value=MagicMock(id="wf"))
    with (
        patch.object(graph_admin, "_store", side_effect=lambda g: g.id),
        patch.object(graph_admin.analysis, "graph_stats", _stats),
        patch.object(admin, "get_temporal_client", new=AsyncMock(return_value=client)),
        patch("src.api.routes.search_v2.get_temporal_client", new=AsyncMock(return_value=client)),
    ):
        for path in ("/admin/graph/stats", "/admin/monitor/sweep", "/admin/wiki/rebuild",
                     "/api/v1/admin/communities/rebuild"):
            r = await _post(path, headers={"X-API-Key": "k"})
            assert r.status_code not in (401, 403), (path, r.status_code, r.text)
            assert r.status_code < 500, (path, r.status_code, r.text)


async def test_wiki_rebuild_409_for_non_default_graph(as_key):
    as_key(ADMIN)
    r = await _post("/admin/wiki/rebuild", headers={"X-API-Key": "k", "X-Graph": "acme"})
    assert r.status_code == 409
    assert r.json()["detail"] == "wiki is available only for the default graph"


async def test_monitor_sweep_409_for_non_default_graph(as_key):
    as_key(ADMIN)
    r = await _post("/admin/monitor/sweep", headers={"X-API-Key": "k", "X-Graph": "acme"})
    assert r.status_code == 409
    assert r.json()["detail"] == "monitor is available only for the default graph"


async def test_graph_admin_uses_request_graph(as_key):
    from src.api.routes import graph_admin

    as_key(ADMIN)
    seen = []

    async def _stats(store):
        seen.append(store)
        return {}

    with (
        patch.object(graph_admin, "_store", side_effect=lambda g: g.id),
        patch.object(graph_admin.analysis, "graph_stats", _stats),
    ):
        r = await _post("/admin/graph/stats", headers={"X-API-Key": "k", "X-Graph": "acme"})
    assert r.status_code == 200
    assert seen == ["acme"]


async def test_ingest_carries_graph_id_and_prefixed_object_key(as_key):
    from src.intake.repository import IntakeRepository

    as_key(USER)
    storage = MagicMock()
    storage.put_object.return_value = "s3://b/acme/x/f.txt"
    submit = AsyncMock()
    with (
        patch("src.intake.api.ingest.build_minio_storage", return_value=storage),
        no_duplicate(),
        patch.object(IntakeRepository, "accept_document", new=AsyncMock()),
        patch("src.intake.api.ingest.get_temporal_client", new=AsyncMock(return_value=MagicMock())),
        patch("src.intake.api.ingest.submit_document", submit),
    ):
        r = await _post(
            "/api/v1/ingest", headers={"X-API-Key": "k", "X-Graph": "acme"},
            files={"file": ("f.txt", b"hi", "text/plain")},
        )
    assert r.status_code == 202, r.text
    key = storage.put_object.call_args.args[0]
    assert key.startswith("acme/") and key.endswith("/f.txt")
    params = submit.await_args.args[1]
    assert params.graph_id == "acme"


async def _graph_seen_by_ingest(headers):
    from src.intake.repository import IntakeRepository

    submit = AsyncMock()
    storage = MagicMock()
    storage.put_object.side_effect = lambda key, *_a, **_k: f"s3://b/{key}"
    with (
        patch("src.intake.api.ingest.build_minio_storage", return_value=storage),
        no_duplicate(),
        patch.object(IntakeRepository, "accept_document", new=AsyncMock()),
        patch("src.intake.api.ingest.get_temporal_client", new=AsyncMock(return_value=MagicMock())),
        patch("src.intake.api.ingest.submit_document", submit),
    ):
        r = await _post("/api/v1/ingest", headers=headers,
                        files={"file": ("f.txt", b"hi", "text/plain")})
    return r, (submit.await_args.args[1].graph_id if submit.await_args else None)


async def test_any_valid_key_with_x_graph_binds_that_graph(as_key):
    as_key(USER)
    r, gid = await _graph_seen_by_ingest({"X-API-Key": "k", "X-Graph": "acme"})
    assert r.status_code == 202, r.text
    assert gid == "acme"


async def test_no_x_graph_binds_default(as_key):
    as_key(USER)
    r, gid = await _graph_seen_by_ingest({"X-API-Key": "k"})
    assert r.status_code == 202, r.text
    assert gid == "default"


async def test_invalid_x_graph_is_400(as_key):
    as_key(USER)
    from src.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/entities", params={"query": "x"},
                         headers={"X-API-Key": "k", "X-Graph": "Bad;Id"})
    assert r.status_code == 400
    assert r.json()["detail"] == "invalid X-Graph"


async def test_ingest_original_object_key_is_graph_prefixed(as_key):
    from src.intake.repository import IntakeRepository

    as_key(USER)
    storage = MagicMock()
    storage.put_object.side_effect = lambda key, *_a, **_k: f"s3://b/{key}"
    with (
        patch("src.intake.api.ingest.build_minio_storage", return_value=storage),
        no_duplicate(),
        patch.object(IntakeRepository, "accept_document", new=AsyncMock()),
        patch("src.intake.api.ingest.get_temporal_client", new=AsyncMock(return_value=MagicMock())),
        patch("src.intake.api.ingest.submit_document", AsyncMock()),
    ):
        r = await _post(
            "/api/v1/ingest", headers={"X-API-Key": "k", "X-Graph": "acme"},
            files={"file": ("f.md", b"hi", "text/markdown"),
                   "original": ("f.docx", b"PK", "application/octet-stream")},
        )
    assert r.status_code == 202, r.text
    keys = [c.args[0] for c in storage.put_object.call_args_list]
    assert len(keys) == 2
    assert keys[0].startswith("acme/") and keys[0].endswith("/f.md")
    assert keys[1].startswith("acme/") and keys[1].endswith("/original/f.docx")


# S6: the action is declared by the ROUTE, so a key short of it is turned away
# by the dependency — before the handler, before any workflow or storage call.
@pytest.mark.parametrize(
    ("method", "path", "detail"),
    [
        ("post", "/admin/graph/stats", "admin not allowed for this key"),
        ("post", "/admin/wiki/rebuild", "admin not allowed for this key"),
        ("post", "/api/v1/admin/communities/rebuild", "admin not allowed for this key"),
        ("post", "/api/v1/ingest", "write not allowed for this key"),
        ("post", "/api/v1/statistics/load", "write not allowed for this key"),
        ("get", "/api/v1/documents/00000000-0000-0000-0000-000000000000",
         "download_original not allowed for this key"),
    ],
)
async def test_route_action_refuses_a_read_only_key(as_key, monkeypatch, method, path, detail):
    from src.api.main import app

    as_key(READER)
    monkeypatch.setattr(settings.authz, "mode", "enforce")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await getattr(ac, method)(path, headers={"X-API-Key": "k"})
    assert (r.status_code, r.json()["detail"]) == (403, detail), r.text


async def test_read_only_key_still_reads(as_key, monkeypatch):
    from src.intake.repository import IntakeRepository

    as_key(READER)
    monkeypatch.setattr(settings.authz, "mode", "enforce")
    from src.api.main import app

    with patch.object(IntakeRepository, "status_counts_by", new=AsyncMock(return_value=[])):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            r = await ac.get("/api/v1/stats/messages", headers={"X-API-Key": "k"})
    assert r.status_code == 200, r.text
