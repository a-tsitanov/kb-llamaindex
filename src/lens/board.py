"""Board service core: every rule the board enforces, independent of MCP/HTTP.

The agent (through the board MCP) and the web (through HTTP) both land here. Each change
is an op in the workspace log tagged with the run that made it (``Op.input_id`` holds the
run id), published on the board event bus so the web redraws.
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from src.lens.events import EventBus
from src.lens.keys import make_key, match_labels, normalize_id, normalize_kind, normalize_type
from src.lens.model import NoteEl, ObjectEl, Op, OpKind, RelationEl, Source
from src.lens.state import CanvasState, fold
from src.lens.store import LensStore

_CITE = re.compile(r"\[\[([^\[\]]+)\]\]")
_SOURCE_FIELDS = ("server", "tool", "call_id", "namespace")
# Keys the fold writes into ObjectEl/RelationEl.attrs itself (state.py, _put_relation). An
# item's incoming attrs must never seed or overwrite these — see state.py::_merge_obj.
_RESERVED_ATTRS = ("types_seen", "kind_original")


class BoardError(ValueError):
    """A request the board refuses as a whole (the message goes back to the agent)."""


@dataclass(frozen=True)
class BoardLimits:
    objects_per_call: int = 50
    objects_per_run: int = 200


def _source(raw: Any, run_id: str | None) -> Source | None:
    if not isinstance(raw, dict) or any(not raw.get(f) for f in _SOURCE_FIELDS):
        return None
    # run_id always comes from the caller's own header, never from the item — a caller
    # cannot forge a source into a different run this way.
    return Source(**{**raw, "run_id": run_id})


class BoardService:
    def __init__(self, store: LensStore, bus: EventBus, limits: BoardLimits | None = None):
        self.store, self.bus = store, bus
        self.limits = limits or BoardLimits()
        # Serializes read-check-write within one process only (Lens runs a single uvicorn
        # process). Running multiple workers would need a Postgres advisory lock here instead.
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # ── plumbing ────────────────────────────────────────────────────────
    async def _ops(self, ws: str) -> list[Op]:
        return await self.store.list_ops(ws)

    async def _append(
        self, ws: str, run_id: str | None, ops: list[tuple[OpKind, dict]],
    ) -> list[Op]:
        if not ops:
            return []
        written = await self.store.append_ops(ws, run_id, ops)
        self.bus.publish(ws, {"type": "ops",
                              "ops": [o.model_dump(mode="json") for o in written]})
        return written

    # ── reads ───────────────────────────────────────────────────────────
    async def state(self, ws: str) -> CanvasState:
        return fold(await self._ops(ws))

    async def get_board(
        self, ws: str, run_id: str | None, limit: int = 50, include_hidden: bool = False,
    ) -> dict[str, Any]:
        st = await self.state(ws)
        visible = {k: o for k, o in st.objects.items() if include_hidden or k not in st.hidden}
        always = {k for k in visible
                  if k in st.pins or (run_id and run_id in st.object_inputs.get(k, []))}
        ranked = sorted(visible, key=lambda k: st.touched.get(k, 0), reverse=True)
        chosen = list(always) + [k for k in ranked if k not in always]
        chosen = chosen[:max(limit, len(always))]
        picked = set(chosen)
        return {
            "objects": [{"key": k, "type": visible[k].type, "label": visible[k].label}
                        for k in chosen],
            "relations": [{"from": r.from_key, "to": r.to_key, "kind": r.kind}
                          for r in st.relations.values()
                          if r.from_key in picked and r.to_key in picked],
            "hidden": sorted(st.hidden),
            "total": len(visible),
        }

    async def find_on_board(self, ws: str, query: str) -> list[dict[str, str]]:
        st = await self.state(ws)
        labels = {k: o.label for k, o in st.objects.items() if k not in st.hidden}
        return [{"key": k, "label": labels[k]} for k in match_labels(query, labels)]

    async def get_object(self, ws: str, key: str) -> dict[str, Any] | None:
        st = await self.state(ws)
        o = st.objects.get(st.canon(key))
        return None if o is None else o.model_dump(
            mode="json", include={"key", "type", "label", "description", "attrs", "sources"})

    # ── writes (agent) ──────────────────────────────────────────────────
    async def add_objects(self, ws: str, run_id: str, objects: list[dict]) -> dict[str, Any]:
        if len(objects) > self.limits.objects_per_call:
            raise BoardError(
                f"слишком много объектов за вызов ({len(objects)} > "
                f"{self.limits.objects_per_call}) — выбери самые относящиеся к вопросу")
        async with self._locks[ws]:
            ops = await self._ops(ws)
            st = fold(ops)
            already = sum(len(o.payload.get("objects", [])) for o in ops
                          if o.kind == "add_objects" and o.input_id == run_id)
            if already + len(objects) > self.limits.objects_per_run:
                raise BoardError(
                    f"лимит объектов за запуск ({self.limits.objects_per_run}) — "
                    "заверши ответ с тем, что уже на доске")
            by_label = {(o.type, normalize_id(o.label)): k for k, o in st.objects.items()}
            built: list[ObjectEl] = []
            keys, merged, rejected = [], [], []
            added = 0
            for item in objects:
                oid, label = str(item.get("id") or "").strip(), str(item.get("label") or "").strip()
                src = _source(item.get("source"), run_id)
                if not oid or not label:
                    rejected.append({"item": item, "reason": "нужны id и label"})
                    continue
                if src is None:
                    rejected.append({"item": item, "reason": "нет источника — укажи call_id "
                                     "вызова инструмента, из которого взят объект"})
                    continue
                otype = normalize_type(item.get("type"))
                key = st.canon(make_key(src.namespace, oid))
                if key not in st.objects and (otype, normalize_id(label)) in by_label:
                    key = by_label[(otype, normalize_id(label))]
                if key in st.objects:
                    merged.append({"id": oid, "merged_into": key})
                elif key not in keys:
                    added += 1
                raw_attrs = item.get("attrs") if isinstance(item.get("attrs"), dict) else {}
                attrs = {k: v for k, v in raw_attrs.items() if k not in _RESERVED_ATTRS}
                built.append(ObjectEl(
                    key=key, type=otype, label=label,
                    description=(str(item["description"]).strip() or None)
                    if item.get("description") else None,
                    attrs=attrs,
                    sources=[src]))
                by_label.setdefault((otype, normalize_id(label)), key)
                keys.append(key)
            await self._append(ws, run_id, [(
                "add_objects", {"objects": [o.model_dump(mode="json") for o in built]})]
                if built else [])
            return {"added": added, "merged": merged, "keys": keys, "rejected": rejected}

    async def add_relations(self, ws: str, run_id: str, relations: list[dict]) -> dict[str, Any]:
        async with self._locks[ws]:
            st = await self.state(ws)
            built: list[RelationEl] = []
            rejected = []
            for item in relations:
                src = _source(item.get("source"), run_id)
                a = st.canon(str(item.get("from") or "").strip())
                b = st.canon(str(item.get("to") or "").strip())
                missing = [k for k in (a, b) if k not in st.objects]
                if src is None:
                    rejected.append({"item": item, "reason": "нет источника (call_id)"})
                elif missing:
                    rejected.append({"item": item, "reason":
                                     f"нет объекта {missing[0]!r} на доске — сначала add_objects"})
                elif a == b:
                    rejected.append({"item": item, "reason": "связь объекта с самим собой"})
                else:
                    kind, original = normalize_kind(item.get("kind"))
                    built.append(RelationEl(
                        from_key=a, to_key=b, kind=kind, sources=[src],
                        attrs={"kind_original": original} if original else {}))
            await self._append(ws, run_id, [(
                "add_relations", {"relations": [r.model_dump(mode="json") for r in built]})]
                if built else [])
            return {"added": len(built), "rejected": rejected}

    async def add_note(self, ws: str, run_id: str, text: str) -> dict[str, Any]:
        async with self._locks[ws]:
            ops = await self._ops(ws)
            if any(o.kind == "undo" and o.input_id == run_id for o in ops):
                return {"skipped": "в этом запуске была отмена — заметка не нужна"}
            st = fold(ops)
            # Hidden objects are excluded here too: a citation must never resolve to (or
            # match the label of) something the board currently hides.
            labels = {k: o.label for k, o in st.objects.items() if k not in st.hidden}
            cites: list[str] = []

            def resolve(m: re.Match) -> str:
                raw = m.group(1).strip()
                key = st.canon(raw)
                if key not in st.objects or key in st.hidden:
                    query = raw.split(":", 1)[1] if ":" in raw else raw
                    found = match_labels(query, labels)
                    if len(found) != 1:
                        return query  # unresolved → plain text, never a broken link
                    key = found[0]
                if key not in cites:
                    cites.append(key)
                return f"[[{key}]]"

            body = _CITE.sub(resolve, text).strip()
            note = NoteEl(key=f"note:{run_id}", text=body, cites=cites)
            await self._append(ws, run_id, [("add_note", {"note": note.model_dump(mode="json")})])
            return {"key": note.key, "cites": cites}

    async def _set_hidden(self, ws: str, run_id: str | None, keys: list[str], hide: bool) -> int:
        async with self._locks[ws]:
            st = await self.state(ws)
            canon = [k for k in dict.fromkeys(st.canon(k) for k in keys) if k in st.objects]
            if not canon:
                return 0
            await self._append(ws, run_id, [("hide" if hide else "show", {"keys": canon})])
            return len(canon)

    async def hide(self, ws: str, run_id: str | None, keys: list[str]) -> dict[str, int]:
        return {"changed": await self._set_hidden(ws, run_id, keys, True)}

    async def show(self, ws: str, run_id: str | None, keys: list[str]) -> dict[str, int]:
        return {"changed": await self._set_hidden(ws, run_id, keys, False)}

    async def merge(self, ws: str, run_id: str, keep: str, drop: str) -> dict[str, str]:
        async with self._locks[ws]:
            st = await self.state(ws)
            k, d = st.canon(keep), st.canon(drop)
            for key in (k, d):
                if key not in st.objects:
                    raise BoardError(f"нет объекта {key!r} на доске")
            if k == d:
                return {"key": k}
            await self._append(ws, run_id, [("merge", {"keep": k, "drop": d})])
            return {"key": k}

    async def undo(self, ws: str, run_id: str) -> dict[str, Any]:
        """Revert the last run that changed the board, never the current one."""
        async with self._locks[ws]:
            ops = await self._ops(ws)
            st = fold(ops)
            previous = [i for i in st.inputs if i != run_id]
            if not previous:
                return {"reverted_run": None, "operations": 0, "message": "нечего отменять"}
            target = previous[-1]
            n = sum(1 for o in ops if o.input_id == target)
            await self._append(ws, run_id, [("undo", {"input_id": target})])
            return {"reverted_run": target, "operations": n}

    # ── writes (web) ────────────────────────────────────────────────────
    async def pin(self, ws: str, key: str, x: float, y: float) -> Op:
        (op,) = await self._append(ws, None, [("pin", {"key": key, "x": x, "y": y})])
        return op
