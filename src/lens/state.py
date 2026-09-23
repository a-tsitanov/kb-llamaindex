"""Canvas state = fold of the workspace op log."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from src.lens.model import NoteEl, ObjectEl, Op, RelationEl


@dataclass
class CanvasState:
    objects: dict[str, ObjectEl] = field(default_factory=dict)
    object_inputs: dict[str, list[str]] = field(default_factory=dict)
    relations: dict[str, RelationEl] = field(default_factory=dict)
    views: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: list[NoteEl] = field(default_factory=list)
    hidden: set[str] = field(default_factory=set)
    pins: dict[str, dict[str, float]] = field(default_factory=dict)
    mode: str = "canvas"
    aliases: dict[str, str] = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)
    last_seq: int = 0

    def canon(self, key: str) -> str:
        seen = set()
        while key in self.aliases and key not in seen:
            seen.add(key)
            key = self.aliases[key]
        return key


def _merge_obj(into: ObjectEl, other: ObjectEl) -> None:
    for k, v in other.attrs.items():
        into.attrs.setdefault(k, v)
    known = {(r.call_id, r.path) for r in into.refs}
    into.refs.extend(r for r in other.refs if (r.call_id, r.path) not in known)


def _add_input(st: CanvasState, key: str, input_id: str | None) -> None:
    if input_id is None:
        return
    lst = st.object_inputs.setdefault(key, [])
    if input_id not in lst:
        lst.append(input_id)


def _put_relation(st: CanvasState, rel: RelationEl) -> None:
    rel.from_key, rel.to_key = st.canon(rel.from_key), st.canon(rel.to_key)
    if rel.from_key == rel.to_key:
        return
    if rel.key in st.relations:
        known = {(r.call_id, r.path) for r in st.relations[rel.key].refs}
        st.relations[rel.key].refs.extend(
            r for r in rel.refs if (r.call_id, r.path) not in known)
    else:
        st.relations[rel.key] = rel


def _apply(st: CanvasState, op: Op) -> None:
    p = op.payload
    if op.kind == "add_objects":
        for d in p["objects"]:
            o = ObjectEl.model_validate(d)
            o.key = st.canon(o.key)
            if o.key in st.objects:
                _merge_obj(st.objects[o.key], o)
            else:
                st.objects[o.key] = o
            _add_input(st, o.key, op.input_id)
    elif op.kind == "add_relations":
        for d in p["relations"]:
            _put_relation(st, RelationEl.model_validate(d))
    elif op.kind == "add_view":
        st.views[p["view"]["key"]] = dict(p["view"])
    elif op.kind == "add_note":
        st.notes.append(NoteEl.model_validate(p["note"]))
    elif op.kind == "hide":
        st.hidden |= {st.canon(k) for k in p["keys"]}
    elif op.kind == "show":
        st.hidden -= {st.canon(k) for k in p["keys"]}
    elif op.kind == "pin":
        st.pins[st.canon(p["key"])] = {"x": p["x"], "y": p["y"]}
    elif op.kind == "unpin":
        st.pins.pop(st.canon(p["key"]), None)
    elif op.kind == "set_mode":
        st.mode = p["mode"]
    elif op.kind == "merge":
        _merge(st, st.canon(p["keep"]), st.canon(p["drop"]))


def _merge(st: CanvasState, keep: str, drop: str) -> None:
    if keep == drop:
        return
    st.aliases[drop] = keep
    if drop in st.objects:
        dobj = st.objects.pop(drop)
        if keep in st.objects:
            _merge_obj(st.objects[keep], dobj)
        else:
            dobj.key = keep
            st.objects[keep] = dobj
    for iid in st.object_inputs.pop(drop, []):
        _add_input(st, keep, iid)
    old = list(st.relations.values())
    st.relations = {}
    for rel in old:
        _put_relation(st, rel)
    if drop in st.hidden:
        st.hidden.discard(drop)
        st.hidden.add(keep)
    if drop in st.pins:
        st.pins.setdefault(keep, st.pins.pop(drop))


def fold(ops: Sequence[Op]) -> CanvasState:
    undone = {o.payload["input_id"] for o in ops if o.kind == "undo"}
    st = CanvasState()
    for o in sorted(ops, key=lambda x: x.seq):
        st.last_seq = o.seq
        if o.kind == "undo" or o.input_id in undone:
            continue
        _apply(st, o)
        if o.input_id and o.input_id not in st.inputs:
            st.inputs.append(o.input_id)
    return st


def state_to_dict(st: CanvasState) -> dict[str, Any]:
    return {
        "objects": [
            {**o.model_dump(mode="json"), "inputs": st.object_inputs.get(k, []),
             "hidden": k in st.hidden, "pin": st.pins.get(k)}
            for k, o in st.objects.items()
        ],
        "relations": [
            {**r.model_dump(mode="json"), "key": r.key} for r in st.relations.values()
        ],
        "views": [
            {**v, "hidden": k in st.hidden, "pin": st.pins.get(k)} for k, v in st.views.items()
        ],
        "notes": [n.model_dump(mode="json") for n in st.notes],
        "mode": st.mode,
        "inputs": list(st.inputs),
        "last_seq": st.last_seq,
    }
