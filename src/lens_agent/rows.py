"""Source-result rows that board writes must point at.

The model never authors an object: it names a row of a stored source result (by row number,
id or label) and the object's id / label / type / description are copied from that row. A
relation must match a relation row of a source result. Rows are found generically (any source):
an entity row is a dict with an id-like field (``id``, ``entity_name``, ``name``); a relation
row is a dict with two endpoints (``src_id``/``tgt_id``, ``from``/``to``, ``source``/``target``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from src.lens.keys import normalize_id

_ID_FIELDS = ("id", "entity_name", "name")
_LABEL_FIELDS = ("entity_name", "name", "title", "id")
_TYPE_FIELDS = ("entity_type", "type", "kind")
_ENDS = (("src_id", "tgt_id"), ("from", "to"), ("source", "target"))
# metadata about the call, not result rows (kb-tools: how the name was resolved)
_SKIP_KEYS = frozenset({"resolution"})


@dataclass
class Row:
    index: int
    id: str
    label: str
    type: str = ""
    description: str = ""
    names: set[str] = field(default_factory=set)  # normalized id + label


@dataclass
class RelRow:
    src: str
    tgt: str
    kind: str = ""
    description: str = ""


def _walk(payload: Any):
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(reversed(node))
        elif isinstance(node, dict):
            yield node
            stack.extend(reversed([v for k, v in node.items()
                                   if k not in _SKIP_KEYS and isinstance(v, list | dict)]))


def _first(d: dict, fields: tuple[str, ...]) -> str:
    for f in fields:
        v = d.get(f)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def entity_rows(payload: Any) -> list[Row]:
    rows: list[Row] = []
    for d in _walk(payload):
        if any(isinstance(d.get(a), str) and isinstance(d.get(b), str) for a, b in _ENDS):
            continue  # a relation row
        rid = _first(d, _ID_FIELDS)
        if not rid:
            continue
        label = _first(d, _LABEL_FIELDS) or rid
        rows.append(Row(index=len(rows), id=rid, label=label, type=_first(d, _TYPE_FIELDS),
                        description=str(d.get("description") or "").strip(),
                        names={normalize_id(rid), normalize_id(label)}))
    return rows


def relation_rows(payload: Any) -> list[RelRow]:
    out: list[RelRow] = []
    for d in _walk(payload):
        for a, b in _ENDS:
            if isinstance(d.get(a), str) and isinstance(d.get(b), str):
                out.append(RelRow(src=d[a], tgt=d[b],
                                  kind=str(d.get("label") or d.get("kind") or d.get("type") or ""),
                                  description=str(d.get("description") or "")))
                break
    return out


def match_entity(rows: list[Row], item: dict) -> Row | None:
    """The row the item points at: ``row`` number, else id or label (normalized, exact)."""
    n = item.get("row")
    if isinstance(n, int) and not isinstance(n, bool):
        return rows[n] if 0 <= n < len(rows) else None
    for v in (item.get("id"), item.get("label")):
        key = normalize_id(str(v)) if v not in (None, "") else ""
        if key:
            hit = next((r for r in rows if key in r.names), None)
            if hit is not None:
                return hit
    return None


def nearest(rows: list[Row], item: dict, n: int = 3) -> list[Row]:
    """Rows most similar to what the model wrote — returned with a rejection."""
    text = normalize_id(str(item.get("label") or item.get("id") or ""))
    if not text:
        return rows[:n]
    return sorted(rows, key=lambda r: -max(SequenceMatcher(None, text, x).ratio()
                                           for x in r.names))[:n]


def match_relation(rels: list[RelRow], a_names: set[str], b_names: set[str]) -> RelRow | None:
    """A relation row between the two objects (either direction); names are normalized."""
    a = {normalize_id(x) for x in a_names}
    b = {normalize_id(x) for x in b_names}
    for r in rels:
        s, t = normalize_id(r.src), normalize_id(r.tgt)
        if (s in a and t in b) or (s in b and t in a):
            return r
    return None
