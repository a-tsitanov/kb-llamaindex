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


# ── привязка фидерного ключа к своему графу ──────────────────────────
#
# Ключ, сужённый до ОДНОГО графа, без заголовка попадал бы на `default`,
# которого нет в его списке, и получал бы отказ на ровном месте.  Поэтому
# единственный граф ключа и есть его умолчание.  Правило живёт здесь, а не
# в зависимости, потому что тот же выбор делает шов MCP.


def _narrow(*graphs: str) -> ApiKeyRecord:
    return ApiKeyRecord(
        owner="feeder", tenant_id="default",
        scopes=frozenset({"write"}), graph_ids=tuple(graphs),
    )


def test_single_graph_key_without_header_binds_to_its_graph():
    assert graph_dep.choose_graph_id(None, _narrow("acme")) == "acme"


def test_multi_graph_key_without_header_stays_on_default():
    """Два графа — выбирать за клиента нечего, подстановка была бы догадкой."""
    assert graph_dep.choose_graph_id(None, _narrow("acme", "beta")) == "default"


def test_unnarrowed_key_without_header_stays_on_default():
    assert graph_dep.choose_graph_id(None, ApiKeyRecord.full("a")) == "default"


def test_explicit_header_always_wins():
    """Привязка — умолчание, а не ограничение: названный граф не подменяется.

    Отказ по чужому графу остаётся работой `authorize`, иначе 404 и 403
    перестали бы различаться на этом шве.
    """
    assert graph_dep.choose_graph_id("beta", _narrow("acme")) == "beta"


def test_key_is_optional():
    """Старые вызовы без ключа работают как раньше."""
    assert graph_dep.choose_graph_id(None) == "default"


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
