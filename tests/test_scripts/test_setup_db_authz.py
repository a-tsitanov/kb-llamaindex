"""Tenancy/authz schema and bootstrap: DDL asserted as text (like
``test_setup_db_bot.py``), bootstrap driven through a fake cursor.

Deliberate deviation from the spec §7, which names this file
``tests/test_storage/test_authz_migration.py``: it lives next to the other
``setup_db`` tests instead.
"""

from __future__ import annotations

from scripts import setup_db
from src.tenancy.authz import ALL_ACTIONS


class _Cur:
    """Fake cursor modelling just enough of `public.schema_migration` that
    the one-off migration can be run twice against the same (simulated)
    database — the repeat run is the whole point of the marker."""

    def __init__(self):
        self.sql: list[tuple[str, object]] = []
        self.markers: set[str] = set()
        self._rows: list[tuple] = []

    def execute(self, q, params=None):
        q = str(q)
        self.sql.append((q, params))
        if "public.schema_migration" not in q:
            return
        if q.lstrip().startswith("SELECT"):
            self._rows = [(1,)] if params and params[0] in self.markers else []
        elif "INSERT" in q and params:
            self.markers.add(params[0])

    def fetchall(self):
        return self._rows


# ── DDL ──────────────────────────────────────────────────────────────


def test_tenants_ddl_creates_both_global_tables():
    assert "CREATE TABLE IF NOT EXISTS public.tenants" in setup_db._TENANTS_DDL
    assert "CREATE TABLE IF NOT EXISTS public.schema_migration" in setup_db._TENANTS_DDL


def test_tenants_ddl_seeds_the_default_tenant_idempotently():
    ddl = setup_db._TENANTS_DDL
    assert "INSERT INTO public.tenants" in ddl
    assert "'default'" in ddl
    assert "ON CONFLICT (id) DO NOTHING" in ddl


def test_tenants_ddl_runs_before_the_tables_that_reference_it():
    g = setup_db.GLOBAL_DDL
    assert g.index(setup_db._TENANTS_DDL) < g.index(setup_db._GRAPHS_DDL)
    assert g.index(setup_db._TENANTS_DDL) < g.index(setup_db._API_KEYS_DDL)


def test_default_tenant_row_is_seeded_before_any_foreign_key_is_added():
    """The FK arrives by ALTER on tables that already hold rows: without the
    `default` row in place first, the ALTER fails on every existing graph
    and key.  Hence the INSERT inside the DDL block, not in bootstrap."""
    script = "\n".join(setup_db.GLOBAL_DDL)
    assert script.index("INSERT INTO public.tenants") < script.index("REFERENCES public.tenants")


def test_graphs_gain_a_tenant_column_and_index():
    ddl = setup_db._GRAPHS_DDL
    assert "ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT 'default'" in ddl
    assert "REFERENCES public.tenants(id)" in ddl
    assert "graphs_tenant_idx" in ddl


def test_api_keys_gain_authorization_columns_additively():
    """Additive only: code still running `SELECT owner` keeps working."""
    ddl = setup_db._API_KEYS_DDL
    for col in ("tenant_id", "scopes TEXT[]", "graph_ids TEXT[]"):
        assert f"ADD COLUMN IF NOT EXISTS {col}" in ddl
    assert "REFERENCES public.tenants(id)" in ddl
    assert "api_keys_tenant_idx" in ddl


def test_a_key_row_written_by_someone_else_gets_the_weakest_scope():
    assert "scopes TEXT[] NOT NULL DEFAULT '{read}'" in setup_db._API_KEYS_DDL


def test_api_keys_ddl_still_has_no_is_admin():
    # Spec 2026-10-18: `graph_ids` is back, `is_admin` is not — the `admin`
    # scope replaces it.
    assert "is_admin" not in setup_db._API_KEYS_DDL


def test_full_scopes_literal_matches_every_action():
    """Drift guard: the SQL literal is spelled out, so it has to be checked
    against `Action` rather than trusted."""
    literal = setup_db._FULL_SCOPES_SQL
    assert {a for a in ALL_ACTIONS if f"'{a}'" in literal} == ALL_ACTIONS
    assert literal.count("'") == 2 * len(ALL_ACTIONS)


