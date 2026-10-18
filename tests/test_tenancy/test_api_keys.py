import hashlib

import src.tenancy.api_keys as api_keys_mod
from src.tenancy.api_keys import ApiKeyRecord, ApiKeyStore, hash_api_key
from src.tenancy.authz import ALL_ACTIONS
from src.tenancy.context import DEFAULT_TENANT_ID

# NB: patch through `api_keys_mod.settings` (the module-level reference
# `src/tenancy/api_keys.py` actually reads), not a fresh
# `from src.config import settings`.  A sibling test elsewhere in the
# suite (tests/test_observability/test_litellm_models.py) does
# `importlib.reload(src.config)`, which rebinds `src.config.settings` to
# a new object with a new `ApiSettings` class; a fresh import after that
# would pick up the reloaded object/class, not the one this module's
# `ApiKeyStore.lookup` closes over, and a monkeypatch on the wrong class
# would silently no-op.


def test_hash_is_sha256_hex():
    assert hash_api_key("k") == hashlib.sha256(b"k").hexdigest()


async def test_lookup_maps_full_row():
    async def loader(h):
        assert h == hash_api_key("secret")
        return {"owner": "acme", "tenant_id": "t1", "scopes": ["read", "write"], "graph_ids": ["a"]}
    rec = await ApiKeyStore(loader=loader).lookup("secret")
    assert rec == ApiKeyRecord("acme", "t1", frozenset({"read", "write"}), ("a",))


async def test_pre_migration_row_is_full_rights():
    """A row with no `scopes` key = public.api_keys not migrated yet.

    This is the degradation path when the code is deployed before
    `scripts.setup_db` runs (mcp-* services, offline cluster): the key keeps
    today's full rights instead of being locked out.
    """
    async def loader(h):
        return {"owner": "acme"}
    assert await ApiKeyStore(loader=loader).lookup("secret") == ApiKeyRecord.full("acme")


async def test_empty_scopes_is_powerless():
    # Present-but-empty is a real (rightless) key, unlike an absent column.
    async def loader(h):
        return {"owner": "acme", "tenant_id": "t1", "scopes": [], "graph_ids": None}
    rec = await ApiKeyStore(loader=loader).lookup("secret")
    assert rec.scopes == frozenset()


async def test_null_graph_ids_means_all():
    async def loader(h):
        return {"owner": "acme", "tenant_id": "t1", "scopes": ["read"], "graph_ids": None}
    rec = await ApiKeyStore(loader=loader).lookup("secret")
    assert rec.graph_ids is None


async def test_legacy_env_key_is_full_rights_in_default_tenant(monkeypatch):
    monkeypatch.setattr(type(api_keys_mod.settings.api), "keys_list", property(lambda self: ["legacy"]))
    async def loader(h):
        return None
    rec = await ApiKeyStore(loader=loader).lookup("legacy")
    assert rec == ApiKeyRecord.full("legacy-env")
    assert (rec.tenant_id, rec.scopes, rec.graph_ids) == (DEFAULT_TENANT_ID, ALL_ACTIONS, None)


async def test_unknown_key_is_none(monkeypatch):
    monkeypatch.setattr(type(api_keys_mod.settings.api), "keys_list", property(lambda self: []))
    async def loader(h):
        return None
    assert await ApiKeyStore(loader=loader).lookup("nope") is None


async def test_loader_error_falls_back_to_env_keys(monkeypatch):
    # public.api_keys missing (code deployed before setup_db) must not 500 every request
    monkeypatch.setattr(type(api_keys_mod.settings.api), "keys_list", property(lambda self: ["legacy"]))
    async def boom(h):
        raise RuntimeError('relation "public.api_keys" does not exist')
    store = ApiKeyStore(loader=boom)
    assert await store.lookup("legacy") == ApiKeyRecord.full("legacy-env")
    assert await store.lookup("other") is None


async def test_empty_key_is_none():
    async def loader(h):
        raise AssertionError("must not query")
    assert await ApiKeyStore(loader=loader).lookup("") is None


def test_record_carries_tenant_scopes_graphs():
    # Spec 2026-10-18 §1: the key carries its rights, not just its identity.
    assert set(ApiKeyRecord.__dataclass_fields__) == {"owner", "tenant_id", "scopes", "graph_ids"}


async def test_loader_query_is_schema_agnostic(monkeypatch):
    seen = {}

    class _Cur:
        async def execute(self, sql, params):
            seen["sql"] = sql
        async def fetchone(self):
            return {"j": {"owner": "x"}}
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False

    class _Conn:
        def cursor(self, row_factory=None):
            return _Cur()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False

    class _Pool:
        def connection(self, timeout=None):
            seen["timeout"] = timeout
            return _Conn()

    async def _get_pool():
        return _Pool()

    import src.storage.pg_pool as pg_pool
    monkeypatch.setattr(pg_pool, "get_pg_pool", _get_pool)
    assert await api_keys_mod._load_key_row("h") == {"owner": "x"}
    assert "to_jsonb" in seen["sql"]
    # Naming the new columns would raise UndefinedColumn on a table that
    # setup_db has not migrated yet and drop EVERY db key into the env
    # fallback (403 per key, cached 30 s).  Do not "fix" this back.
    for col in ("scopes", "graph_ids", "tenant_id", "is_admin"):
        assert col not in seen["sql"]
    assert seen["timeout"] == 1
