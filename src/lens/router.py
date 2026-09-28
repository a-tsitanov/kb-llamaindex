"""Rule-based router: workspace commands compile to ops without MCP/LLM.

Commands are matched against the WHOLE input (so "отмена санкций" is a search, not
an undo).  Text targets ("скрой Путина") are matched by words with a crude Russian
stem, never by raw substring (so "Си" does not hit "Россия").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.lens.keys import match_labels
from src.lens.model import Column, OpKind, Ref, TableEl
from src.lens.state import CanvasState

_END = r"\s*[.!]?$"
_UNDO = re.compile(r"^(отмени|отмена|undo)" + _END, re.I)
_STOP = re.compile(r"^(стоп|останови(сь)?|прекрати|stop)" + _END, re.I)
_MERGE = re.compile(r"^(да,?\s*)?(это одно(\s+и то же)?|объедини)" + _END, re.I)
_TABLE = re.compile(
    r"^(покажи\s+)?таблицей(\s+только\s+(?P<vals>.+?))?" + _END, re.I)
_CANVAS_MODE = re.compile(r"^(покажи\s+)?(полем|на поле|карточками)" + _END, re.I)
_HIDE = re.compile(r"^(скрой|убери|спрячь)\b\s*(?P<t>.*?)" + _END, re.I)
_SHOW = re.compile(r"^(покажи|верни)\b\s*(?P<t>.*?)" + _END, re.I)
_OPEN = re.compile(r"^открой\s+(?P<t>.+?)" + _END, re.I)
_VALS_SPLIT = re.compile(r"\s*(?:,|\bи\b|\s)\s*", re.I)


@dataclass
class Command:
    ops: list[tuple[OpKind, dict]] = field(default_factory=list)
    reply: str | None = None
    # "открой X": the agent looks up a workspace by title; not found → treated as search
    open_query: str | None = None


@dataclass
class Search:
    text: str


def is_stop(text: str) -> bool:
    return bool(_STOP.match(text.strip()))


def _match(target: str, state: CanvasState, keys: list[str]) -> list[str]:
    return match_labels(target, {k: state.objects[k].label for k in keys})


def _ambiguous(state: CanvasState, keys: list[str]) -> Command:
    labels = ", ".join(state.objects[k].label for k in keys[:5])
    return Command(reply=f"Подходят несколько: {labels}. Уточни через @.")


def _table(text_match: re.Match, mentions: list[str], state: CanvasState) -> Command:
    aggs = [m for m in mentions if state.views.get(m, {}).get("kind") == "aggregate"]
    vals = [v for v in _VALS_SPLIT.split(text_match["vals"] or "") if v]
    if not mentions:
        if vals:
            return Command(reply="Отметь агрегат через @, чтобы отфильтровать таблицу.")
        return Command(ops=[("set_mode", {"mode": "table"})])
    if not aggs:
        return Command(reply="Таблицей можно показать только агрегат (например, @IP · 212).")
    ops: list[tuple[OpKind, dict]] = []
    for k in aggs:
        v = state.views[k]
        table = TableEl(key=f"table:{k}", source_key=k,
                        rows_ref=Ref.model_validate(v["rows_ref"]),
                        columns=[Column.model_validate(c) for c in v["columns"]],
                        filter={"*": vals} if vals else {})
        ops.append(("add_view", {"view": table.model_dump(mode="json")}))
    return Command(ops=ops)


def route(text: str, mentions: list[str], state: CanvasState) -> Command | Search:
    t = text.strip()
    mentions = [state.canon(m) for m in mentions]

    if _UNDO.match(t):
        if not state.inputs:
            return Command(reply="Нечего отменять.")
        return Command(ops=[("undo", {"input_id": state.inputs[-1]})])

    if _MERGE.match(t):
        if len(mentions) != 2:
            return Command(reply="Отметь два объекта через @, чтобы объединить.")
        return Command(ops=[("merge", {"keep": mentions[0], "drop": mentions[1]})])

    if m := _TABLE.match(t):
        return _table(m, mentions, state)

    if _CANVAS_MODE.match(t):
        return Command(ops=[("set_mode", {"mode": "canvas"})])

    if m := _HIDE.match(t):
        if mentions:
            return Command(ops=[("hide", {"keys": mentions})])
        visible = [k for k in state.objects if k not in state.hidden]
        found = _match(m["t"], state, visible)
        if not found:
            return Command(reply=f"Не нашёл «{m['t']}» на поле.")
        if len(found) > 1:
            return _ambiguous(state, found)
        return Command(ops=[("hide", {"keys": found})])

    if m := _SHOW.match(t):
        if mentions and not m["t"]:
            return Command(ops=[("show", {"keys": mentions})])
        hidden = [k for k in state.objects if k in state.hidden]
        found = _match(m["t"], state, hidden)
        if len(found) == 1:
            return Command(ops=[("show", {"keys": found})])
        if len(found) > 1:
            return _ambiguous(state, found)
        return Search(t)

    if not mentions and (m := _OPEN.match(t)):
        return Command(open_query=m["t"])

    return Search(t)
