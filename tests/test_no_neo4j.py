"""Neo4j is gone for good: no mention in code, scripts or dependencies."""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "src", ROOT / "scripts"]
FILES = [ROOT / "pyproject.toml"]
NEEDLE = re.compile(r"neo4j", re.IGNORECASE)


def _hits():
    paths = [p for t in TARGETS for p in t.rglob("*") if p.is_file() and p.suffix in {".py", ".sh", ".toml", ".yml", ".yaml"}]
    paths += FILES
    return [
        f"{p.relative_to(ROOT)}:{i}"
        for p in paths
        for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1)
        if NEEDLE.search(line)
    ]


def test_no_neo4j_mentions():
    assert _hits() == []
