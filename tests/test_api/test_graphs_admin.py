import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.auth import require_api_key
from src.api.routes import graphs_admin
from src.tenancy import graph_repo
from src.tenancy.api_keys import ApiKeyRecord


class _Client:
    def __init__(self, fail=False):
        self.started, self.fail = [], fail

    async def start_workflow(self, run, arg, *, id, task_queue, **kw):
        if self.fail:
            raise RuntimeError("temporal down")
        self.started.append((id, arg.graph_id))

        class _H:
            pass

        h = _H()
        h.id = id
        return h


@pytest.fixture
def ctx(monkeypatch):
    state = {
        "client": _Client(),
        "outcome": graph_repo.CreateOutcome("created", "provisioning"),
        "row": None,
        "prev": "ready",
        "statuses": [],
    }

    async def _client():
        return state["client"]

    async def create(gid, owner, n, **kw):
        if gid in ("default", "Bad"):
            from src.tenancy.context import InvalidGraphId

            raise InvalidGraphId(gid)
        return state["outcome"]

    async def get_row(gid, **kw):
        return state["row"]

    async def mark_deleting(gid, **kw):
        return state["prev"]

    async def set_status(gid, status, error="", **kw):
        state["statuses"].append((gid, status))
        state.setdefault("expects", []).append(kw.get("expect"))

    monkeypatch.setattr(graphs_admin, "get_temporal_client", _client)
    monkeypatch.setattr(graphs_admin.graph_repo, "create_or_resume", create)
    monkeypatch.setattr(graphs_admin.graph_repo, "get_row", get_row)
    monkeypatch.setattr(graphs_admin.graph_repo, "mark_deleting", mark_deleting)
    monkeypatch.setattr(graphs_admin.graph_repo, "set_status", set_status)
    app = FastAPI()
    app.include_router(graphs_admin.router)
    app.dependency_overrides[require_api_key] = lambda: ApiKeyRecord(owner="t")
    state["http"] = TestClient(app)
    return state


def test_post_creates_and_starts_workflow(ctx):
    r = ctx["http"].post("/admin/graphs", json={"id": "acme", "owner": "team"})
    assert r.status_code == 202
    assert r.json() == {
        "id": "acme",
        "status": "provisioning",
        "workflow_id": "lifecycle-provision-acme",
    }
    assert ctx["client"].started == [("lifecycle-provision-acme", "acme")]


def test_post_resume_failed_starts_again(ctx):
    ctx["outcome"] = graph_repo.CreateOutcome("resumed", "provisioning")
    assert ctx["http"].post("/admin/graphs", json={"id": "acme", "owner": "t"}).status_code == 202


@pytest.mark.parametrize("status", ["ready", "provisioning", "deleting"])
def test_post_existing_ready_is_409(ctx, status):
    ctx["outcome"] = graph_repo.CreateOutcome("conflict", status)
    r = ctx["http"].post("/admin/graphs", json={"id": "acme", "owner": "t"})
    assert r.status_code == 409 and status in r.json()["detail"]
    assert ctx["client"].started == []


@pytest.mark.parametrize("gid", ["default", "Bad"])
def test_post_invalid_id_400(ctx, gid):
    assert ctx["http"].post("/admin/graphs", json={"id": gid, "owner": "t"}).status_code == 400


def test_post_workflow_start_failure_marks_failed(ctx):
    ctx["client"] = _Client(fail=True)
    r = ctx["http"].post("/admin/graphs", json={"id": "acme", "owner": "t"})
    assert r.status_code == 500
    assert ctx["statuses"] == [("acme", "failed")]
    assert ctx["expects"] == ["provisioning"]


def test_get_unknown_404(ctx):
    assert ctx["http"].get("/admin/graphs/acme").status_code == 404


def test_delete_guards(ctx):
    http = ctx["http"]
    assert http.delete("/admin/graphs/default?confirm=default").status_code == 409
    assert http.delete("/admin/graphs/acme?confirm=acmee").status_code == 400
    assert http.delete("/admin/graphs/acme").status_code == 422  # confirm required
    ctx["prev"] = None
    assert http.delete("/admin/graphs/acme?confirm=acme").status_code == 404
    assert ctx["client"].started == []


def test_delete_provisioning_is_409(ctx):
    ctx["row"] = {"id": "acme", "status": "provisioning"}
    ctx["prev"] = "provisioning"
    r = ctx["http"].delete("/admin/graphs/acme?confirm=acme")
    assert r.status_code == 409


def test_delete_racing_resume_is_409(ctx):
    # A pre-read saw `failed`, but a concurrent POST resumed the row to
    # `provisioning`; the atomic mark_deleting reports it and nothing starts.
    ctx["row"] = {"id": "acme", "status": "failed"}
    ctx["prev"] = "provisioning"
    r = ctx["http"].delete("/admin/graphs/acme?confirm=acme")
    assert r.status_code == 409
    assert ctx["client"].started == []


def test_delete_start_failure_marks_failed_only_from_deleting(ctx):
    ctx["client"] = _Client(fail=True)
    r = ctx["http"].delete("/admin/graphs/acme?confirm=acme")
    assert r.status_code == 500
    assert ctx["statuses"] == [("acme", "failed")] and ctx["expects"] == ["deleting"]


def test_delete_starts_workflow(ctx):
    ctx["row"] = {"id": "acme", "status": "ready"}
    r = ctx["http"].delete("/admin/graphs/acme?confirm=acme")
    assert r.status_code == 202
    assert r.json()["workflow_id"] == "lifecycle-delete-acme"
    assert ctx["client"].started == [("lifecycle-delete-acme", "acme")]
