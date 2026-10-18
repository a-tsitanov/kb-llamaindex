import pytest

from src.graph import nebula_schema
from src.tenancy.context import default_graph_context, new_graph_context


class _Resp:
    def __init__(self, ok=True, names=()):
        self.ok, self.names = ok, list(names)

    def is_succeeded(self):
        return self.ok

    def error_msg(self):
        return "boom"

    def keys(self):
        return ["Name"]

    def row_size(self):
        return len(self.names)

    def row_values(self, i):
        class _V:
            def __init__(self, v):
                self.v = v

            def cast(self):
                return self.v
        return [_V(self.names[i])]


class _Sess:
    def __init__(self, responses):
        self.responses, self.stmts = responses, []

    def execute(self, stmt):
        self.stmts.append(stmt)
        for prefix, resp in self.responses.items():
            if stmt.startswith(prefix):
                return resp
        return _Resp()


def test_expected_names_parsed_from_ddl():
    assert {"Entity", "Community"} <= set(nebula_schema.expected_tags())
    assert {"RELATED", "MENTIONS", "IN_COMMUNITY"} <= set(nebula_schema.expected_edges())


def test_verify_reports_missing():
    sess = _Sess({
        "SHOW TAGS": _Resp(names=[t for t in nebula_schema.expected_tags() if t != "Community"]),
        "SHOW EDGES": _Resp(names=nebula_schema.expected_edges()),
    })
    assert nebula_schema.verify_space_schema(sess, new_graph_context("acme")) == ["Community"]
    assert sess.stmts[0] == "USE `g_acme`;"


def test_verify_space_unusable():
    sess = _Sess({"USE": _Resp(ok=False)})
    assert nebula_schema.verify_space_schema(sess, new_graph_context("acme")) == ["<space unusable>"]


def test_drop_space_statement():
    sess = _Sess({})
    nebula_schema.drop_space(sess, new_graph_context("acme"))
    assert sess.stmts == ["DROP SPACE IF EXISTS `g_acme`;"]


def test_drop_refuses_default_space():
    with pytest.raises(ValueError):
        nebula_schema.drop_space(_Sess({}), default_graph_context())


def test_drop_space_failure_raises():
    with pytest.raises(RuntimeError):
        nebula_schema.drop_space(_Sess({"DROP SPACE": _Resp(ok=False)}), new_graph_context("acme"))
