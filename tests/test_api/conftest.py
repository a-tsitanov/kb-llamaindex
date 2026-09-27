"""Keep API tests DB-free: no ``public.api_keys`` / ``public.graphs`` lookups.

Env ``API_KEYS`` stay valid through the legacy fallback (R-A3) and resolve to
the built-in ``default`` graph.
"""

import pytest

from src.tenancy import api_keys, registry


@pytest.fixture(autouse=True)
def _db_free_auth(monkeypatch):
    async def _none(_):
        return None

    monkeypatch.setattr(api_keys, "_load_key_row", _none)
    monkeypatch.setattr(registry, "_load_row_from_pg", _none)
    api_keys.reset_api_key_store_for_tests()
    registry.reset_graph_registry_for_tests()
    yield
    api_keys.reset_api_key_store_for_tests()
    registry.reset_graph_registry_for_tests()
