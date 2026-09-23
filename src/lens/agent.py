"""Input orchestration: route → (commands | planner → normalizer) → op log → events.

Inputs of one workspace run one at a time (per-workspace lock); "стоп" cancels the
running one.  Pins bypass the lock (the store serializes seq), so dragging never
waits for a 30-second search.
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict

from loguru import logger

from src.lens.events import EventBus
from src.lens.model import NoteEl, ObjectEl, Op, OpKind, RelationEl
from src.lens.normalizer import Normalizer
from src.lens.planner import Planner, PlannerFinal, PlannerStatus, ToolCalled
from src.lens.router import Command, Search, is_stop, route
from src.lens.state import CanvasState, fold
from src.lens.store import LensStore

_CITE = re.compile(r"\s*\[\[([^\[\]]+)\]\]")
_NORM = re.compile(r"[\W_]+", re.U)


def _canvas_summary(st: CanvasState, limit: int = 80) -> str:
    """Most recent visible objects first, with keys (the LLM cites/uses them)."""
    items = [
        f"{o.label} ({o.type}) [{k}]"
        for k, o in reversed(st.objects.items())
        if k not in st.hidden
    ]
    return "; ".join(items[:limit])


def _norm_label(label: str) -> str:
    return _NORM.sub(" ", label.casefold().replace("ё", "е")).strip()


def _ns(key: str) -> str:
    return key.split(":", 1)[0]


def same_as_candidates(
    new: list[ObjectEl], existing: dict[str, ObjectEl]
) -> list[RelationEl]:
    """Cross-namespace objects with the same type and normalized label → ``same_as?``."""
    index: dict[tuple[str, str], list[str]] = defaultdict(list)
    for k, o in existing.items():
        index[(o.type, _norm_label(o.label))].append(k)
    out: list[RelationEl] = []
    for o in new:
        for other in index.get((o.type, _norm_label(o.label)), []):
            if _ns(other) != _ns(o.key):
                out.append(
                    RelationEl(
                        from_key=o.key,
                        to_key=other,
                        kind="same_as?",
                        confidence=0.5,
                    )
                )
        index[(o.type, _norm_label(o.label))].append(o.key)
    return out


def resolve_citations(
    text: str, known: set[str]
) -> tuple[str, list[str]]:
    """Keep ``[[key]]`` markers that name real canvas elements, drop invented ones."""
    cites: list[str] = []

    def repl(m: re.Match) -> str:
        key = m.group(1).strip()
        if key in known:
            if key not in cites:
                cites.append(key)
            return f" [[{key}]]"
        return ""

    return _CITE.sub(repl, text).strip(), cites


class Agent:
    def __init__(
        self,
        *,
        store: LensStore,
        bus: EventBus,
        planner: Planner,
        normalizer: Normalizer,
    ) -> None:
        self.store, self.bus = store, bus
        self.planner, self.normalizer = planner, normalizer
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._tasks: set[asyncio.Task] = set()
        self._current: dict[str, asyncio.Task] = {}

    async def submit(
        self, workspace_id: str, text: str, mentions: list[str]
    ) -> str:
        input_id = await self.store.add_input(workspace_id, text, mentions)
        if is_stop(text):
            running = self._current.get(workspace_id)
            if running is not None and not running.done():
                running.cancel()
                reply = "Останавливаю текущий запрос."
            else:
                reply = "Сейчас ничего не выполняется."
            await self.store.set_input_status(input_id, "done")
            self.bus.publish(
                workspace_id,
                {"type": "reply", "input_id": input_id, "text": reply},
            )
            self.bus.publish(
                workspace_id,
                {
                    "type": "input_done",
                    "input_id": input_id,
                    "status": "done",
                },
            )
            return input_id
        task = asyncio.create_task(
            self.process(workspace_id, input_id, text, mentions)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return input_id

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(
                *list(self._tasks), return_exceptions=True
            )

    async def pin(
        self, workspace_id: str, key: str, x: float, y: float
    ) -> list[Op]:
        return await self._append(
            workspace_id, None, [("pin", {"key": key, "x": x, "y": y})]
        )

    async def _append(
        self,
        workspace_id: str,
        input_id: str | None,
        ops: list[tuple[OpKind, dict]],
    ) -> list[Op]:
        if not ops:
            return []
        written = await self.store.append_ops(workspace_id, input_id, ops)
        self.bus.publish(
            workspace_id,
            {
                "type": "ops",
                "ops": [o.model_dump(mode="json") for o in written],
            },
        )
        return written

    def _reply(self, workspace_id: str, input_id: str, text: str) -> None:
        self.bus.publish(
            workspace_id,
            {"type": "reply", "input_id": input_id, "text": text},
        )

    async def process(
        self,
        workspace_id: str,
        input_id: str,
        text: str,
        mentions: list[str],
    ) -> None:
        async with self._locks[workspace_id]:
            self._current[workspace_id] = asyncio.current_task()
            status = "done"
            try:
                await self._process(workspace_id, input_id, text, mentions)
            except asyncio.CancelledError:
                status = "cancelled"
                self._reply(workspace_id, input_id, "Остановлено.")
            except Exception as e:  # surface any failure to the UI
                logger.exception("lens: input {} failed", input_id)
                status = "failed"
                self._reply(workspace_id, input_id, f"Ошибка: {e}")
            finally:
                self._current.pop(workspace_id, None)
            await self.store.set_input_status(input_id, status)
            self.bus.publish(
                workspace_id,
                {
                    "type": "input_done",
                    "input_id": input_id,
                    "status": status,
                },
            )

    async def _open(
        self, workspace_id: str, input_id: str, query: str
    ) -> bool:
        q = query.casefold()
        found = [
            w
            for w in await self.store.list_workspaces()
            if q in w.title.casefold()
        ]
        if len(found) == 1:
            self.bus.publish(
                workspace_id,
                {
                    "type": "open_workspace",
                    "input_id": input_id,
                    "workspace_id": found[0].id,
                    "title": found[0].title,
                },
            )
            return True
        if len(found) > 1:
            titles = ", ".join(w.title for w in found[:5])
            self._reply(
                workspace_id,
                input_id,
                f"Подходят несколько расследований: {titles}.",
            )
            return True
        return False

    async def _process(
        self,
        workspace_id: str,
        input_id: str,
        text: str,
        mentions: list[str],
    ) -> None:
        state = fold(await self.store.list_ops(workspace_id))
        decision = route(text, mentions, state)
        if isinstance(decision, Command):
            if decision.open_query is not None:
                if await self._open(
                    workspace_id, input_id, decision.open_query
                ):
                    return
                decision = Search(text.strip())  # no such workspace: it's a query
            else:
                await self._append(workspace_id, input_id, decision.ops)
                if decision.reply:
                    self._reply(workspace_id, input_id, decision.reply)
                return
        await self._search(
            workspace_id, input_id, decision.text, mentions, state
        )

    async def _search(
        self,
        workspace_id: str,
        input_id: str,
        text: str,
        mentions: list[str],
        state: CanvasState,
    ) -> None:
        canon_mentions = [state.canon(m) for m in mentions]
        mention_ctx = []
        for k in canon_mentions:
            o = state.objects.get(k)
            if o is not None:
                d = o.model_dump(mode="json", include={"key", "type", "label", "attrs"})
                ns, _, obj_id = k.partition(":")
                d["id"], d["namespace"] = obj_id, ns
                mention_ctx.append(d)
                continue
            v = state.views.get(k)
            if v is not None:
                mention_ctx.append({"key": k, "kind": v.get("kind"), "label": v.get("label")})
        known_objects: dict[str, ObjectEl] = dict(state.objects)
        # Ordered set (dict keys keep insertion order): mentions first, then the most
        # recently added canvas objects, then everything else — build_prompt's cap
        # relies on this order to keep the most relevant keys when there are many.
        known_keys: dict[str, None] = {}
        for k in (*canon_mentions, *reversed(state.objects), *state.views):
            known_keys.setdefault(k, None)
        calls: list[str] = []
        async for ev in self.planner.run(
            input_id=input_id,
            text=text,
            mentions=mention_ctx,
            canvas_summary=_canvas_summary(state),
        ):
            if isinstance(ev, PlannerStatus):
                self.bus.publish(
                    workspace_id,
                    {
                        "type": "status",
                        "input_id": input_id,
                        "server": ev.server,
                        "tool": ev.tool,
                        "state": ev.state,
                        "message": ev.message,
                    },
                )
            elif isinstance(ev, ToolCalled):
                calls.append(ev.record.id)
                result = await self.normalizer.normalize(
                    ev.record, ev.tool.description, known_keys
                )
                ops: list[tuple[OpKind, dict]] = []
                m = result.materialized
                if m is not None:
                    relations = list(m.relations)
                    if m.objects:
                        fresh = [
                            o
                            for o in m.objects
                            if o.key not in known_objects
                        ]
                        relations += same_as_candidates(
                            fresh, known_objects
                        )
                        ops.append(
                            (
                                "add_objects",
                                {
                                    "objects": [
                                        o.model_dump(mode="json")
                                        for o in m.objects
                                    ]
                                },
                            )
                        )
                        for o in m.objects:
                            known_objects.setdefault(o.key, o)
                            known_keys[o.key] = None
                    if relations:
                        ops.append(
                            (
                                "add_relations",
                                {
                                    "relations": [
                                        r.model_dump(mode="json")
                                        for r in relations
                                    ]
                                },
                            )
                        )
                    for agg in m.aggregates:
                        ops.append(
                            (
                                "add_view",
                                {"view": agg.model_dump(mode="json")},
                            )
                        )
                        known_keys[agg.key] = None
                if result.raw is not None:
                    ops.append(
                        (
                            "add_view",
                            {"view": result.raw.model_dump(mode="json")},
                        )
                    )
                    known_keys[result.raw.key] = None
                await self._append(workspace_id, input_id, ops)
            elif isinstance(ev, PlannerFinal) and ev.text.strip():
                body, cites = resolve_citations(ev.text, known_keys)
                note = NoteEl(
                    key=f"note:{input_id}",
                    text=body,
                    cites=cites,
                    calls=calls,
                )
                await self._append(
                    workspace_id,
                    input_id,
                    [("add_note", {"note": note.model_dump(mode="json")})],
                )