# ── one-off grandfathering ───────────────────────────────────────────


def _updates(cur):
    return [s for s, _ in cur.sql if "UPDATE public.api_keys" in s]


def _marker_writes(cur):
    return [(s, p) for s, p in cur.sql if "INSERT INTO public.schema_migration" in s]


def test_grandfather_grants_every_action_when_the_marker_is_absent(monkeypatch):
    monkeypatch.setattr(setup_db.settings.api, "keys", "", raising=False)
    cur = _Cur()
    setup_db._bootstrap_registry(cur)
    (sql,) = _updates(cur)
    assert setup_db._FULL_SCOPES_SQL in sql
    assert "WHERE" not in sql  # every pre-migration row, not a subset
    ((_, params),) = _marker_writes(cur)
    assert params == (setup_db._GRANDFATHER_MARKER,)


def test_grandfather_reads_the_marker_before_it_grants(monkeypatch):
    monkeypatch.setattr(setup_db.settings.api, "keys", "", raising=False)
    cur = _Cur()
    setup_db._bootstrap_registry(cur)
    stmts = [s for s, _ in cur.sql]
    read = next(
        i
        for i, s in enumerate(stmts)
        if s.lstrip().startswith("SELECT") and "public.schema_migration" in s
    )
    assert read < stmts.index(_updates(cur)[0])


def test_grandfather_skipped_when_marker_present(monkeypatch):
    """A second setup_db run must not hand back the rights an operator
    revoked by hand in between — nothing is granted, nothing is claimed."""
    monkeypatch.setattr(setup_db.settings.api, "keys", "", raising=False)
    cur = _Cur()
    cur.markers.add(setup_db._GRANDFATHER_MARKER)
    setup_db._bootstrap_registry(cur)
    assert _updates(cur) == []
    assert _marker_writes(cur) == []


def test_grandfather_grants_once_across_two_runs(monkeypatch):
    """The same (simulated) database, twice: the marker written by the
    first run is what stops the second."""
    monkeypatch.setattr(setup_db.settings.api, "keys", "", raising=False)
    cur = _Cur()
    setup_db._bootstrap_registry(cur)
    setup_db._bootstrap_registry(cur)
    assert len(_updates(cur)) == 1
    assert len(_marker_writes(cur)) == 1


def test_marker_claim_survives_a_racing_init_container(monkeypatch):
    """Under READ COMMITTED two init containers can both pass the check.
    Both then write the same full-scope grant (harmless), so the loser must
    not abort setup_db on a duplicate marker."""
    monkeypatch.setattr(setup_db.settings.api, "keys", "", raising=False)
    cur = _Cur()
    setup_db._bootstrap_registry(cur)
    ((sql, _),) = _marker_writes(cur)
    assert "ON CONFLICT (name) DO NOTHING" in sql


def test_grandfather_is_the_first_thing_bootstrap_does(monkeypatch):
    """Before any row this run inserts — those carry their scopes already."""
    monkeypatch.setattr(setup_db.settings.api, "keys", "k1", raising=False)
    cur = _Cur()
    setup_db._bootstrap_registry(cur)
    writes = [i for i, (s, _) in enumerate(cur.sql) if "INSERT" in s or "UPDATE" in s]
    assert "UPDATE public.api_keys" in cur.sql[writes[0]][0]


# ── legacy-env keys ──────────────────────────────────────────────────


def test_legacy_env_insert_sets_tenant_and_full_scopes_explicitly(monkeypatch):
    """Leaning on the column DEFAULT '{read}' would quietly strip tg_ingest,
    the offline webui and graph_refresh.sh of ingest rights on the very next
    setup_db run."""
    monkeypatch.setattr(setup_db.settings.api, "keys", "k1", raising=False)
    cur = _Cur()
    setup_db._bootstrap_registry(cur)
    inserts = [s for s, _ in cur.sql if "INSERT INTO public.api_keys" in s]
    assert len(inserts) == 1
    assert "tenant_id" in inserts[0]
    assert setup_db._FULL_SCOPES_SQL in inserts[0]
    assert "ON CONFLICT (key_hash) DO NOTHING" in inserts[0]
