import pytest

from src.tenancy.context import default_graph_context, new_graph_context
from src.tenancy.registry import GraphNotFound, GraphNotReady, GraphRegistry


def _row(gid, status="ready"):
    c = new_graph_context(gid)
    return {
        "id": gid, "owner": "o", "status": status,
        "nebula_space": c.nebula_space, "nebula_partition_num": c.nebula_partition_num,
        "chunks_collection": c.chunks_collection, "er_vec_collection": c.er_vec_collection,
        "report_vec_collection": c.report_vec_collection, "pg_schema": c.pg_schema,
    }


class _Loader:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    async def __call__(self, gid):
        self.calls.append(gid)
        return self.rows.get(gid)


async def test_get_ready_graph_builds_context():
    reg = GraphRegistry(loader=_Loader({"acme": _row("acme")}))
    assert await reg.get("acme") == new_graph_context("acme")


async def test_get_caches_within_ttl_and_reloads_after():
    t = [0.0]
    loader = _Loader({"acme": _row("acme")})
    reg = GraphRegistry(loader=loader, ttl_s=30, clock=lambda: t[0])
    await reg.get("acme")
    await reg.get("acme")
    assert loader.calls == ["acme"]
    t[0] = 31
    await reg.get("acme")
    assert loader.calls == ["acme", "acme"]


async def test_missing_graph_becomes_visible_after_short_negative_ttl():
    # Live smoke 2026-10-18: a 404 probe cached "absent" for the full 30 s TTL,
    # so ingest right after provisioning finished still got 404.
    t = [0.0]
    loader = _Loader({})
    reg = GraphRegistry(loader=loader, ttl_s=30, negative_ttl_s=2, clock=lambda: t[0])
    with pytest.raises(GraphNotFound):
        await reg.get("acme")
    with pytest.raises(GraphNotFound):
        await reg.get("acme")
    assert loader.calls == ["acme"]  # typo floods still hit the cache
    loader.rows["acme"] = _row("acme")
    t[0] = 3
    assert (await reg.get("acme")).id == "acme"


async def test_not_ready_graph_turns_ready_after_short_negative_ttl():
    t = [0.0]
    loader = _Loader({"acme": _row("acme", "provisioning")})
    reg = GraphRegistry(loader=loader, ttl_s=30, negative_ttl_s=2, clock=lambda: t[0])
    with pytest.raises(GraphNotReady):
        await reg.get("acme")
    loader.rows["acme"] = _row("acme")
    t[0] = 3
    assert (await reg.get("acme")).id == "acme"


async def test_invalidate_forces_reload():
    loader = _Loader({"acme": _row("acme")})
    reg = GraphRegistry(loader=loader)
    await reg.get("acme")
    reg.invalidate("acme")
    await reg.get("acme")
    assert loader.calls == ["acme", "acme"]


async def test_unknown_graph_raises_not_found():
    reg = GraphRegistry(loader=_Loader({}))
    with pytest.raises(GraphNotFound):
        await reg.get("nope")


@pytest.mark.parametrize("status", ["provisioning", "deleting", "failed"])
async def test_non_ready_graph_raises_not_ready(status):
    reg = GraphRegistry(loader=_Loader({"acme": _row("acme", status)}))
    with pytest.raises(GraphNotReady) as ei:
        await reg.get("acme")
    assert ei.value.status == status


async def test_invalid_id_never_reaches_loader():
    loader = _Loader({})
    reg = GraphRegistry(loader=loader)
    with pytest.raises(GraphNotFound):
        await reg.get("Bad;Id")
    assert loader.calls == []


async def test_default_falls_back_to_builtin_when_row_missing():
    reg = GraphRegistry(loader=_Loader({}))
    assert await reg.get("default") == default_graph_context()


async def test_default_falls_back_to_builtin_when_loader_errors():
    async def boom(gid):
        raise OSError("pg down")
    reg = GraphRegistry(loader=boom)
    assert await reg.get("default") == default_graph_context()


async def test_non_default_loader_error_propagates():
    async def boom(gid):
        raise OSError("pg down")
    reg = GraphRegistry(loader=boom)
    with pytest.raises(OSError):
        await reg.get("acme")


class _CountingBoom:
    def __init__(self):
        self.calls = []

    async def __call__(self, gid):
        self.calls.append(gid)
        raise OSError("pg down")


async def test_default_fallback_after_loader_error_is_cached_for_ttl():
    """R-P8: a PG outage must not make every `default` request re-hit PG."""
    t = [0.0]
    loader = _CountingBoom()
    reg = GraphRegistry(loader=loader, ttl_s=30, clock=lambda: t[0])
    assert await reg.get("default") == default_graph_context()
    assert await reg.get("default") == default_graph_context()
    assert loader.calls == ["default"]
    t[0] = 31
    assert await reg.get("default") == default_graph_context()
    assert loader.calls == ["default", "default"]


async def test_default_fallback_when_row_missing_is_cached_for_ttl():
    t = [0.0]
    loader = _Loader({})
    reg = GraphRegistry(loader=loader, ttl_s=30, clock=lambda: t[0])
    await reg.get("default")
    await reg.get("default")
    assert loader.calls == ["default"]
    t[0] = 31
    await reg.get("default")
    assert loader.calls == ["default", "default"]


async def test_non_default_loader_error_is_not_cached():
    t = [0.0]
    loader = _CountingBoom()
    reg = GraphRegistry(loader=loader, ttl_s=30, clock=lambda: t[0])
    for _ in range(2):
        with pytest.raises(OSError):
            await reg.get("acme")
    assert loader.calls == ["acme", "acme"]


class _FakeCur:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        pass

    async def fetchone(self):
        return None


class _FakeConn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def cursor(self, **k):
        return _FakeCur()


class _FakePool:
    def __init__(self):
        self.kwargs = []

    def connection(self, **kwargs):
        self.kwargs.append(kwargs)
        return _FakeConn()


async def test_pg_row_loaders_use_short_pool_timeout(monkeypatch):
    """R-P8: a saturated/unreachable pool must fail fast (1 s), not block
    the request for the pool's default 30 s wait."""
    import src.storage.pg_pool as pg_pool_mod
    from src.tenancy.api_keys import _load_key_row
    from src.tenancy.registry import _load_row_from_pg

    pool = _FakePool()

    async def fake_get_pg_pool():
        return pool

    monkeypatch.setattr(pg_pool_mod, "get_pg_pool", fake_get_pg_pool)
    assert await _load_row_from_pg("default") is None
    assert await _load_key_row("abc") is None
    assert pool.kwargs == [{"timeout": 1}, {"timeout": 1}]


async def test_generation_read_from_row():
    row = _row("acme") | {"generation": 42}
    reg = GraphRegistry(loader=_Loader({"acme": row}))
    assert (await reg.get("acme")).generation == 42


def test_registry_selects_generation():
    from src.tenancy import registry

    assert "generation" in registry._COLS
