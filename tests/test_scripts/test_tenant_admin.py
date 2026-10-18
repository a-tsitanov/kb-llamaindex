"""`scripts/tenant_admin.py` — the only way a tenant or a key is created.

No database: the command core takes a ``conn_factory``, and the fakes below
record every statement, the way ``tests/test_tenancy/test_graph_repo.py``
does for the async repository.  What is actually under test is the handling
of the raw key (printed once, never stored, never logged) and the refusal of
rights nobody can grant.
"""

from __future__ import annotations

import pytest

from scripts import tenant_admin
from src.tenancy.api_keys import hash_api_key
from src.tenancy.authz import ALL_ACTIONS


class _Cur:
    def __init__(self, results=()):
        self.results, self.sql = list(results), []

    def execute(self, q, params=None):
        self.sql.append((str(q), params))

    def fetchone(self):
        return self.results.pop(0) if self.results else None

    def fetchall(self):
        return self.results.pop(0) if self.results else []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _run(argv, results=()):
    """Drive the CLI end to end (argparse included) against a fake cursor."""
    cur = _Cur(results)
    rc = tenant_admin.run(tenant_admin._parse_args(argv), conn_factory=lambda: _Conn(cur))
    return rc, cur


def _stmts(cur, needle):
    return [(s, p) for s, p in cur.sql if needle in s]


# ── create ───────────────────────────────────────────────────────────


def test_create_inserts_the_tenant_idempotently(capsys):
    rc, cur = _run(["create", "--id", "acme", "--name", "ACME Inc"], results=[("acme",)])
    assert rc == 0
    ((sql, params),) = _stmts(cur, "INSERT INTO public.tenants")
    assert "ON CONFLICT (id) DO NOTHING" in sql
    assert params == ("acme", "ACME Inc")
    assert "created" in capsys.readouterr().out


def test_create_says_so_when_the_tenant_was_already_there(capsys):
    """`ON CONFLICT DO NOTHING` returns no row — a repeat run is not an error."""
    rc, _ = _run(["create", "--id", "acme", "--name", "ACME Inc"], results=[])
    assert rc == 0
    assert "exists" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["ACME", "1acme", "a", "acme-inc", "acme inc", "public.graphs"])
def test_create_rejects_an_invalid_slug(bad):
    """The id reaches DDL through `public.graphs`/schema names elsewhere, so
    it is validated by the same rule as a graph id — and before any SQL."""
    rc, cur = _run(["create", "--id", bad, "--name", "x"])
    assert rc != 0
    assert cur.sql == []


# ── key ──────────────────────────────────────────────────────────────


def _raw_key(capsys) -> str:
    out = capsys.readouterr().out
    # The raw key is printed on a line of its own, last.
    return out.strip().splitlines()[-1].strip(), out


def test_key_prints_the_raw_key_exactly_once_and_stores_only_its_hash(capsys):
    rc, cur = _run(["key", "--tenant", "acme", "--owner", "ci", "--scopes", "read,write"])
    assert rc == 0
    raw, out = _raw_key(capsys)
    assert out.count(raw) == 1
    ((sql, params),) = _stmts(cur, "INSERT INTO public.api_keys")
    assert "key_hash" in sql
    assert params[0] == hash_api_key(raw)
    assert params[1:4] == ("ci", "acme", ["read", "write"])


def test_key_is_long_enough_to_be_unguessable(capsys):
    _run(["key", "--tenant", "acme", "--owner", "ci", "--scopes", "read"])
    raw, _ = _raw_key(capsys)
    assert len(raw) >= 32


def test_no_statement_or_parameter_carries_the_raw_key(capsys):
    _, cur = _run(["key", "--tenant", "acme", "--owner", "ci", "--scopes", "read"])
    raw, _ = _raw_key(capsys)
    for sql, params in cur.sql:
        assert raw not in sql
        assert raw not in repr(params)


def test_key_accepts_every_known_action():
    """Drift guard: the CLI must be able to grant whatever `Action` defines."""
    scopes = ",".join(sorted(ALL_ACTIONS))
    rc, cur = _run(["key", "--tenant", "acme", "--owner", "ci", "--scopes", scopes])
    assert rc == 0
    ((_, params),) = _stmts(cur, "INSERT INTO public.api_keys")
    assert set(params[3]) == ALL_ACTIONS


def test_key_rejects_an_unknown_scope():
    rc, cur = _run(["key", "--tenant", "acme", "--owner", "ci", "--scopes", "read,bogus"])
    assert rc != 0
    assert cur.sql == []


def test_key_rejects_an_empty_scope_set():
    """A rightless key is not a thing this CLI hands out by accident."""
    rc, cur = _run(["key", "--tenant", "acme", "--owner", "ci", "--scopes", ""])
    assert rc != 0
    assert cur.sql == []


def test_key_rejects_an_invalid_tenant_slug():
    rc, cur = _run(["key", "--tenant", "ACME", "--owner", "ci", "--scopes", "read"])
    assert rc != 0
    assert cur.sql == []


def test_key_narrowed_to_named_graphs_stores_the_list():
    rc, cur = _run(
        ["key", "--tenant", "acme", "--owner", "ci", "--scopes", "read", "--graphs", "a_one,b_two"]
    )
    assert rc == 0
    ((_, params),) = _stmts(cur, "INSERT INTO public.api_keys")
    assert params[4] == ["a_one", "b_two"]


def test_key_without_the_graph_flag_is_every_graph_of_the_tenant():
    """NULL, not an empty array: `graph_ids IS NULL` is what
    `ApiKeyRecord.graph_ids is None` means."""
    _, cur = _run(["key", "--tenant", "acme", "--owner", "ci", "--scopes", "read"])
    ((_, params),) = _stmts(cur, "INSERT INTO public.api_keys")
    assert params[4] is None


def test_key_rejects_an_invalid_graph_in_the_narrowing():
    rc, cur = _run(
        ["key", "--tenant", "acme", "--owner", "ci", "--scopes", "read", "--graphs", "a_one,B!"]
    )
    assert rc != 0
    assert cur.sql == []


# ── revoke ───────────────────────────────────────────────────────────


def test_revoke_deletes_the_row_by_hash(capsys):
    h = hash_api_key("whatever")
    rc, cur = _run(["revoke", "--key-hash", h], results=[("ci",)])
    assert rc == 0
    ((sql, params),) = _stmts(cur, "DELETE FROM public.api_keys")
    assert "WHERE key_hash = %s" in sql
    assert params == (h,)
    assert "ci" in capsys.readouterr().out


def test_revoke_reports_a_hash_that_matched_nothing(capsys):
    rc, _ = _run(["revoke", "--key-hash", "deadbeef"], results=[])
    assert rc != 0
    assert "no key" in capsys.readouterr().out.lower()


# ── list ─────────────────────────────────────────────────────────────


def test_list_reads_the_three_tables_and_prints_no_raw_key(capsys):
    h = hash_api_key("whatever")
    rc, cur = _run(
        ["list"],
        results=[
            [("acme", "ACME Inc")],
            [("acme", "a_one", "ready")],
            [("acme", "ci", h, ["read", "write"], None)],
        ],
    )
    assert rc == 0
    for table in ("public.tenants", "public.graphs", "public.api_keys"):
        assert _stmts(cur, table), table
    out = capsys.readouterr().out
    assert "acme" in out and "a_one" in out and "ci" in out
    assert "read,write" in out
    # Only a prefix of the hash, and never anything a caller could replay.
    assert h[:12] in out
    assert h not in out
