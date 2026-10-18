"""Tenant isolation of the graph lifecycle admin routes (plan S8).

Every test PINS the mode by assigning ``settings.authz.mode``: the setting is
a cached_property on the process-wide singleton, so ``monkeypatch.setenv``
would be a no-op, and pinning is also what makes these outcomes independent
of an ambient ``AUTHZ_MODE``.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from loguru import logger

from src.api.auth import require_api_key
from src.api.routes import graphs_admin
from src.config import settings
from src.tenancy import graph_repo
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.authz import ALL_ACTIONS

MINE = {"id": "mine", "status": "ready", "tenant_id": "t1"}
THEIRS = {"id": "theirs", "status": "ready", "tenant_id": "t2"}

KEY = ApiKeyRecord(owner="u", tenant_id="t1", scopes=ALL_ACTIONS, graph_ids=None)
NO_ADMIN = ApiKeyRecord(
    owner="r", tenant_id="t1", scopes=frozenset({"read", "write"}), graph_ids=None
)


class _Handle:
    def __init__(self, wid: str) -> None:
        self.id = wid


@pytest.fixture
def env(monkeypatch):
    """The whole admin router with every repository call recorded."""
    state: dict = {
        "key": KEY,
        "rows": {"mine": dict(MINE), "theirs": dict(THEIRS)},
        "outcome": graph_repo.CreateOutcome("created", "provisioning"),
        "created": [],
        "listed": [],
        "patched": [],
        "marked": [],
        "started": [],
    }

    class _Client:
        async def start_workflow(self, run, arg, *, id, task_queue, **kw):
            state["started"].append(id)
            return _Handle(id)

    async def _client():
        return _Client()

    async def create_or_resume(gid, owner, n, **kw):
        state["created"].append((gid, kw.get("tenant_id"), kw.get("tenant_filter")))
        return state["outcome"]

    async def get_row(gid, **kw):
        return state["rows"].get(gid)

    async def list_rows(**kw):
        tenant = kw.get("tenant_id")
        state["listed"].append(tenant)
        rows = list(state["rows"].values())
        return [r for r in rows if tenant is None or r["tenant_id"] == tenant]

    async def patch_row(gid, **kw):
        state["patched"].append((gid, kw.get("tenant_id")))
        return state["rows"].get(gid)

    async def mark_deleting(gid, **kw):
        state["marked"].append((gid, kw.get("tenant_id")))
        row = state["rows"].get(gid)
        if row is None or (kw.get("tenant_id") not in (None, row["tenant_id"])):
            return None
        return row["status"]

    async def set_status(gid, status, error="", **kw):
        return None

    monkeypatch.setattr(graphs_admin, "get_temporal_client", _client)
    monkeypatch.setattr(graphs_admin.graph_repo, "create_or_resume", create_or_resume)
    monkeypatch.setattr(graphs_admin.graph_repo, "get_row", get_row)
    monkeypatch.setattr(graphs_admin.graph_repo, "list_rows", list_rows)
    monkeypatch.setattr(graphs_admin.graph_repo, "patch_row", patch_row)
    monkeypatch.setattr(graphs_admin.graph_repo, "mark_deleting", mark_deleting)
    monkeypatch.setattr(graphs_admin.graph_repo, "set_status", set_status)
    app = FastAPI()
    app.include_router(graphs_admin.router)
    app.dependency_overrides[require_api_key] = lambda: state["key"]
    state["http"] = TestClient(app)
    state["mode"] = lambda m: monkeypatch.setattr(settings.authz, "mode", m)
    return state


@pytest.fixture
def enforce(env):
    env["mode"]("enforce")
    return env


@pytest.fixture
def log_lines():
    records: list[str] = []
    sink_id = logger.add(records.append, format="{message}", level="WARNING")
    yield records
    logger.remove(sink_id)


# --- enforce ---------------------------------------------------------------


def test_list_is_filtered_by_tenant(enforce):
    r = enforce["http"].get("/admin/graphs")
    assert r.status_code == 200
    assert [row["id"] for row in r.json()] == ["mine"]
    assert enforce["listed"] == ["t1"]


def test_get_foreign_graph_is_indistinguishable_from_missing(enforce):
    foreign = enforce["http"].get("/admin/graphs/theirs")
    ghost = enforce["http"].get("/admin/graphs/ghost")
    assert foreign.status_code == ghost.status_code == 404
    assert foreign.content == ghost.content
    assert "theirs" not in foreign.text


def test_get_own_graph_passes(enforce):
    r = enforce["http"].get("/admin/graphs/mine")
    assert r.status_code == 200 and r.json()["id"] == "mine"


def test_patch_foreign_graph_is_404_and_writes_nothing(enforce):
    r = enforce["http"].patch("/admin/graphs/theirs", json={"owner": "hijack"})
    assert r.status_code == 404 and enforce["patched"] == []


def test_patch_own_graph_passes_the_tenant_filter(enforce):
    r = enforce["http"].patch("/admin/graphs/mine", json={"owner": "new"})
    assert r.status_code == 200 and enforce["patched"] == [("mine", "t1")]


def test_delete_foreign_graph_is_404_before_anything_happens(enforce):
    r = enforce["http"].delete("/admin/graphs/theirs?confirm=theirs")
    assert r.status_code == 404
    assert enforce["marked"] == [] and enforce["started"] == []


def test_delete_own_graph_passes_the_tenant_filter(enforce):
    r = enforce["http"].delete("/admin/graphs/mine?confirm=mine")
    assert r.status_code == 202
    assert enforce["marked"] == [("mine", "t1")] and enforce["started"] == ["lifecycle-delete-mine"]


def test_post_takes_the_tenant_from_the_key_not_the_body(enforce):
    r = enforce["http"].post(
        "/admin/graphs", json={"id": "acme", "owner": "team", "tenant_id": "t2"}
    )
    assert r.status_code == 202
    assert enforce["created"] == [("acme", "t1", "t1")]


@pytest.mark.parametrize("status", ["ready", "unavailable"])
def test_post_conflict_body_is_opaque(enforce, status):
    enforce["outcome"] = graph_repo.CreateOutcome("conflict", status)
    r = enforce["http"].post("/admin/graphs", json={"id": "acme", "owner": "t"})
    assert r.status_code == 409 and r.json()["detail"] == "graph id is not available"
    assert status not in r.text and enforce["started"] == []


def test_post_conflict_is_byte_identical_for_own_and_foreign_slug(enforce):
    enforce["outcome"] = graph_repo.CreateOutcome("conflict", "ready")
    own = enforce["http"].post("/admin/graphs", json={"id": "acme", "owner": "t"})
    enforce["outcome"] = graph_repo.CreateOutcome("conflict", "unavailable")
    foreign = enforce["http"].post("/admin/graphs", json={"id": "acme", "owner": "t"})
    assert own.status_code == foreign.status_code == 409
    assert own.content == foreign.content


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("post", "/admin/graphs", {"json": {"id": "acme", "owner": "t"}}),
        ("get", "/admin/graphs", {}),
        ("get", "/admin/graphs/mine", {}),
        ("patch", "/admin/graphs/mine", {"json": {"owner": "x"}}),
        ("delete", "/admin/graphs/mine?confirm=mine", {}),
    ],
)
def test_key_without_admin_scope_is_403_everywhere(enforce, method, path, kwargs):
    enforce["key"] = NO_ADMIN
    r = getattr(enforce["http"], method)(path, **kwargs)
    assert r.status_code == 403 and r.json()["detail"].endswith("not allowed for this key")
    assert enforce["started"] == [] and enforce["marked"] == []


def test_narrowed_key_may_still_list_its_tenant(enforce):
    # A narrowing to graph ids has no single graph to apply to on a
    # collection; the rows are still cut down to the key's tenant.
    enforce["key"] = ApiKeyRecord(
        owner="n", tenant_id="t1", scopes=ALL_ACTIONS, graph_ids=("other",)
    )
    r = enforce["http"].get("/admin/graphs")
    assert r.status_code == 200 and enforce["listed"] == ["t1"]


def test_narrowed_key_may_not_touch_a_graph_outside_the_narrowing(enforce):
    enforce["key"] = ApiKeyRecord(
        owner="n", tenant_id="t1", scopes=ALL_ACTIONS, graph_ids=("other",)
    )
    assert enforce["http"].get("/admin/graphs/mine").status_code == 403


# --- off: the emergency lever, repository filters included -----------------


def test_mode_off_lists_all_tenants(env):
    env["mode"]("off")
    r = env["http"].get("/admin/graphs")
    assert {row["id"] for row in r.json()} == {"mine", "theirs"}
    assert env["listed"] == [None]


def test_mode_off_deletes_foreign_graph(env):
    env["mode"]("off")
    r = env["http"].delete("/admin/graphs/theirs?confirm=theirs")
    assert r.status_code == 202
    assert env["marked"] == [("theirs", None)]


def test_mode_off_is_silent(env, log_lines):
    env["mode"]("off")
    env["http"].get("/admin/graphs")
    assert [line for line in log_lines if "authz" in line] == []


# --- log: today's behaviour plus one line ----------------------------------


def test_mode_log_does_not_filter_but_reports(env, log_lines):
    env["mode"]("log")
    r = env["http"].get("/admin/graphs")
    assert {row["id"] for row in r.json()} == {"mine", "theirs"}
    assert env["listed"] == [None]
    assert [line for line in log_lines if "would-deny list" in line and "foreign_rows=1" in line]


def test_mode_log_lets_a_foreign_graph_through(env, log_lines):
    env["mode"]("log")
    assert env["http"].get("/admin/graphs/theirs").status_code == 200
    assert [line for line in log_lines if "would-deny" in line and "reason=tenant" in line]
