"""End-to-end (ASGI) checks that routes bind to the request graph (Task 9)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import auth, graph_dep
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.context import new_graph_context

USER = ApiKeyRecord(owner="u", graph_ids=("acme",), is_admin=False)
ADMIN = ApiKeyRecord(owner="ops", graph_ids=("default",), is_admin=True)


class _Store:
    def __init__(self, rec):
        self.rec = rec

    async def lookup(self, k):
        return self.rec if k == "k" else None


class _Reg:
    async def get(self, gid):
        return new_graph_context(gid)


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


async def test_admin_routes_reject_non_admin_key(as_key):
    as_key(USER)
    for path in ("/admin/graph/stats", "/admin/monitor/sweep", "/admin/wiki/rebuild",
                 "/api/v1/admin/communities/rebuild"):
        r = await _post(path, headers={"X-API-Key": "k"})
        assert r.status_code == 403, path


async def test_wiki_rebuild_409_for_non_default_graph(as_key):
    as_key(ADMIN)
    r = await _post("/admin/wiki/rebuild", headers={"X-API-Key": "k", "X-Graph": "acme"})
    assert r.status_code == 409
    assert r.json()["detail"] == "wiki is available only for the default graph"


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
            "/api/v1/ingest", headers={"X-API-Key": "k"},
            files={"file": ("f.txt", b"hi", "text/plain")},
        )
    assert r.status_code == 202, r.text
    key = storage.put_object.call_args.args[0]
    assert key.startswith("acme/") and key.endswith("/f.txt")
    params = submit.await_args.args[1]
    assert params.graph_id == "acme"


async def test_multi_graph_key_without_header_is_400(monkeypatch):
    monkeypatch.setattr(
        auth, "get_api_key_store",
        lambda: _Store(ApiKeyRecord(owner="u", graph_ids=("a", "b"), is_admin=False)),
    )
    from src.api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/entities", params={"query": "x"}, headers={"X-API-Key": "k"})
    assert r.status_code == 400
