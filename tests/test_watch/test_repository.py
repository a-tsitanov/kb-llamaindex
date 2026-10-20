"""WatchRepository — SQL shape over a stub connection (no live DB)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date

from psycopg.rows import dict_row

from src.storage import pg_scope
from src.tenancy.context import default_graph_context, new_graph_context
from src.watch import repository as watch_mod
from src.watch.repository import WatchRepository


@dataclass
class _Cur:
    rows: list = field(default_factory=list)
    row_factory: object = None
    executed: list = field(default_factory=list)
    many: list = field(default_factory=list)
    rowcount: int = 0

    async def execute(self, sql, params=None):
        self.executed.append((sql, params))

    async def executemany(self, sql, seq):
        self.many.append((sql, list(seq)))

    def _shaped(self, r):
        return r if self.row_factory is dict_row else tuple(r.values())

    async def fetchall(self):
        return [self._shaped(r) for r in self.rows]

    async def fetchone(self):
        return self._shaped(self.rows[0]) if self.rows else None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@dataclass
class _Conn:
    cur: _Cur
    commits: int = 0

    def cursor(self, *a, **kw):
        self.cur.row_factory = kw.get("row_factory")
        return self.cur

    async def commit(self):
        self.commits += 1

    def transaction(self):
        conn = self

        @asynccontextmanager
        async def _tx():
            yield
            conn.commits += 1

        return _tx()


def _repo(rows=None):
    conn = _Conn(cur=_Cur(rows=list(rows or [])))
    repo = WatchRepository(graph=default_graph_context())

    @asynccontextmanager
    async def _c():
        yield conn

    repo._conn = _c  # type: ignore[method-assign]
    return repo, conn


# ── journals ─────────────────────────────────────────────────────────


async def test_record_mentions_appends_idempotently():
    repo, conn = _repo()
    await repo.record_mentions([
        {"entity_vid": "v1", "doc_id": "d0c5e6a0-0000-0000-0000-000000000001",
         "entity_name": "Блинов", "label": "Person", "doc_date": date(2024, 3, 12),
         "mention_count": 4, "backfill": False},
    ])
    sql, rows = conn.cur.many[0]
    assert "INSERT INTO entity_mention" in sql
    assert "ON CONFLICT (entity_vid, doc_id) DO NOTHING" in sql
    assert rows[0][0] == "v1" and rows[0][5] == 4
    assert conn.commits == 1


async def test_record_mentions_empty_is_a_no_op():
    repo, conn = _repo()
    await repo.record_mentions([])
    assert conn.cur.many == [] and conn.commits == 0


async def test_record_new_edges_keeps_the_first_pair_only():
    repo, conn = _repo()
    await repo.record_new_edges([
        {"src_vid": "a", "src_name": "A", "src_label": "Person",
         "tgt_vid": "b", "tgt_name": "+79161234567", "tgt_label": "PhoneNumber",
         "rel": "PHONE", "doc_id": "d0c5e6a0-0000-0000-0000-000000000001",
         "doc_date": None, "backfill": False},
    ])
    sql, rows = conn.cur.many[0]
    assert "INSERT INTO edge_new" in sql
    assert "ON CONFLICT (src_vid, tgt_vid) DO NOTHING" in sql
    assert rows[0][:3] == ("a", "A", "Person")


# ── ER merge ─────────────────────────────────────────────────────────


async def test_rewrite_vid_moves_every_table_and_drops_colliding_loser_rows():
    repo, conn = _repo()
    await repo.rewrite_vid("loser", "canon", "Исаев Валентин Игоревич")
    blob = "\n".join(s for s, _ in conn.cur.executed)
    for t in ("watch", "entity_mention", "edge_new", "watch_event"):
        assert f"UPDATE {t} " in blob
    # rows that would collide with an existing canonical row are deleted
    assert "DELETE FROM watch " in blob
    assert "DELETE FROM entity_mention " in blob
    assert "DELETE FROM edge_new " in blob
    assert conn.commits == 1


async def test_rewrite_vid_same_vid_is_a_no_op():
    repo, conn = _repo()
    await repo.rewrite_vid("v", "v", "x")
    assert conn.cur.executed == []


# ── sweep plumbing ───────────────────────────────────────────────────


async def test_cursor_defaults_to_zero():
    repo, _ = _repo(rows=[])
    assert await repo.cursor("entity_mention") == 0


async def test_read_journal_rejects_unknown_tables():
    repo, _ = _repo()
    import pytest

    with pytest.raises(ValueError):
        await repo.read_journal("documents; DROP", after_id=0, limit=10)


async def test_read_journal_reads_past_the_cursor_with_a_settle_lag():
    repo, conn = _repo(rows=[{"id": 5}])
    rows = await repo.read_journal("edge_new", after_id=4, limit=100)
    sql, params = conn.cur.executed[0]
    assert "FROM edge_new" in sql and "id > %s" in sql and "ORDER BY id" in sql
    assert "interval" in sql
    assert params[0] == 4 and params[-1] == 100
    assert rows == [{"id": 5}]


async def test_save_events_and_cursor_is_one_transaction():
    repo, conn = _repo()
    await repo.save_events("edge_new", [{
        "entity_vid": "a", "entity_name": "A", "kind": "new_identifier",
        "doc_id": None, "doc_date": None, "detail": {"tgt": "+7"}, "why": "w",
        "source_table": "edge_new", "source_id": 5, "dedup_key": "k",
    }], last_id=5)
    ins_sql, rows = conn.cur.many[0]
    assert "INSERT INTO watch_event" in ins_sql
    assert "ON CONFLICT (dedup_key) DO NOTHING" in ins_sql
    assert '"tgt"' in rows[0][5]  # detail serialized as JSON
    cur_sql, cur_params = conn.cur.executed[-1]
    assert "INSERT INTO monitor_cursor" in cur_sql and "ON CONFLICT (name)" in cur_sql
    assert cur_params == ("edge_new", 5)
    assert conn.commits == 1


async def test_watched_returns_vid_to_name():
    repo, _ = _repo(rows=[{"entity_vid": "a", "entity_name": "A"}])
    assert await repo.watched() == {"a": "A"}


# ── subscriptions + feed ─────────────────────────────────────────────


async def test_add_watch_upserts_on_owner_and_entity():
    repo, conn = _repo()
    await repo.add_watch("default", "v", "Блинов", kinds=["new_mention"], note="КУСП 805")
    sql, params = conn.cur.executed[0]
    assert "INSERT INTO watch" in sql and "ON CONFLICT (owner, entity_vid)" in sql
    assert params == ("default", "v", "Блинов", ["new_mention"], "КУСП 805")


async def test_remove_watch_reports_whether_anything_was_removed():
    repo, conn = _repo()
    conn.cur.rowcount = 1
    assert await repo.remove_watch("default", "v") is True


async def test_feed_scopes_to_owner_subscriptions_kinds_mute_and_unacked():
    repo, conn = _repo(rows=[])
    await repo.feed("default", include_acked=False, limit=20)
    sql, params = conn.cur.executed[0]
    assert "JOIN watch w ON w.entity_vid = e.entity_vid AND w.owner = %s" in sql
    assert "e.detected_at >= w.created_at" in sql
    assert "cardinality(w.kinds) = 0 OR e.kind = ANY(w.kinds)" in sql
    assert "w.muted_until IS NULL OR w.muted_until < now()" in sql
    assert "s.acked_at IS NULL" in sql
    assert params[0] == "default" and params[-1] == 20


async def test_feed_with_acked_drops_the_unacked_filter():
    repo, conn = _repo(rows=[])
    await repo.feed("default", include_acked=True, limit=20)
    assert "s.acked_at IS NULL" not in conn.cur.executed[0][0]


async def test_ack_specific_events():
    repo, conn = _repo()
    await repo.ack("default", event_ids=[1, 2])
    sql, rows = conn.cur.many[0]
    assert "INSERT INTO watch_seen" in sql and "acked_at" in sql
    assert rows == [("default", 1), ("default", 2)]


async def test_ack_all_marks_every_visible_event():
    repo, conn = _repo()
    await repo.ack("default", all_events=True)
    sql, params = conn.cur.executed[0]
    assert "INSERT INTO watch_seen" in sql and "SELECT" in sql
    assert params == ("default",)


# ── graph scoping ────────────────────────────────────────────────────


class _ScopedConn:
    """Records the search_path SET + commits, then serves the watch queries."""

    def __init__(self):
        self.log: list = []
        self.cur = _Cur()

    async def execute(self, q, params=None):
        self.log.append(q.as_string(None) if hasattr(q, "as_string") else str(q))

    async def commit(self):
        self.log.append("commit")

    def cursor(self, *a, **kw):
        self.cur.row_factory = kw.get("row_factory")
        return self.cur

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


async def test_pooled_connection_runs_in_the_graph_schema(monkeypatch):
    conn = _ScopedConn()

    class _Pool:
        @asynccontextmanager
        async def connection(self, timeout=None):
            yield conn

    async def _get_pool():
        return _Pool()

    monkeypatch.setattr(pg_scope, "get_pg_pool", _get_pool)
    repo = WatchRepository(graph=new_graph_context("acme"))
    assert repo.graph.id == "acme"
    await repo.watched()
    assert conn.log[:2] == ['SET search_path TO "g_acme", extensions', "commit"]
    assert conn.cur.executed  # the query ran on the scoped connection


async def test_dsn_connection_sets_the_graph_schema(monkeypatch):
    conn = _ScopedConn()

    async def _connect(dsn):
        assert dsn == "postgresql://x"
        return conn

    monkeypatch.setattr(watch_mod.psycopg.AsyncConnection, "connect", _connect)
    repo = WatchRepository("postgresql://x", graph=new_graph_context("acme"))
    await repo.watched()
    assert conn.log[:2] == ['SET search_path TO "g_acme", extensions', "commit"]
