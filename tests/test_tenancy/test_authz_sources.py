"""Узкое право `sources`: управлять источниками фидера может не любой ключ."""

from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.authz import ALL_ACTIONS, Action, authorize


def _key(*, tenant="t1", scopes=("sources",), graphs=None):
    return ApiKeyRecord(owner="u", tenant_id=tenant, scopes=frozenset(scopes), graph_ids=graphs)


def test_sources_is_a_distinct_action():
    assert Action.SOURCES == "sources"
    assert "sources" in ALL_ACTIONS


def test_read_and_write_do_not_grant_sources():
    d = authorize(_key(scopes={"read", "write"}), "g", "t1", Action.SOURCES)
    assert (d.allowed, d.reason) == (False, "scope")


def test_admin_does_not_imply_sources():
    d = authorize(_key(scopes={"admin"}), "g", "t1", Action.SOURCES)
    assert (d.allowed, d.reason) == (False, "scope")


def test_key_with_sources_passes():
    assert authorize(_key(), "g", "t1", Action.SOURCES).allowed


def test_foreign_tenant_key_does_not_pass():
    d = authorize(_key(tenant="t2"), "g", "t1", Action.SOURCES)
    assert (d.allowed, d.reason) == (False, "tenant")
