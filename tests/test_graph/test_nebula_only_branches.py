"""No module branches on a graph backend: settings.graph is gone, NebulaGraph only."""
from __future__ import annotations

import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
PATTERN = re.compile(r"settings\.graph\b|settings\.neo4j\b|community_backend\s*==\s*[\"']gds|gds\.")


def test_no_backend_branches_anywhere():
    hits = [
        f"{p.relative_to(SRC)}:{i}"
        for p in SRC.rglob("*.py")
        for i, line in enumerate(p.read_text().splitlines(), 1)
        if PATTERN.search(line)
    ]
    assert hits == []
