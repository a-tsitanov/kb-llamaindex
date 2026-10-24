"""``SourceRepository`` — проверка эмитируемого SQL без живой БД."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest

from src.intake.sources import repository as repo_mod
from src.intake.sources.channel_key import normalize_slug
from src.intake.sources.repository import SourceRepository, SourceRow
from src.tenancy.context import default_graph_context


class _Cur:
    def __init__(self, rows: list[Any], rowcount: int) -> None:
        self.sql: list[tuple[str, Any]] = []
        self._rows, self.rowcount = rows, rowcount

    async def execute(self, q, params=None) -> None:
        self.sql.append((str(q), params))

    async def fetchall(self):
        return self._rows

    async def fetchone(self):
        return self._rows[0] if self._rows else None


class _Conn:
    def __init__(self, cur: _Cur) -> None:
        self.cur, self.commits = cur, 0

    def cursor(self, row_factory=None):
        @asynccontextmanager
        async def cm():
            yield self.cur

        return cm()

    async def commit(self) -> None:
        self.commits += 1


def _patch(monkeypatch, rows=None, rowcount=1) -> _Conn:
    conn = _Conn(_Cur(rows or [], rowcount))

    @asynccontextmanager
    async def graph_connection(graph, timeout=None):
        yield conn

    monkeypatch.setattr(repo_mod, "graph_connection", graph_connection)
    return conn


@pytest.fixture
def repo() -> SourceRepository:
    return SourceRepository(graph=default_graph_context())


def _row(**over) -> dict[str, Any]:
    return {
        "peer_id": 7, "slug": "news", "title": "News", "group_name": "g",
        "trust": None, "state": "active", "added_by": "me", "note": "",
        **over,
    }


async def test_add_writes_source_and_slug_in_one_transaction(monkeypatch, repo):
    conn = _patch(monkeypatch)
    await repo.add(7, "news", "News", "g", added_by="me")
    (q1, p1), (q2, p2) = conn.cur.sql
    assert "INSERT INTO source " in q1
    assert p1 == (7, "news", "News", "g", "me")
    assert "INSERT INTO source_slug" in q2 and p2 == (7, "news")
    assert conn.commits == 1


async def test_add_is_an_upsert_that_reactivates_a_left_channel(monkeypatch, repo):
    conn = _patch(monkeypatch)
    await repo.add(7, "news2", "News 2", "g2", added_by="you")
    q = conn.cur.sql[0][0]
    assert "ON CONFLICT (peer_id) DO UPDATE" in q
    assert "state = 'active'" in q and "left_at = NULL" in q
    for col in ("group_name", "slug", "title", "added_by"):
        assert f"{col} = EXCLUDED.{col}" in q
    # доверие и заметка оператора не затираются
    assert "trust" not in q.split("DO UPDATE")[1]
    assert "note" not in q.split("DO UPDATE")[1]


async def test_get_and_by_slug(monkeypatch, repo):
    conn = _patch(monkeypatch, [_row()])
    got = await repo.get(7)
    assert isinstance(got, SourceRow) and got.slug == "news"
    assert "WHERE peer_id = %s" in conn.cur.sql[0][0]
    await repo.by_slug("news")
    assert "WHERE slug = %s" in conn.cur.sql[1][0]
    assert conn.cur.sql[1][1] == ("news",)


async def test_get_missing_is_none(monkeypatch, repo):
    _patch(monkeypatch, [])
    assert await repo.get(1) is None


async def test_list_active_filters_state(monkeypatch, repo):
    conn = _patch(monkeypatch, [_row(), _row(peer_id=8)])
    rows = await repo.list_active()
    assert [r.peer_id for r in rows] == [7, 8]
    assert "state = 'active'" in conn.cur.sql[0][0]


async def test_set_trust_none_resets_to_group(monkeypatch, repo):
    conn = _patch(monkeypatch)
    assert await repo.set_trust(7, None) is True
    q, p = conn.cur.sql[0]
    assert "SET trust = %s" in q and p == (None, 7)
    assert conn.commits == 1


async def test_update_reports_missing_row(monkeypatch, repo):
    _patch(monkeypatch, rowcount=0)
    assert await repo.set_group(99, "x") is False


async def test_mark_left_keeps_the_row(monkeypatch, repo):
    conn = _patch(monkeypatch)
    assert await repo.mark_left(7) is True
    q = conn.cur.sql[0][0]
    assert q.startswith("UPDATE source")
    assert "state = 'left'" in q and "left_at = now()" in q
    assert "DELETE" not in q


async def test_trust_for_channel_goes_through_slug_history(monkeypatch, repo):
    conn = _patch(monkeypatch, [(0.8,)])
    assert await repo.trust_for_channel("old_name") == 0.8
    q, p = conn.cur.sql[0]
    assert "FROM source_slug" in q and "s.state = 'active'" in q
    assert p == ("old_name",)


async def test_trust_for_channel_none_when_no_row(monkeypatch, repo):
    _patch(monkeypatch, [])
    assert await repo.trust_for_channel("ghost") is None


async def test_trust_for_channel_none_when_trust_unset(monkeypatch, repo):
    _patch(monkeypatch, [(None,)])
    assert await repo.trust_for_channel("news") is None


async def test_slugs_of(monkeypatch, repo):
    _patch(monkeypatch, [("a",), ("b",)])
    assert await repo.slugs_of(7) == ["a", "b"]


async def test_remember_slug_is_idempotent(monkeypatch, repo):
    conn = _patch(monkeypatch)
    await repo.remember_slug(7, "new")
    q, p = conn.cur.sql[0]
    assert "ON CONFLICT DO NOTHING" in q and p == (7, "new")
    assert conn.commits == 1


def _order_by(q: str) -> str:
    return " ".join(q.split("ORDER BY")[1].split("LIMIT")[0].split())


async def test_trust_for_channel_prefers_current_owner_of_the_slug(monkeypatch, repo):
    # слаг мог достаться другому каналу: выигрывает тот, у кого он сейчас в source.slug
    conn = _patch(monkeypatch, [(0.3,)])
    await repo.trust_for_channel("taken")
    order = _order_by(conn.cur.sql[0][0])
    assert order.startswith("(COALESCE(NULLIF(ltrim(lower(s.slug), '@'), ''), s.peer_id::text) = ss.slug) DESC")
    assert "ss.seen_at DESC" in order and "s.peer_id DESC" in order


async def test_trust_for_channel_renamed_channel_found_by_old_slug(monkeypatch, repo):
    # переименованный канал: старый слаг только в истории, фильтр — по source_slug
    conn = _patch(monkeypatch, [(0.8,)])
    assert await repo.trust_for_channel("old_name") == 0.8
    q = conn.cur.sql[0][0]
    assert "WHERE ss.slug = %s" in q and "s.state = 'active'" in q
    assert "WHERE s.slug" not in q


async def test_by_slug_is_deterministic_when_slug_is_shared(monkeypatch, repo):
    conn = _patch(monkeypatch, [_row()])
    await repo.by_slug("taken")
    q, p = conn.cur.sql[0]
    assert "WHERE slug = %s" in q and p == ("taken",)
    order = _order_by(q)
    assert order.startswith("(state = 'active') DESC")
    assert "added_at DESC" in order and "peer_id DESC" in order


@pytest.mark.parametrize(
    "slug,expected",
    [("@Five", "five"), ("five", "five"), ("FIVE", "five"), ("", "-1007")],
)
async def test_registry_key_equals_the_key_of_what_the_feeder_posts(
    monkeypatch, repo, slug, expected,
):
    """Круг: ключ в source_slug == ключ того, что фидер кладёт в ``channel``."""
    conn = _patch(monkeypatch, [(0.9,)])
    await repo.add(-1007, slug, "Five", "g", added_by="me")
    (_q1, p1), (_q2, p2) = conn.cur.sql
    assert p1[1] == slug  # человеческое имя остаётся в source.slug
    stored_key = p2[1]
    assert stored_key == expected
    # так фидер называет канал в документах: слаг без «@», иначе peer_id
    posted_channel = (slug or str(-1007)).lstrip("@")
    assert normalize_slug(posted_channel) == stored_key
    # доверие по «голой» форме документа находит строку
    conn.cur.sql.clear()
    assert await repo.trust_for_channel(posted_channel) == 0.9
    assert conn.cur.sql[0][1] == (stored_key,)


async def test_remember_slug_stores_the_key_and_can_rename_the_display(monkeypatch, repo):
    conn = _patch(monkeypatch)
    await repo.remember_slug(7, "@NewName", display="@NewName")
    (_q1, p1), (q2, p2) = conn.cur.sql
    assert p1 == (7, "newname")
    assert "UPDATE source SET slug" in q2 and p2 == ("@NewName", 7)
    assert conn.commits == 1
