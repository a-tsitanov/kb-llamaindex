from scripts import setup_db


class _Cur:
    def __init__(self):
        self.sql = []

    def execute(self, q, params=None):
        self.sql.append((str(q), params))


def test_global_ddl_creates_registry_tables_in_public():
    assert "CREATE TABLE IF NOT EXISTS public.graphs" in setup_db._GRAPHS_DDL
    assert "CREATE TABLE IF NOT EXISTS public.api_keys" in setup_db._API_KEYS_DDL


def test_bootstrap_inserts_default_row_idempotently(monkeypatch):
    cur = _Cur()
    monkeypatch.setattr(setup_db.settings.api, "keys", "k1,k2", raising=False)
    setup_db._bootstrap_registry(cur)
    stmts = [s for s, _ in cur.sql]
    assert any("INSERT INTO public.graphs" in s and "ON CONFLICT (id) DO NOTHING" in s for s in stmts)
    key_inserts = [p for s, p in cur.sql if "INSERT INTO public.api_keys" in s]
    assert len(key_inserts) == 2
    assert all("ON CONFLICT (key_hash) DO NOTHING" in s for s, _ in cur.sql if "public.api_keys" in s and "INSERT" in s)
