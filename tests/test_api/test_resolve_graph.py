import pytest
from fastapi import HTTPException

from src.api import graph_dep
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.context import new_graph_context
from src.tenancy.registry import GraphNotFound, GraphNotReady

ONE = ApiKeyRecord.full("a")


# `choose_graph_id` only maps the header to an id (absent -> default); the
# access decision happens after it, in the dependency `graph_for` builds.
# It stays decision-free because MCP reuses it through `src/mcp/_shared.py`.
@pytest.mark.parametrize(
    ("hdr", "expected"),
    [
        (None, "default"),
        ("acme", "acme"),
        ("acme_hr", "acme_hr"),
        ("other", "other"),
        ("default", "default"),
    ],
)
def test_choose_graph_ok(hdr, expected):
    assert graph_dep.choose_graph_id(hdr) == expected


@pytest.mark.parametrize("hdr", ["Bad;Id", "", "UPPER", "../x"])
def test_choose_graph_invalid_slug_is_400(hdr):
    with pytest.raises(HTTPException) as ei:
        graph_dep.choose_graph_id(hdr)
    assert ei.value.status_code == 400
    assert ei.value.detail == "invalid X-Graph"


class _Reg:
    def __init__(self, result):
        self.result = result

    async def get(self, gid):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def test_resolve_graph_maps_registry_errors(monkeypatch):
    monkeypatch.setattr(graph_dep, "get_graph_registry", lambda: _Reg(GraphNotFound("acme")))
    with pytest.raises(HTTPException) as ei:
        await graph_dep.resolve_graph(ONE, "acme")
    assert ei.value.status_code == 404
    # One slug-free text for "no such graph" and "not your graph" alike.
    assert ei.value.detail == graph_dep.GRAPH_NOT_FOUND_DETAIL
    assert "acme" not in ei.value.detail
    monkeypatch.setattr(
        graph_dep, "get_graph_registry", lambda: _Reg(GraphNotReady("acme", "deleting"))
    )
    with pytest.raises(HTTPException) as ei:
        await graph_dep.resolve_graph(ONE, "acme")
    assert ei.value.status_code == 409
    # A graph of one's OWN tenant may still say why it is unusable.
    assert ei.value.detail == "graph 'acme' is deleting"
    monkeypatch.setattr(graph_dep, "get_graph_registry", lambda: _Reg(new_graph_context("acme")))
    assert (await graph_dep.resolve_graph(ONE, "acme")).id == "acme"


async def test_require_api_key_statuses(monkeypatch):
    from src.api import auth

    class _Store:
        async def lookup(self, k):
            return ONE if k == "good" else None

    monkeypatch.setattr(auth, "get_api_key_store", lambda: _Store())
    with pytest.raises(HTTPException) as ei:
        await auth.require_api_key(None)
    assert ei.value.status_code == 401
    with pytest.raises(HTTPException) as ei:
        await auth.require_api_key("bad")
    assert ei.value.status_code == 403
    assert await auth.require_api_key("good") == ONE
