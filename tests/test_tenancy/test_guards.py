"""Plan A invariants: no transitional default left; physical names only via GraphContext."""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def _hits(pattern: str, allow: set[str]) -> list[str]:
    rx = re.compile(pattern)
    out = []
    for p in SRC.rglob("*.py"):
        rel = str(p.relative_to(ROOT))
        if rel in allow:
            continue
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if rx.search(line):
                out.append(f"{rel}:{i}")
    return out


def test_no_transitional_default_left():
    assert _hits(r"transitional_default_graph", {"src/tenancy/context.py"}) == []


def test_chunk_collection_setting_only_read_by_tenancy():
    assert _hits(r"settings\.milvus\.collection", {"src/tenancy/context.py"}) == []


def test_no_hardcoded_space_or_collection_names():
    assert _hits(r"SPACE_NAME|[\"']entity_er_vec[\"']|[\"']community_report_vec[\"']|USE `kb`", {"src/tenancy/context.py"}) == []


def test_graph_store_builders_require_a_graph():
    import inspect

    from src.graph.nebula_store import build_nebula_graph_store
    from src.graph.store import build_graph_store
    for fn in (build_graph_store, build_nebula_graph_store):
        assert list(inspect.signature(fn).parameters) == ["graph"]
