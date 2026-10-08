"""Canvas state = fold of the workspace op log."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from src.lens.model import NoteEl, ObjectEl, Op, RelationEl, Source


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
    touched: dict[str, int] = field(default_factory=dict)  # key → seq of last add/merge
    last_seq: int = 0

    def canon(self, key: str) -> str:
        seen = set()
        while key in self.aliases and key not in seen:
            seen.add(key)
            key = self.aliases[key]
        return key


def _merge_sources(into: list[Source], other: list[Source]) -> None:
    known = {(s.call_id, s.run_id) for s in into}
    into.extend(s for s in other if (s.call_id, s.run_id) not in known)


def _merge_obj(into: ObjectEl, other: ObjectEl) -> None:
    for k, v in other.attrs.items():
        into.attrs.setdefault(k, v)
    known = {(r.call_id, r.path) for r in into.refs}
    into.refs.extend(r for r in other.refs if (r.call_id, r.path) not in known)
    _merge_sources(into.sources, other.sources)
    if other.description:
        into.description = other.description  # latest non-empty wins; history in the op log
    if into.type == "other" and other.type != "other":
        into.type = other.type  # "other" means unknown: a known type refines it
    elif other.type != into.type and other.type != "other":
        seen = into.attrs.get("types_seen")
        # Tolerate a non-list value: the model can write into attrs directly, and a
        # non-list types_seen must never brick every future read/write of this key.
        seen = list(seen) if isinstance(seen, list) else ([seen] if seen else [into.type])
        if other.type not in seen:
            seen.append(other.type)
        into.attrs["types_seen"] = seen


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
        _merge_sources(st.relations[rel.key].sources, rel.sources)
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
            st.touched[o.key] = op.seq
    elif op.kind == "add_relations":
        for d in p["relations"]:
            _put_relation(st, RelationEl.model_validate(d))
    elif op.kind == "add_view":
        st.views[p["view"]["key"]] = dict(p["view"])
    elif op.kind == "add_note":
        note = NoteEl.model_validate(p["note"])
        st.notes = [n for n in st.notes if n.key != note.key]  # one note per key (per run)
        st.notes.append(note)
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
        keep = st.canon(p["keep"])
        _merge(st, keep, st.canon(p["drop"]))
        st.touched[keep] = op.seq
    elif op.kind == "redirect":
        # the source renamed the entity (KB ER merge: «Росатом» → "Rosatom"): the object moves
        # to the new key, keeps its pins / relations / label, and remembers what it was
        to, frm = st.canon(p["to"]), st.canon(p["from"])
        label = st.objects[frm].label if frm in st.objects else None
        _merge(st, to, frm)
        obj = st.objects.get(to)
        if obj is not None:
            if label:
                obj.attrs.setdefault("resolved_from", label)
            if p.get("to_id"):
                obj.attrs["source_id"] = p["to_id"]
        st.touched[to] = op.seq


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
    st.touched.pop(drop, None)


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
            if r.from_key in st.objects and r.to_key in st.objects
        ],
        "views": [
            {**v, "hidden": k in st.hidden, "pin": st.pins.get(k)} for k, v in st.views.items()
        ],
        "notes": [n.model_dump(mode="json") for n in st.notes],
        "mode": st.mode,
        "inputs": list(st.inputs),
        "aliases": dict(st.aliases),
        "last_seq": st.last_seq,
    }
