import json

import httpx
import pytest

from scripts import smoke_graph_isolation as S


async def test_wait_for_returns_first_truthy():
    calls = iter([None, None, {"status": "ready"}])

    async def probe():
        return next(calls)

    assert await S.wait_for(probe, timeout_s=5, interval_s=0) == {"status": "ready"}


async def test_wait_for_times_out():
    async def probe():
        return None

    with pytest.raises(TimeoutError):
        await S.wait_for(probe, timeout_s=0.05, interval_s=0.01)


# --- check_cross_tenant (S11): tenant A must not see tenant B's graph -------

KEY_A, KEY_B = "key-a", "key-b"
GRAPH_A, GRAPH_B = "tenant_a_graph", "tenant_b_graph"
NOT_FOUND = {"detail": "graph not found"}
UNAVAILABLE = {"detail": "graph id is not available"}


def _transport(
    *,
    list_rows: list | None = None,
    delete_status: int = 404,
    foreign_conflict: dict | None = None,
) -> httpx.MockTransport:
    """A stack where tenant A is fully isolated from graph B, unless an
    argument deliberately breaks one of the guarantees."""
    rows = [{"id": GRAPH_A, "status": "ready"}] if list_rows is None else list_rows

    def handle(request: httpx.Request) -> httpx.Response:
        key, path = request.headers.get("X-API-Key"), request.url.path
        if path == "/admin/graphs":
            if request.method == "GET":
                return httpx.Response(200, json=rows)
            gid = json.loads(request.content)["id"]
            body = foreign_conflict if gid == GRAPH_B and foreign_conflict else UNAVAILABLE
            return httpx.Response(409, json=body)
        if path == f"/admin/graphs/{GRAPH_B}":
            if request.method == "DELETE":
                return httpx.Response(delete_status, json={"id": GRAPH_B, "status": "deleting"})
            if key == KEY_B:
                return httpx.Response(200, json={"id": GRAPH_B, "status": "ready"})
            return httpx.Response(404, json=NOT_FOUND)
        if path == "/api/v1/entities":
            return httpx.Response(404, json=NOT_FOUND)
        raise AssertionError(f"unexpected request {request.method} {path}")

    return httpx.MockTransport(handle)


async def _cross_tenant(transport: httpx.MockTransport) -> None:
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as http:
        await S.check_cross_tenant(http, KEY_A, KEY_B, GRAPH_A, GRAPH_B)


async def test_cross_tenant_passes_when_isolated():
    await _cross_tenant(_transport())


async def test_cross_tenant_fails_when_foreign_graph_is_listed():
    rows = [{"id": GRAPH_A, "status": "ready"}, {"id": GRAPH_B, "status": "ready"}]
    with pytest.raises(SystemExit) as exc:
        await _cross_tenant(_transport(list_rows=rows))
    assert exc.value.code == 1


async def test_cross_tenant_fails_when_foreign_delete_is_accepted():
    with pytest.raises(SystemExit) as exc:
        await _cross_tenant(_transport(delete_status=202))
    assert exc.value.code == 1


async def test_cross_tenant_fails_when_foreign_conflict_body_differs():
    # The 409 body is the oracle guarded by spec objection 4: a conflict on
    # someone else's slug must read exactly like one on your own graph.
    with pytest.raises(SystemExit) as exc:
        await _cross_tenant(_transport(foreign_conflict={"detail": f"graph {GRAPH_B!r} is ready"}))
    assert exc.value.code == 1
