"""Every route declares the action of spec §3.1 — exactly once.

The table below is a copy of the spec's "route -> action" matrix, checked
against the dependency tree FastAPI actually built, router-level
dependencies included.  Nothing here calls a handler: the subject is the
wiring, so a route that is mislabelled (or silently added without a label)
fails at collection time rather than in the first request that matters.

Why the "exactly once" part is load-bearing: FastAPI caches a dependency
per request by the identity of its callable.  Two DIFFERENT graph
dependencies on one route therefore resolve the graph twice and authorize
it twice — and a write route under a read router would hand a write-only
key a 403 from a dependency its handler never needed.
"""

from __future__ import annotations

import pytest
from fastapi.routing import APIRoute

from src.api import graph_dep
from src.api.main import app

# Spec §3.1, verbatim: method + path -> the action the route performs.
EXPECTED: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/ingest"): "write",
    ("GET", "/api/v1/ingest/{job_id}"): "read",
    # ?variant=text included: it hands out the whole document, not a snippet.
    ("GET", "/api/v1/documents/{doc_id}"): "download_original",
    ("POST", "/api/v1/search/local"): "read",
    ("POST", "/api/v1/search/global"): "read",
    ("POST", "/api/v1/search/drift"): "read",
    ("POST", "/api/v1/search/auto"): "read",
    ("POST", "/api/v1/analyze"): "read",
    ("GET", "/api/v1/entities"): "read",
    ("GET", "/api/v1/intake/stats"): "read",
    ("GET", "/api/v1/stats/messages"): "read",
    ("GET", "/api/v1/stats/timeline"): "read",
    ("POST", "/api/v1/statistics/load"): "write",
    ("POST", "/api/v1/admin/communities/rebuild"): "admin",
    ("POST", "/admin/wiki/rebuild"): "admin",
    ("POST", "/admin/monitor/sweep"): "admin",
    ("POST", "/admin/graph/stats"): "admin",
    ("POST", "/admin/graph/refresh-stats"): "admin",
    ("POST", "/admin/graph/pagerank"): "admin",
    ("POST", "/admin/graph/personalized-pagerank"): "admin",
    ("POST", "/admin/graph/components"): "admin",
    ("POST", "/admin/graph/shortest-path"): "admin",
    ("POST", "/admin/graph/materialize"): "admin",
}

# The only routes that bind no graph: liveness, and the lifecycle router,
# which operates ON graphs rather than inside one and authorizes itself
# (spec §3.3).
NO_GRAPH: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/health"),
        ("POST", "/admin/graphs"),
        ("GET", "/admin/graphs"),
        ("GET", "/admin/graphs/{graph_id}"),
        ("PATCH", "/admin/graphs/{graph_id}"),
        ("DELETE", "/admin/graphs/{graph_id}"),
    }
)

_ACTION_OF: dict[int, str] = {
    id(graph_dep.resolve_graph): "read",
    id(graph_dep.resolve_graph_write): "write",
    id(graph_dep.resolve_graph_download): "download_original",
    id(graph_dep.resolve_graph_admin): "admin",
}


def _subdependencies(dependant):
    for sub in dependant.dependencies:
        yield sub
        yield from _subdependencies(sub)


def _graph_actions(route: APIRoute) -> list[str]:
    """Graph dependencies of this route, in declaration order.

    Walks the whole tree, so a dependency declared on the router shows up
    next to one declared on the handler instead of hiding behind it.
    """
    return [
        _ACTION_OF[id(sub.call)]
        for sub in _subdependencies(route.dependant)
        if id(sub.call) in _ACTION_OF
    ]


def _wired() -> dict[tuple[str, str], list[str]]:
    out: dict[tuple[str, str], list[str]] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue  # /docs, /openapi.json and friends
        for method in route.methods:
            if method in ("HEAD", "OPTIONS"):
                continue
            out[(method, route.path)] = _graph_actions(route)
    return out


WIRED = _wired()


@pytest.mark.parametrize(("endpoint", "actions"), sorted(WIRED.items()))
def test_route_declares_its_spec_action_once(endpoint, actions):
    if endpoint in NO_GRAPH:
        assert actions == [], f"{endpoint} is not supposed to bind a graph"
        return
    assert endpoint in EXPECTED, f"{endpoint} is new — give it a row in the spec §3.1 table"
    assert actions == [EXPECTED[endpoint]], endpoint


def test_table_covers_exactly_the_routes_that_exist():
    # Catches the other direction: a route renamed or dropped leaves a row
    # here that nothing checks any more.
    assert set(EXPECTED) | NO_GRAPH == set(WIRED)


def test_no_route_resolves_the_graph_twice():
    # The regression this guards: `stats` and `statistics` used to carry a
    # router-level `Depends(resolve_graph)` on top of the per-handler one.
    doubled = {endpoint: acts for endpoint, acts in WIRED.items() if len(acts) > 1}
    assert doubled == {}


def test_no_data_route_is_left_without_a_graph():
    unbound = {endpoint for endpoint, acts in WIRED.items() if not acts} - NO_GRAPH
    assert unbound == set()
