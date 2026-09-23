"""Minimal JSONPath subset used by view-specs.

Supported: ``$``, ``.key``, ``[n]``, ``[*]``, ``["key"]`` / ``['key']``.
``iter_path`` returns concrete paths so every canvas value can cite exactly
where it came from.
"""

from __future__ import annotations

import json
import re
from typing import Any

_TOKEN = re.compile(
    r"""\.(?P<key>[^.\[\]]+)"""
    r"""|\[(?P<idx>-?\d+)\]"""
    r"""|\[(?P<star>\*)\]"""
    r"""|\[(?P<q>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')\]"""
)
_PLAIN_KEY = re.compile(r"[^.\[\]\s'\"]+")


class PathError(ValueError):
    pass


class _Star:
    def __repr__(self) -> str:
        return "*"


STAR = _Star()


def parse(path: str) -> list[str | int | _Star]:
    if not isinstance(path, str) or not path.startswith("$"):
        raise PathError(f"path must start with '$': {path!r}")
    out: list[str | int | _Star] = []
    pos = 1
    while pos < len(path):
        m = _TOKEN.match(path, pos)
        if m is None:
            raise PathError(f"bad path syntax at {pos}: {path!r}")
        if m["key"] is not None:
            out.append(m["key"])
        elif m["idx"] is not None:
            out.append(int(m["idx"]))
        elif m["star"] is not None:
            out.append(STAR)
        else:
            q = m["q"]
            out.append(json.loads(q) if q[0] == '"' else q[1:-1].replace("\\'", "'"))
        pos = m.end()
    return out


def _fmt_key(key: str) -> str:
    if _PLAIN_KEY.fullmatch(key):
        return f".{key}"
    return f"[{json.dumps(key, ensure_ascii=False)}]"


def iter_path(data: Any, path: str) -> list[tuple[str, Any]]:
    results: list[tuple[str, Any]] = [("$", data)]
    for tok in parse(path):
        nxt: list[tuple[str, Any]] = []
        for cp, val in results:
            if tok is STAR:
                if isinstance(val, list):
                    nxt.extend((f"{cp}[{i}]", v) for i, v in enumerate(val))
                elif isinstance(val, dict):
                    nxt.extend((f"{cp}{_fmt_key(str(k))}", v) for k, v in val.items())
            elif isinstance(tok, int):
                if isinstance(val, list) and -len(val) <= tok < len(val):
                    i = tok % len(val)
                    nxt.append((f"{cp}[{i}]", val[i]))
            elif isinstance(val, dict) and tok in val:
                nxt.append((f"{cp}{_fmt_key(tok)}", val[tok]))
        results = nxt
    return results


def resolve(data: Any, path: str) -> Any:
    matches = iter_path(data, path)
    if len(matches) != 1:
        raise PathError(f"{path!r} matched {len(matches)} values, expected 1")
    return matches[0][1]


def join(base: str, rel: str) -> str:
    if not rel.startswith("$"):
        raise PathError(f"relative path must start with '$': {rel!r}")
    return base + rel[1:]
