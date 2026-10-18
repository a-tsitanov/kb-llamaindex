from pathlib import Path

import httpx
import pytest

from scripts import tg_ingest


def test_client_headers():
    assert tg_ingest.client_headers(None) == {}
    assert tg_ingest.client_headers("") == {}
    assert tg_ingest.client_headers("acme") == {"X-Graph": "acme"}


def test_client_headers_rejects_bad_slug():
    with pytest.raises(ValueError):
        tg_ingest.client_headers("Bad;Id")


async def test_post_ingest_inherits_client_graph_header():
    seen = {}

    def handler(request):
        seen.update(request.headers)
        return httpx.Response(202, json={"job_id": "00000000-0000-0000-0000-000000000000"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers=tg_ingest.client_headers("acme"),
    ) as http:
        ok = await tg_ingest.post_ingest(http, "http://x", "k", "f.txt", "t", "2026-10-18", None)
    assert ok and seen["x-graph"] == "acme" and seen["x-api-key"] == "k"


def test_scoped_state_path_default_graph_keeps_path():
    for graph in (None, "", "default"):
        assert tg_ingest.scoped_state_path("/data/tg_ingest.state.json", graph) == Path(
            "/data/tg_ingest.state.json"
        )


def test_scoped_state_path_per_graph():
    # Cursors advanced while feeding `default` must not be resumed for acme.
    assert tg_ingest.scoped_state_path("/data/tg_ingest.state.json", "acme") == Path(
        "/data/tg_ingest.state.acme.json"
    )


def test_scoped_state_path_rejects_bad_slug():
    with pytest.raises(ValueError):
        tg_ingest.scoped_state_path("s.json", "../x")
