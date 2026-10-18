from dataclasses import replace

from src.graph import nebula_store
from src.tenancy.context import new_graph_context


class _Sess:
    released = 0

    def execute(self, stmt):
        raise AssertionError("not used")

    def release(self):
        _Sess.released += 1


def test_new_generation_gets_new_store_and_closes_old(monkeypatch):
    nebula_store.reset_nebula_stores_for_tests()
    monkeypatch.setattr(nebula_store, "_shared_pool", lambda: object())
    monkeypatch.setattr(nebula_store, "_acquire_session", lambda pool, u, p: _Sess())
    monkeypatch.setattr(nebula_store, "ensure_schema", lambda sess, graph: None)
    g1 = replace(new_graph_context("acme"), generation=1)
    g2 = replace(new_graph_context("acme"), generation=2)
    s1 = nebula_store.build_nebula_graph_store(g1)
    assert nebula_store.build_nebula_graph_store(g1) is s1
    s2 = nebula_store.build_nebula_graph_store(g2)
    assert s2 is not s1 and s2.graph.generation == 2
    assert _Sess.released == 1
    assert list(nebula_store._stores) == ["acme#2"]
    nebula_store.reset_nebula_stores_for_tests()
