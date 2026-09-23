"""Scoring for the Lens normalizer benchmark (spec §5 item 8)."""

from __future__ import annotations

from src.lens.normalizer import NormalizeResult


def score(result: NormalizeResult, golden: dict) -> dict:
    gold = {g["key"]: g["type"] for g in golden.get("objects", [])}
    if result.raw is not None or result.materialized is None:
        ok = not gold
        return {"valid": ok, "recall": 1.0 if ok else 0.0, "precision": 1.0 if ok else 0.0,
                "type_acc": 1.0 if ok else 0.0}
    got = {o.key: o.type for o in result.materialized.objects}
    agg_types = {a.item_type for a in result.materialized.aggregates}
    matched = [k for k in gold if k in got or gold[k] in agg_types]
    recall = len(matched) / len(gold) if gold else 1.0
    precision = (len([k for k in got if k in gold]) / len(got)) if got else (
        1.0 if matched or not gold else 0.0)
    type_ok = [k for k in matched if got.get(k, gold[k] if gold[k] in agg_types else None)
               == gold[k]]
    type_acc = len(type_ok) / len(matched) if matched else (1.0 if not gold else 0.0)
    return {"valid": True, "recall": recall, "precision": precision, "type_acc": type_acc}


def aggregate(scores: list[dict]) -> dict:
    n = len(scores)
    if n == 0:
        return {"n": 0, "valid_rate": 0.0, "mean_recall": 0.0, "mean_precision": 0.0,
                "mean_type_acc": 0.0}
    return {
        "n": n,
        "valid_rate": sum(s["valid"] for s in scores) / n,
        "mean_recall": sum(s["recall"] for s in scores) / n,
        "mean_precision": sum(s["precision"] for s in scores) / n,
        "mean_type_acc": sum(s["type_acc"] for s in scores) / n,
    }
