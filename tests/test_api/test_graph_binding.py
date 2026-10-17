"""End-to-end (ASGI) checks that routes bind to the request graph (Task 9)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import auth, graph_dep
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.context import default_graph_context, new_graph_context

# Spec amendment 2026-10-17: a key authenticates only; any valid key may use
# any graph, selected by X-Graph (absent -> default).
USER = ApiKeyRecord(owner="u")
ADMIN = USER  # no admin keys any more — admin endpoints take any valid key


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
    """No admin gating: any valid key passes auth on admin endpoints."""
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


async def test_monitor_watch_409_for_non_default_graph(as_key):
    from src.api.routes import admin

    as_key(ADMIN)
    with patch.object(admin, "mark_watched") as mark:
        r = await _post(
            "/admin/monitor/watch", json=["Acme Corp"],
            headers={"X-API-Key": "k", "X-Graph": "acme"},
        )
    assert r.status_code == 409
    assert r.json()["detail"] == "monitor is available only for the default graph"
    mark.assert_not_called()


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
    from src.storage.postgres import AsyncPostgres

    as_key(USER)
    storage = MagicMock()
    storage.put_object.return_value = "s3://b/acme/x/f.txt"
    submit = AsyncMock()
    with (
        patch("src.api.routes.ingest.build_minio_storage", return_value=storage),
        patch.object(AsyncPostgres, "insert_pending", new=AsyncMock()),
        patch("src.api.routes.ingest.get_temporal_client", new=AsyncMock(return_value=MagicMock())),
        patch("src.api.routes.ingest.submit_document", submit),
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
    from src.storage.postgres import AsyncPostgres

    submit = AsyncMock()
    storage = MagicMock()
    storage.put_object.side_effect = lambda key, *_a, **_k: f"s3://b/{key}"
    with (
        patch("src.api.routes.ingest.build_minio_storage", return_value=storage),
        patch.object(AsyncPostgres, "insert_pending", new=AsyncMock()),
        patch("src.api.routes.ingest.get_temporal_client", new=AsyncMock(return_value=MagicMock())),
        patch("src.api.routes.ingest.submit_document", submit),
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
    from src.storage.postgres import AsyncPostgres

    as_key(USER)
    storage = MagicMock()
    storage.put_object.side_effect = lambda key, *_a, **_k: f"s3://b/{key}"
    with (
        patch("src.api.routes.ingest.build_minio_storage", return_value=storage),
        patch.object(AsyncPostgres, "insert_pending", new=AsyncMock()),
        patch("src.api.routes.ingest.get_temporal_client", new=AsyncMock(return_value=MagicMock())),
        patch("src.api.routes.ingest.submit_document", AsyncMock()),
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
