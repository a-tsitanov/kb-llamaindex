from src.lens.model import AggregateEl, Column, ObjectEl, RawEl, Ref
from src.lens.normalizer import NormalizeResult
from src.lens.spec import Materialized
from tests.eval.lens_normalizer.scoring import aggregate, score


def res(objs=(), aggs=(), raw=False):
    if raw:
        return NormalizeResult(None, RawEl(key="raw:c", call_id="c", reason="x"), "raw")
    return NormalizeResult(Materialized(objects=list(objs), aggregates=list(aggs)), None, "llm")


def o(key, type_):
    return ObjectEl(key=key, type=type_, label=key)


def test_perfect_match():
    s = score(res([o("kb:1", "person"), o("kb:2", "event")]),
              {"objects": [{"key": "kb:1", "type": "person"}, {"key": "kb:2", "type": "event"}]})
    assert s == {"valid": True, "recall": 1.0, "precision": 1.0, "type_acc": 1.0}


def test_partial_and_wrong_type():
    s = score(res([o("kb:1", "organization"), o("kb:9", "person")]),
              {"objects": [{"key": "kb:1", "type": "person"}, {"key": "kb:2", "type": "event"}]})
    assert s["recall"] == 0.5 and s["precision"] == 0.5 and s["type_acc"] == 0.0


def test_raw_is_valid_only_when_golden_empty():
    assert score(res(raw=True), {"objects": []})["valid"] is True
    assert score(res(raw=True), {"objects": [{"key": "kb:1", "type": "person"}]})["valid"] \
        is False


def test_aggregate_counts_by_item_type():
    agg = AggregateEl(key="agg:c:h", label="ip · 30", item_type="ip", count=30,
                      rows_ref=Ref(call_id="c", path="$.h[*]"),
                      columns=[Column(name="id", path="$.ip")])
    s = score(res(aggs=[agg]), {"objects": [{"key": "fofa:1.1.1.1", "type": "ip"}]})
    assert s["recall"] == 1.0 and s["type_acc"] == 1.0


def test_aggregate_scores():
    a = aggregate([{"valid": True, "recall": 1.0, "precision": 0.5, "type_acc": 1.0},
                   {"valid": False, "recall": 0.0, "precision": 0.0, "type_acc": 0.0}])
    assert a == {"n": 2, "valid_rate": 0.5, "mean_recall": 0.5, "mean_precision": 0.25,
                 "mean_type_acc": 0.5}


def test_over_materialization_on_raw_fixture_is_invalid():
    s = score(res([o("kb:1", "person")]), {"objects": []})
    assert s == {"valid": False, "recall": 1.0, "precision": 0.0, "type_acc": 0.0}
    agg = AggregateEl(key="agg:c:h", label="ip · 30", item_type="ip", count=30,
                      rows_ref=Ref(call_id="c", path="$.h[*]"),
                      columns=[Column(name="id", path="$.ip")])
    assert score(res(aggs=[agg]), {"objects": []})["valid"] is False
    assert score(res(), {"objects": []})["valid"] is True
