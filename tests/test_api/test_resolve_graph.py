import pytest
from fastapi import HTTPException

from src.api import graph_dep
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.context import new_graph_context
from src.tenancy.registry import GraphNotFound, GraphNotReady

ONE = ApiKeyRecord(owner="a", graph_ids=("acme",), is_admin=False)
TWO = ApiKeyRecord(owner="a", graph_ids=("acme", "acme_hr"), is_admin=False)
ADMIN = ApiKeyRecord(owner="ops", graph_ids=("default",), is_admin=True)


@pytest.mark.parametrize(
    ("key", "hdr", "expected"),
    [(ONE, None, "acme"), (ONE, "acme", "acme"), (TWO, "acme_hr", "acme_hr"), (ADMIN, None, "default"), (ADMIN, "acme", "acme")],
)
def test_choose_graph_ok(key, hdr, expected):
    assert graph_dep.choose_graph_id(key, hdr) == expected


@pytest.mark.parametrize(("key", "hdr", "code"), [(TWO, None, 400), (ONE, "other", 403), (ONE, "Bad;Id", 403)])
def test_choose_graph_errors(key, hdr, code):
    with pytest.raises(HTTPException) as ei:
        graph_dep.choose_graph_id(key, hdr)
    assert ei.value.status_code == code


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
        await graph_dep.resolve_graph(ONE, None)
    assert ei.value.status_code == 404
    monkeypatch.setattr(graph_dep, "get_graph_registry", lambda: _Reg(GraphNotReady("acme", "deleting")))
    with pytest.raises(HTTPException) as ei:
        await graph_dep.resolve_graph(ONE, None)
    assert ei.value.status_code == 409
    monkeypatch.setattr(graph_dep, "get_graph_registry", lambda: _Reg(new_graph_context("acme")))
    assert (await graph_dep.resolve_graph(ONE, None)).id == "acme"


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
