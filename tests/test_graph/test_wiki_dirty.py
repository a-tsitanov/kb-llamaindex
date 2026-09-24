from unittest.mock import MagicMock

import src.graph.wiki_dirty as wiki_dirty
from src.graph.wiki_dirty import clear_dirty, mark_dirty, select_dirty


def test_mark_dirty_routes_through_seam(monkeypatch):
    store = MagicMock()
    ops = MagicMock()
    build = MagicMock(return_value=ops)
    monkeypatch.setattr(wiki_dirty, "build_wiki_graph_ops", build)

    mark_dirty(store, ["A", "B"])

    build.assert_called_once_with(store)
    ops.mark_dirty.assert_called_once_with(["A", "B"])


def test_select_dirty_routes_through_seam_and_returns_result(monkeypatch):
    store = MagicMock()
    ops = MagicMock()
    ops.select_dirty.return_value = ["A", "B"]
    build = MagicMock(return_value=ops)
    monkeypatch.setattr(wiki_dirty, "build_wiki_graph_ops", build)

    result = select_dirty(store, limit=10)

    assert result == ["A", "B"]
    build.assert_called_once_with(store)
    ops.select_dirty.assert_called_once_with(10)


def test_clear_dirty_routes_through_seam(monkeypatch):
    store = MagicMock()
    ops = MagicMock()
    build = MagicMock(return_value=ops)
    monkeypatch.setattr(wiki_dirty, "build_wiki_graph_ops", build)

    clear_dirty(store, "A", "deadbeef")

    build.assert_called_once_with(store)
    ops.clear_dirty.assert_called_once_with("A", "deadbeef")


# --- default (nebula) path: the seam issues the nGQL update (the per-backend
# guard lives in tests/test_graph/test_wiki_graph_ops.py; this just confirms
# a real, undispatched call reaches it). -----------------------------------


def test_mark_dirty_default_reaches_store():
    from src.graph.nebula_store import entity_vid

    store = MagicMock()
    mark_dirty(store, ["A", "B"])
    stmts = [c.args[0] for c in store.structured_query.call_args_list]
    assert len(stmts) == 2
    assert entity_vid("A") in stmts[0] and entity_vid("B") in stmts[1]
    assert all("wiki_dirty = true" in s for s in stmts)


def test_mark_dirty_noop_on_empty():
    store = MagicMock()
    mark_dirty(store, [])
    store.structured_query.assert_not_called()
