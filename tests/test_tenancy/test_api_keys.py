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
        return {"owner": "acme", "graph_ids": ["acme", "acme_hr"], "is_admin": False}
    rec = await ApiKeyStore(loader=loader).lookup("secret")
    assert rec == ApiKeyRecord(owner="acme", graph_ids=("acme", "acme_hr"), is_admin=False)


async def test_legacy_env_key_is_default_admin(monkeypatch):
    monkeypatch.setattr(type(api_keys_mod.settings.api), "keys_list", property(lambda self: ["legacy"]))
    async def loader(h):
        return None
    rec = await ApiKeyStore(loader=loader).lookup("legacy")
    assert rec == ApiKeyRecord(owner="legacy-env", graph_ids=("default",), is_admin=True)


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
    assert await store.lookup("legacy") == ApiKeyRecord(owner="legacy-env", graph_ids=("default",), is_admin=True)
    assert await store.lookup("other") is None


async def test_empty_key_is_none():
    async def loader(h):
        raise AssertionError("must not query")
    assert await ApiKeyStore(loader=loader).lookup("") is None
