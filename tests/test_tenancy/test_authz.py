"""Graph access decisions (spec 2026-10-18 §2): the five rules, in order."""

import asyncio
import inspect

import pytest
from loguru import logger

from src.config import settings
from src.tenancy import authz
from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.authz import ALL_ACTIONS, Action, Decision, authorize


def _key(*, tenant="t1", scopes=ALL_ACTIONS, graphs=None):
    return ApiKeyRecord(owner="u", tenant_id=tenant, scopes=frozenset(scopes), graph_ids=graphs)


# rights x graph x action -> (allowed, reason).  `graph_tenant=None` is a graph
# the registry does not know (or a row whose tenant could not be read).
@pytest.mark.parametrize(
    ("key", "graph_id", "graph_tenant", "action", "expected"),
    [
        # 5 — full key, own tenant, no graph narrowing
        (_key(), "acme", "t1", Action.READ, (True, "")),
        (_key(), "acme", "t1", Action.WRITE, (True, "")),
        (_key(), "acme", "t1", Action.ADMIN, (True, "")),
        (_key(), "acme", "t1", Action.DOWNLOAD_ORIGINAL, (True, "")),
        # 1 — action outside the key's scopes
        (_key(scopes={"read"}), "acme", "t1", Action.WRITE, (False, "scope")),
        (_key(scopes={"read"}), "acme", "t1", Action.ADMIN, (False, "scope")),
        # download_original is NOT implied by read (A4)
        (_key(scopes={"read"}), "acme", "t1", Action.DOWNLOAD_ORIGINAL, (False, "scope")),
        (_key(scopes=()), "acme", "t1", Action.READ, (False, "scope")),
        # 2 — graph unknown to the registry
        (_key(), "ghost", None, Action.READ, (False, "unknown")),
        # 3 — someone else's tenant
        (_key(), "acme", "t2", Action.READ, (False, "tenant")),
        (_key(), "acme", "t2", Action.ADMIN, (False, "tenant")),
        # 4 — key narrowed to specific graphs of its own tenant
        (_key(graphs=("a",)), "b", "t1", Action.READ, (False, "graph")),
        (_key(graphs=("a",)), "a", "t1", Action.READ, (True, "")),
        (_key(graphs=()), "a", "t1", Action.READ, (False, "graph")),
    ],
)
def test_decision_table(key, graph_id, graph_tenant, action, expected):
    d = authorize(key, graph_id, graph_tenant, action)
    assert (d.allowed, d.reason) == expected


def test_null_graph_ids_allows_any_graph_of_own_tenant():
    key = _key(graphs=None)
    for gid in ("acme", "beta", "default"):
        assert authorize(key, gid, "t1", Action.READ) == Decision(True, "")


def test_scope_is_checked_before_graph_existence():
    # Rule order matters: a key that may not write must not learn, from the
    # reason, whether the graph it named exists.
    d = authorize(_key(scopes={"read"}), "ghost", None, Action.WRITE)
    assert d == Decision(False, "scope")


def test_unknown_is_checked_before_tenant_and_graph():
    # Same key, same graph: with the scope in hand the missing graph wins over
    # the graph_ids narrowing.
    d = authorize(_key(graphs=("a",)), "ghost", None, Action.READ)
    assert d == Decision(False, "unknown")


def test_tenant_is_checked_before_graph_narrowing():
    d = authorize(_key(graphs=("acme",)), "acme", "t2", Action.READ)
    assert d == Decision(False, "tenant")


def test_authorize_is_sync_and_pure():
    # Deliberate deviation from the spec's `async def authorize(...)`: the
    # graph's tenant is passed in, so there is no I/O left to await.
    assert not inspect.iscoroutinefunction(authorize)
    with pytest.raises(RuntimeError):
        asyncio.get_running_loop()  # no event loop in this test
    assert isinstance(authorize(_key(), "acme", "t1", Action.READ), Decision)


def test_decision_reason_defaults_to_empty():
    assert Decision(True) == Decision(True, "")


# ── guard(): the AUTHZ_MODE switch ───────────────────────────────────
#
# Every behavioural test below pins the mode by ASSIGNING to
# `settings.authz.mode`, never with `monkeypatch.setenv`: `settings.authz` is
# a cached_property on the process-wide `settings` singleton, so once anything
# has touched it the env is no longer read.  Pinning also keeps these outcomes
# independent of an ambient AUTHZ_MODE — the suite is accepted both with the
# variable unset and with AUTHZ_MODE=enforce exported.


@pytest.fixture
def log_lines():
    """Collect loguru messages emitted inside the test."""
    records: list[str] = []
    sink_id = logger.add(records.append, format="{message}", level="WARNING")
    yield records
    logger.remove(sink_id)


def _pin(monkeypatch, mode):
    monkeypatch.setattr(settings.authz, "mode", mode)


def test_mode_off_skips_decision(monkeypatch, log_lines):
    # `off` is the emergency switch: it must not even consult the rules.
    def _boom(*a, **kw):
        raise AssertionError("authorize() must not be called in off mode")

    _pin(monkeypatch, "off")
    monkeypatch.setattr(authz, "authorize", _boom)
    assert authz.guard(_key(), "acme", "t2", Action.WRITE) == Decision(True)
    assert log_lines == []


def test_mode_log_allows_and_writes_line(monkeypatch, log_lines):
    _pin(monkeypatch, "log")
    d = authz.guard(_key(), "acme", "t2", Action.WRITE)
    assert d == Decision(True)
    # The line format is the contract for the 24-hour review window.
    assert [line.strip() for line in log_lines] == [
        "authz would-deny key_owner=u tenant=t1 graph=acme action=write reason=tenant"
    ]


def test_mode_log_allows_silently_when_authorized(monkeypatch, log_lines):
    _pin(monkeypatch, "log")
    assert authz.guard(_key(), "acme", "t1", Action.WRITE) == Decision(True)
    assert log_lines == []


def test_mode_enforce_denies(monkeypatch, log_lines):
    _pin(monkeypatch, "enforce")
    assert authz.guard(_key(), "acme", "t2", Action.WRITE) == Decision(False, "tenant")
    assert [line.strip() for line in log_lines] == [
        "authz deny key_owner=u tenant=t1 graph=acme action=write reason=tenant"
    ]


def test_mode_enforce_allows_authorized(monkeypatch, log_lines):
    _pin(monkeypatch, "enforce")
    assert authz.guard(_key(graphs=("acme",)), "acme", "t1", Action.READ) == Decision(True)
    assert log_lines == []


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("off", None), ("log", None), ("enforce", "t1")],
)
def test_tenant_filter_only_in_enforce(monkeypatch, mode, expected):
    # Repository-level filters hang off the SAME switch, so `off` really does
    # restore today's behaviour (unfiltered list, DELETE of a foreign graph)
    # and `log` really does leave external behaviour unchanged.
    _pin(monkeypatch, mode)
    assert authz.tenant_filter(_key()) == expected


def test_mode_is_read_on_every_call(monkeypatch):
    # No module-level caching of the mode: flipping the setting mid-process
    # must take effect immediately (that is what makes `off` a kill switch).
    _pin(monkeypatch, "enforce")
    assert authz.guard(_key(), "acme", "t2", Action.READ).allowed is False
    _pin(monkeypatch, "off")
    assert authz.guard(_key(), "acme", "t2", Action.READ).allowed is True
