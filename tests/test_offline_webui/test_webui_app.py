"""Offline-cluster web UI (deploy/offline/webui/app.py) against a mocked KB API.

The app reads its env at import time, so it is loaded from its file path with
the env set; upstream calls go through an ``httpx.MockTransport``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest

APP = Path(__file__).resolve().parents[2] / "deploy/offline/webui/app.py"
_RealClient = httpx.AsyncClient


@pytest.fixture
def webui(monkeypatch):
    monkeypatch.setenv("KB_API_URL", "http://kb")
    monkeypatch.setenv("KB_API_KEY", "k")
    monkeypatch.setenv("DOCS2MD_URL", "http://d2m")
    spec = importlib.util.spec_from_file_location("offline_webui_app", APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    seen: list[httpx.Request] = []

    def route(handler):
        def wrapped(req: httpx.Request) -> httpx.Response:
            seen.append(req)
            return handler(req)

        monkeypatch.setattr(
            mod.httpx, "AsyncClient",
            lambda *a, **kw: _RealClient(*a, transport=httpx.MockTransport(wrapped), **kw),
        )

    return mod, route, seen


def _client(mod):
    return _RealClient(transport=httpx.ASGITransport(app=mod.app), base_url="http://ui")


@pytest.mark.asyncio
async def test_documents_streams_binary_with_headers(webui):
    mod, route, seen = webui
    body = bytes(range(256)) * 4  # not valid UTF-8: must survive byte-exact
    cd = "attachment; filename=\"r.docx\"; filename*=UTF-8''r.docx"
    ct = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    route(lambda req: httpx.Response(
        200, content=body, headers={"content-type": ct, "content-disposition": cd}))
    async with _client(mod) as c:
        r = await c.get("/api/documents/abc?variant=original")
    assert r.status_code == 200
    assert r.content == body
    assert r.headers["content-type"] == ct
    assert r.headers["content-disposition"] == cd
    assert seen[0].url.path == "/api/v1/documents/abc"
    assert seen[0].url.params["variant"] == "original"
    assert seen[0].headers["x-api-key"] == "k"


@pytest.mark.asyncio
async def test_documents_without_variant_forwards_none(webui):
    mod, route, seen = webui
    route(lambda req: httpx.Response(200, content=b"x", headers={"content-type": "text/plain"}))
    async with _client(mod) as c:
        await c.get("/api/documents/abc")
    assert "variant" not in seen[0].url.params


@pytest.mark.asyncio
async def test_documents_relays_upstream_404(webui):
    mod, route, _ = webui
    route(lambda req: httpx.Response(404, json={"detail": "original file not available"}))
    async with _client(mod) as c:
        r = await c.get("/api/documents/abc?variant=original")
    assert r.status_code == 404
    assert r.json()["detail"] == "original file not available"


@pytest.mark.asyncio
async def test_ingest_forwards_original(webui):
    mod, route, seen = webui
    route(lambda req: httpx.Response(202, json={"job_id": "j1"}))
    async with _client(mod) as c:
        r = await c.post(
            "/api/ingest",
            data={"markdown": "# hi", "filename": "Отчёт.docx"},
            files={"original": ("Отчёт.docx", b"PK\x03\x04docx", "application/octet-stream")},
        )
    assert r.status_code == 202, r.text
    sent = seen[0].read()
    assert b'name="file"' in sent and b"# hi" in sent
    assert b'name="original"' in sent and b"PK\x03\x04docx" in sent


@pytest.mark.asyncio
async def test_ingest_without_original(webui):
    mod, route, seen = webui
    route(lambda req: httpx.Response(202, json={"job_id": "j1"}))
    async with _client(mod) as c:
        r = await c.post("/api/ingest", data={"markdown": "# hi", "filename": "a.md"})
    assert r.status_code == 202, r.text
    assert b'name="original"' not in seen[0].read()
