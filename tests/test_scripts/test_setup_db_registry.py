from scripts import setup_db


class _Cur:
    def __init__(self):
        self.sql = []

    def execute(self, q, params=None):
        self.sql.append((str(q), params))


def test_global_ddl_creates_registry_tables_in_public():
    assert "CREATE TABLE IF NOT EXISTS public.graphs" in setup_db._GRAPHS_DDL
    assert "CREATE TABLE IF NOT EXISTS public.api_keys" in setup_db._API_KEYS_DDL


def test_api_keys_ddl_has_no_authorization_columns():
    # Spec amendment 2026-10-17: keys authenticate only.
    assert "graph_ids" not in setup_db._API_KEYS_DDL
    assert "is_admin" not in setup_db._API_KEYS_DDL


def test_bootstrap_inserts_default_row_idempotently(monkeypatch):
    cur = _Cur()
    monkeypatch.setattr(setup_db.settings.api, "keys", "k1,k2", raising=False)
    setup_db._bootstrap_registry(cur)
    stmts = [s for s, _ in cur.sql]
    assert any("INSERT INTO public.graphs" in s and "ON CONFLICT (id) DO NOTHING" in s for s in stmts)
    key_inserts = [p for s, p in cur.sql if "INSERT INTO public.api_keys" in s]
    assert len(key_inserts) == 2
    assert all("ON CONFLICT (key_hash) DO NOTHING" in s for s, _ in cur.sql if "public.api_keys" in s and "INSERT" in s)
    for s, _ in cur.sql:
        if "INSERT INTO public.api_keys" in s:
            assert "graph_ids" not in s and "is_admin" not in s
            assert "'legacy-env'" in s


def _deletes(cur):
    return [(s, p) for s, p in cur.sql if "DELETE FROM public.api_keys" in s]


def test_bootstrap_prunes_legacy_env_keys_not_in_env(monkeypatch):
    """R-P7: rotating/removing a key in API_KEYS must revoke the old
    legacy-env row on the next setup_db run."""
    from src.tenancy.api_keys import hash_api_key

    cur = _Cur()
    monkeypatch.setattr(setup_db.settings.api, "keys", "k1,k2", raising=False)
    setup_db._bootstrap_registry(cur)
    deletes = _deletes(cur)
    assert len(deletes) == 1
    sql, params = deletes[0]
    assert "owner = 'legacy-env'" in sql
    assert "NOT (key_hash = ANY(%s))" in sql
    assert sorted(params[0]) == sorted([hash_api_key("k1"), hash_api_key("k2")])
    # prune runs after the inserts
    idx = [i for i, (s, _) in enumerate(cur.sql) if "public.api_keys" in s]
    assert "DELETE" in cur.sql[idx[-1]][0]


def test_bootstrap_with_no_env_keys_deletes_all_legacy_env_rows(monkeypatch):
    cur = _Cur()
    monkeypatch.setattr(setup_db.settings.api, "keys", " , ", raising=False)
    setup_db._bootstrap_registry(cur)
    assert not [s for s, _ in cur.sql if "INSERT INTO public.api_keys" in s]
    deletes = _deletes(cur)
    assert len(deletes) == 1
    sql, params = deletes[0]
    assert "owner = 'legacy-env'" in sql
    assert "ANY" not in sql
    assert not params


class _Desc:
    def __init__(self, name):
        self.name = name


class _SelCur(_Cur):
    _COLS = ("id", "owner", "status", "nebula_space", "nebula_partition_num",
             "chunks_collection", "er_vec_collection", "report_vec_collection",
             "pg_schema")

    def __init__(self, rows):
        super().__init__()
        self._rows = rows
        self.description = [_Desc(c) for c in self._COLS]

    def fetchall(self):
        return list(self._rows)


def _row(ctx, status="ready"):
    return (ctx.id, "system", status, ctx.nebula_space, ctx.nebula_partition_num,
            ctx.chunks_collection, ctx.er_vec_collection, ctx.report_vec_collection,
            ctx.pg_schema)


def test_ready_graphs_always_includes_default_when_row_missing():
    from src.tenancy.context import default_graph_context

    graphs = setup_db._ready_graphs(_SelCur([]))
    assert [g.id for g in graphs] == [default_graph_context().id]
    assert graphs[0] == default_graph_context()


def test_ready_graphs_dedupes_default_when_row_ready():
    from src.tenancy.context import default_graph_context

    d = default_graph_context()
    graphs = setup_db._ready_graphs(_SelCur([_row(d)]))
    assert [g.id for g in graphs] == [d.id]


def test_ready_graphs_includes_default_alongside_other_ready_graphs():
    from src.tenancy.context import default_graph_context, new_graph_context

    other = new_graph_context("acme")
    graphs = setup_db._ready_graphs(_SelCur([_row(other)]))
    assert sorted(g.id for g in graphs) == sorted([default_graph_context().id, "acme"])
    assert sum(1 for g in graphs if g.id == default_graph_context().id) == 1
