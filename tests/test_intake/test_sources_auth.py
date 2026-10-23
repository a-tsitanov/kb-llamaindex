"""Шов доступа MCP фидера: право `sources` и ровно один граф."""

import pytest
from fastmcp.exceptions import ToolError

import src.intake.sources.auth as auth
import src.mcp._shared as sh
from src.config import settings
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.context import GraphContext, new_graph_context
from src.tenancy.registry import GraphNotFound
from tests.test_mcp.test_current_graph import mint_token

FEEDER = "feeder_g"


class _Reg:
    def __init__(self):
        self.calls: list[str] = []

    async def get(self, gid):
        self.calls.append(gid)
        return new_graph_context(gid)


def _key(scopes=("sources",), tenant="default", graphs=None):
    return ApiKeyRecord(
        owner="harness", tenant_id=tenant, scopes=frozenset(scopes), graph_ids=graphs,
    )


@pytest.fixture
def reg(monkeypatch):
    r = _Reg()
    monkeypatch.setattr(sh, "get_graph_registry", lambda: r)
    monkeypatch.setattr(auth, "get_http_headers", lambda **kw: {})
    return r


async def _with_token(monkeypatch, rec):
    tok = await mint_token(monkeypatch, rec)
    monkeypatch.setattr(auth, "get_access_token", lambda: tok)


async def test_no_token_is_refused(monkeypatch, reg):
    monkeypatch.setattr(auth, "get_access_token", lambda: None)
    with pytest.raises(ToolError):
        await auth.require_sources_access(FEEDER)
    assert reg.calls == []


async def test_foreign_graph_is_refused_before_the_registry(monkeypatch, reg):
    await _with_token(monkeypatch, _key())
    monkeypatch.setattr(auth, "get_http_headers", lambda **kw: {"x-graph": "other"})
    with pytest.raises(ToolError, match="foreign graph"):
        await auth.require_sources_access(FEEDER)
    assert reg.calls == []


async def test_missing_right_is_refused_even_in_log_mode(monkeypatch, reg):
    """`guard` в режиме log пропустил бы вызов; `authorize` — нет."""
    monkeypatch.setattr(settings.authz, "mode", "log")
    await _with_token(monkeypatch, _key(scopes=("read", "write")))
    with pytest.raises(ToolError, match="forbidden"):
        await auth.require_sources_access(FEEDER)


async def test_missing_right_is_refused_even_when_authz_is_off(monkeypatch, reg):
    monkeypatch.setattr(settings.authz, "mode", "off")
    await _with_token(monkeypatch, _key(scopes=("read", "write")))
    with pytest.raises(ToolError, match="forbidden"):
        await auth.require_sources_access(FEEDER)


async def test_other_tenant_answers_as_missing_graph(monkeypatch, reg):
    # Тест держится на том, что фейковый реестр отдаёт контекст арендатора
    # `default`; ключ `t2` ему чужой.  Без этого отказ был бы «нет права».
    assert (await reg.get(FEEDER)).tenant_id == "default"
    await _with_token(monkeypatch, _key(tenant="t2"))
    with pytest.raises(ToolError) as e:
        await auth.require_sources_access(FEEDER)
    assert str(e.value) == sh.GRAPH_NOT_FOUND_DETAIL


async def test_key_with_right_gets_the_feeder_context(monkeypatch, reg):
    await _with_token(monkeypatch, _key())
    ctx = await auth.require_sources_access(FEEDER)
    assert ctx.id == FEEDER
    assert reg.calls == [FEEDER]


async def test_header_naming_the_feeder_graph_is_accepted(monkeypatch, reg):
    await _with_token(monkeypatch, _key())
    monkeypatch.setattr(auth, "get_http_headers", lambda **kw: {"x-graph": FEEDER})
    assert (await auth.require_sources_access(FEEDER)).id == FEEDER


async def test_key_narrowed_to_another_graph_is_refused(monkeypatch, reg):
    await _with_token(monkeypatch, _key(graphs=("some_other",)))
    with pytest.raises(ToolError, match="forbidden"):
        await auth.require_sources_access(FEEDER)


async def test_graph_not_found_is_not_disclosed_to_unauthorized_key(monkeypatch, reg):
    """Ключ без права получает один и тот же отказ, есть граф или нет."""
    await _with_token(monkeypatch, _key(scopes=("read",)))
    with pytest.raises(ToolError) as existing:
        await auth.require_sources_access(FEEDER)

    async def missing(gid):
        raise GraphNotFound(gid)

    monkeypatch.setattr(reg, "get", missing)
    with pytest.raises(ToolError) as absent:
        await auth.require_sources_access(FEEDER)
    assert str(absent.value) == str(existing.value)
    assert str(absent.value) != sh.GRAPH_NOT_FOUND_DETAIL


async def test_happy_path_returns_graph_context(monkeypatch, reg):
    await _with_token(monkeypatch, _key())
    ctx = await auth.require_sources_access(FEEDER)
    assert isinstance(ctx, GraphContext)
    assert ctx.id == FEEDER
