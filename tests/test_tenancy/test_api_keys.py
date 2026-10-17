import hashlib

import src.tenancy.api_keys as api_keys_mod
from src.tenancy.api_keys import ApiKeyRecord, ApiKeyStore, hash_api_key

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


async def test_lookup_db_row():
    async def loader(h):
        assert h == hash_api_key("secret")
        return {"owner": "acme"}
    rec = await ApiKeyStore(loader=loader).lookup("secret")
    # Authentication only: the record carries no graph binding / admin flag.
    assert rec == ApiKeyRecord(owner="acme")


async def test_legacy_env_key_is_valid(monkeypatch):
    monkeypatch.setattr(type(api_keys_mod.settings.api), "keys_list", property(lambda self: ["legacy"]))
    async def loader(h):
        return None
    rec = await ApiKeyStore(loader=loader).lookup("legacy")
    assert rec == ApiKeyRecord(owner="legacy-env")


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
    assert await store.lookup("legacy") == ApiKeyRecord(owner="legacy-env")
    assert await store.lookup("other") is None


async def test_empty_key_is_none():
    async def loader(h):
        raise AssertionError("must not query")
    assert await ApiKeyStore(loader=loader).lookup("") is None


def test_record_has_no_authorization_fields():
    # Spec amendment 2026-10-17: keys authenticate only.
    assert set(ApiKeyRecord.__dataclass_fields__) == {"owner"}


async def test_loader_query_selects_owner_only(monkeypatch):
    seen = {}

    class _Cur:
        async def execute(self, sql, params):
            seen["sql"] = sql
        async def fetchone(self):
            return {"owner": "x"}
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
    assert "graph_ids" not in seen["sql"] and "is_admin" not in seen["sql"]
    assert seen["timeout"] == 1
