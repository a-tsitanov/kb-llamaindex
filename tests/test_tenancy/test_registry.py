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
