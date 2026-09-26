"""No module outside the store factory branches on settings.graph.backend."""
from __future__ import annotations

import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
ALLOWED = {SRC / "graph" / "store.py", SRC / "config.py"}
PATTERN = re.compile(r"settings\.graph\.backend|community_backend\s*==\s*[\"']gds|gds\.")


def test_no_backend_branches_outside_store():
    hits = [
        f"{p.relative_to(SRC)}:{i}"
        for p in SRC.rglob("*.py")
        if p not in ALLOWED
        for i, line in enumerate(p.read_text().splitlines(), 1)
        if PATTERN.search(line)
    ]
    assert hits == []
