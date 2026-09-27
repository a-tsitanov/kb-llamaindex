import src.graph.nebula_store as ns
from src.graph import nebula_schema
from src.tenancy.context import default_graph_context, new_graph_context


class _Sess:
    def __init__(self, log):
        self.log = log

    def execute(self, stmt):
        self.log.append(stmt)
        return type("R", (), {"is_succeeded": lambda s: True, "error_msg": lambda s: "", "error_code": lambda s: 0})()


def test_space_ddl_uses_graph_names():
    assert nebula_schema.space_ddl(default_graph_context()) == (
        "CREATE SPACE IF NOT EXISTS `kb` (partition_num=100, replica_factor=1, vid_type=FIXED_STRING(32));"
    )
    assert nebula_schema.space_ddl(new_graph_context("acme")) == (
        "CREATE SPACE IF NOT EXISTS `g_acme` (partition_num=10, replica_factor=1, vid_type=FIXED_STRING(32));"
    )


def test_ensure_schema_uses_the_graph_space():
    log = []
    nebula_schema.ensure_schema(_Sess(log), new_graph_context("acme"), use_attempts=1, use_delay_s=0)
    assert log[0].startswith("CREATE SPACE IF NOT EXISTS `g_acme`")
    assert log[1] == "USE `g_acme`;"
    assert not any("`kb`" in s for s in log)


def test_stores_are_cached_per_space_and_share_one_pool(monkeypatch):
    ns.reset_nebula_stores_for_tests()
    pools = []

    class FakePool:
        def __init__(self):
            pools.append(self)

        def init(self, *a, **k):
            return True

    used = []
    monkeypatch.setattr("nebula3.gclient.net.ConnectionPool", FakePool)
    monkeypatch.setattr(ns, "_acquire_session", lambda pool, u, p: object())
    monkeypatch.setattr(ns, "ensure_schema", lambda sess, graph: used.append(graph.nebula_space))
    a1 = ns.build_nebula_graph_store(new_graph_context("acme"))
    a2 = ns.build_nebula_graph_store(new_graph_context("acme"))
    d = ns.build_nebula_graph_store(default_graph_context())
    assert a1 is a2 and a1 is not d
    assert a1.graph.nebula_space == "g_acme" and d.graph.nebula_space == "kb"
    assert len(pools) == 1
    assert used == ["g_acme", "kb"]
    ns.reset_nebula_stores_for_tests()


def test_reconnect_reuses_the_graph_space(monkeypatch):
    ns.reset_nebula_stores_for_tests()
    monkeypatch.setattr("nebula3.gclient.net.ConnectionPool", lambda: type("P", (), {"init": lambda s, *a, **k: True})())
    monkeypatch.setattr(ns, "_acquire_session", lambda pool, u, p: object())
    used = []
    monkeypatch.setattr(ns, "ensure_schema", lambda sess, graph: used.append(graph.nebula_space))
    store = ns.build_nebula_graph_store(new_graph_context("acme"))
    store._reconnect()
    assert used == ["g_acme", "g_acme"]
    ns.reset_nebula_stores_for_tests()
