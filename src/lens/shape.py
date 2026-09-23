"""Response shape fingerprint (spec-cache key) and LLM-sized samples."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _shape(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _shape(v[k]) for k in sorted(v, key=str)}
    if isinstance(v, list):
        shapes: list[Any] = []
        for item in v[:5]:
            s = _shape(item)
            if s not in shapes:
                shapes.append(s)
        return ["list", shapes]
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    return type(v).__name__


def shape_hash(payload: Any) -> str:
    canon = json.dumps(_shape(payload), sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(canon.encode()).hexdigest()[:16]


def skeleton(payload: Any, max_items: int, max_str: int) -> Any:
    if isinstance(payload, dict):
        return {k: skeleton(v, max_items, max_str) for k, v in payload.items()}
    if isinstance(payload, list):
        out = [skeleton(x, max_items, max_str) for x in payload[:max_items]]
        if len(payload) > max_items:
            out.append(f"… {len(payload) - max_items} more")
        return out
    if isinstance(payload, str) and len(payload) > max_str:
        return payload[:max_str] + "…"
    return payload


def sample_json(payload: Any, budget_chars: int = 6000) -> str:
    """Full JSON when it fits the budget; otherwise progressively truncated."""
    s = json.dumps(payload, ensure_ascii=False)
    if len(s) <= budget_chars:
        return s
    for max_items, max_str in ((3, 120), (2, 80), (1, 60), (1, 30)):
        s = json.dumps(skeleton(payload, max_items, max_str), ensure_ascii=False)
        if len(s) <= budget_chars:
            return s
    return s[:budget_chars] + "…(truncated)"
