"""Per-run tool-call guard: the ``process_tool_call`` hook of every MCP server.

What the model cannot be trusted with happens here:
- every call gets a fresh short ``call_id`` (c1, c2 …) that the model sees in source results
  and cites in board writes; the journal (``tool_call``/``tool_result``) uses the same id.
  Provider tool-call ids are not trusted to be unique (some backends restart them each turn);
- tool calls of a run are sequential (see ``runner``), so an identical call in the same turn
  already finds the first one's result in the cache;
- source results are stored in full; the model sees numbered rows with a coverage header and
  the name resolution (``view``), cut to ``result_chars`` by whole rows, and pages the rest
  with the local ``more`` tool (not a source call: no source budget); results without entity
  rows keep a plain character cut;
- an identical repeated source call is answered from the run cache (not counted twice);
- soft budgets per kind (source / board): over budget the call is not made and the model is
  told to finish with what it has;
- board writes point at ROWS of this run's stored source results (see ``rows``): an object
  names a row (``row`` number, ``id`` or ``label``) of the cited call — or of any source call
  of the run when ``call_id`` is missing — and its id / label / type / description are
  copied from that row (never from the model); no matching row → rejected with the nearest
  rows. A relation must match a relation row of a source result (its kind comes from the
  row). The full ``source {server, tool, call_id, namespace}`` is attached by the hook;
- when a source says it resolved the asked name to another one by an exact-level match
  (``resolution`` block: casefold / alias / translit — a KB rename after an ER merge), an
  object already on the board under the asked name is moved to the new key (board
  ``redirect``, hidden from the model);
- board reads repeated while this run has not changed the board are answered from the cache
  with a nudge to add objects or answer (a weak model otherwise re-reads the board in a loop);
- consecutive calls that bring nothing new (cache hits, over-budget calls) are counted; at
  ``stall_calls`` the run is stopped (``RunStalled``) instead of burning the run timeout.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic_ai import ModelRetry

from src.lens.keys import make_key, normalize_id
from src.lens_agent.config import McpEntry
from src.lens_agent.rows import (
    Row,
    entity_rows,
    match_entity,
    match_relation,
    nearest,
    relation_rows,
)
from src.lens_agent.store import AgentStore, CallPayload
from src.lens_agent.stream import RunEmitter
from src.lens_agent.view import render

_BOARD_WRITES = {"add_objects": "objects", "add_relations": "relations"}
_BOARD_READS = ("get_board", "find_on_board", "get_object")


def _changed(name: str, result: Any) -> bool:
    """Did this board call change the board? Writes count only if something landed."""
    if name not in _BOARD_WRITES:
        return True  # note, hide/show, merge, undo
    return isinstance(result, dict) and (bool(result.get("added")) or bool(result.get("merged")))


log = logging.getLogger(__name__)

# resolution steps that mean "the same entity under its current name", not a guess
_RENAME_VIA = frozenset({"casefold", "alias", "translit"})


class RunStalled(Exception):
    """The agent keeps making calls that bring nothing new."""

    def __init__(self, calls: int):
        super().__init__(f"агент зациклился: {calls} вызовов подряд без новых данных")
        self.calls = calls


@dataclass(frozen=True)
class CallInfo:
    call_id: str  # the call whose stored payload backs this id (cache hits point back)
    server: str
    tool: str
    namespace: str


@dataclass(frozen=True)
class CallLimits:
    result_chars: int = 4000
    source_calls: int = 8
    board_calls: int = 20
    tool_timeout_s: float = 120.0
    stall_calls: int = 4


def _text(result: Any) -> str:
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False,
                                                             default=str)


def _summary(result: Any, text: str) -> dict[str, Any]:
    items = None
    if isinstance(result, list):
        items = len(result)
    elif isinstance(result, dict) and isinstance(result.get("added"), int):
        items = result["added"]  # board writes: what actually landed
    elif isinstance(result, dict):
        items = next((len(v) for v in result.values() if isinstance(v, list)), None)
    return {"items": items, "bytes": len(text.encode()), "preview": text[:200]}


class RunCalls:
    def __init__(self, run_id: str, store: AgentStore, emitter: RunEmitter,
                 limits: CallLimits | None = None):
        self.run_id, self.store, self.emitter = run_id, store, emitter
        self.limits = limits or CallLimits()
        self.registry: dict[str, CallInfo] = {}
        self.counts = {"source": 0, "board": 0}
        self.note_written = False
        self.undone = False
        self._seen: set[str] = set()
        self._n = 0
        self._cache: dict[str, tuple[str, str]] = {}
        self._payloads: dict[str, Any] = {}  # source call id -> full result (for source ids)
        self._object_src: dict[str, CallInfo] = {}  # board key written this run -> its source
        self._object_names: dict[str, set[str]] = {}  # board key -> normalized source names
        self._rows: dict[str, tuple[list[Row], list]] = {}  # source call id -> parsed rows
        self._board_version = 0  # bumped by every board change this run makes
        self._board_reads: dict[str, str] = {}  # read key (incl. version) -> first call id
        self.stalls = 0  # consecutive calls that brought nothing new
        # direct board MCP call (name, args) for hook-only board ops (redirect); set by the runner
        self.board_direct: Callable[[str, dict[str, Any]], Awaitable[Any]] | None = None

    def short_id(self, provider_id: str | None) -> str:
        """A fresh id for every hook invocation (never reused, even for a repeated provider
        id); the provider id is only remembered for ``seen``."""
        if provider_id:
            self._seen.add(provider_id)
        self._n += 1
        return f"c{self._n}"

    def seen(self, provider_id: str | None) -> bool:
        """Did this model tool call reach our hook (and get its own tool_result)?"""
        return bool(provider_id) and provider_id in self._seen

    def hook(self, entry: McpEntry):
        async def process_tool_call(ctx, call_tool, name: str, args: dict[str, Any]):
            cid = self.short_id(ctx.tool_call_id)
            await self.emitter.emit("tool_call", call_id=cid, server=entry.name, tool=name,
                                    args=args)
            if entry.role == "board":
                return await self._board(cid, call_tool, name, args)
            return await self._source(entry, cid, call_tool, name, args)
        return process_tool_call

    def _progress(self) -> None:
        self.stalls = 0

    def _stall(self) -> None:
        """Count a call that brought nothing new; stop the run at ``stall_calls``."""
        self.stalls += 1
        if self.stalls >= self.limits.stall_calls:
            raise RunStalled(self.stalls)

    def _stall_after_board(self, name: str, result: Any) -> None:
        if name in _BOARD_WRITES and not _changed(name, result):
            self._stall()  # everything was rejected: the model is stuck on a dead end

    async def _result(self, cid: str, *, ok: bool, t0: float, text: str = "",
                      result: Any = None, truncated: bool = False, error: str | None = None,
                      **extra: Any) -> None:
        data: dict[str, Any] = {"call_id": cid, "ok": ok,
                                "duration_ms": int((time.monotonic() - t0) * 1000),
                                "summary": _summary(result, text), "truncated": truncated,
                                **extra}
        if error is not None:
            data["error"] = error
        await self.emitter.emit("tool_result", **data)

    async def _call(self, cid: str, t0: float, call_tool, name: str, args: dict[str, Any]):
        try:
            return await asyncio.wait_for(call_tool(name, args, None),
                                          self.limits.tool_timeout_s)
        except ModelRetry as e:  # tool error: back to the model as text, red in the journal
            await self._result(cid, ok=False, t0=t0, error=str(e))
            raise
        except TimeoutError:
            msg = f"таймаут {self.limits.tool_timeout_s:.0f} с — попробуй иначе или завершай"
            await self._result(cid, ok=False, t0=t0, error=msg)
            raise ModelRetry(msg) from None
        except asyncio.CancelledError:  # run cancelled / timed out: close the call's entry
            await self._result(cid, ok=False, t0=t0, error="отменено")
            raise

    async def _source(self, entry: McpEntry, cid: str, call_tool, name: str,
                      args: dict[str, Any]) -> str:
        t0 = time.monotonic()
        key = json.dumps([entry.name, name, args], sort_keys=True, ensure_ascii=False,
                         default=str)
        if key in self._cache:
            first, model_text = self._cache[key]
            self.registry[cid] = self.registry[first]
            await self._result(cid, ok=True, t0=t0, text=model_text, cached_from=first)
            self._stall()
            return f"(повтор вызова {first}, тот же результат)\n{model_text}"
        if self.counts["source"] >= self.limits.source_calls:
            msg = (f"лимит вызовов источников исчерпан ({self.limits.source_calls}) — "
                   "завершай с тем, что есть")
            await self._result(cid, ok=False, t0=t0, error=msg)
            self._stall()
            return msg
        self.counts["source"] += 1
        result = await self._call(cid, t0, call_tool, name, args)
        self._progress()
        await self.store.save_payload(CallPayload(run_id=self.run_id, call_id=cid,
                                                  server=entry.name, tool=name, args=args,
                                                  payload=result))
        text = _text(result)
        n = self.limits.result_chars
        view = render(cid, result, n)
        if view is not None:
            model_text, truncated = view
        else:
            truncated = len(text) > n
            body = text[:n] + (f"\n…усечено, продолжение: more(call_id=\"{cid}\", "
                               f"offset={n})" if truncated else "")
            model_text = f"call_id={cid}\n{body}"
        moved = await self._redirect(entry.ns, result)
        if moved:
            model_text += f"\n{moved}"
        self.registry[cid] = CallInfo(cid, entry.name, name, entry.ns)
        self._payloads[cid] = result
        self._cache[key] = (cid, model_text)
        await self._result(cid, ok=True, t0=t0, text=text, result=result, truncated=truncated)
        return model_text

    async def _redirect(self, ns: str, result: Any) -> str:
        res = result.get("resolution") if isinstance(result, dict) else None
        if self.board_direct is None or not isinstance(res, dict) or res.get("status") != "ok":
            return ""
        chosen = res.get("chosen") if isinstance(res.get("chosen"), dict) else {}
        asked, name = str(res.get("query") or ""), str(chosen.get("name") or "")
        via = [str(v).rsplit("+", 1)[-1] for v in chosen.get("matched_via") or []]
        if (not asked or not name or normalize_id(asked) == normalize_id(name)
                or not set(via) & _RENAME_VIA):
            return ""
        frm, to = make_key(ns, asked), make_key(ns, name)
        try:
            r = await self.board_direct("redirect", {"from_key": frm, "to_key": to,
                                                     "to_id": name, "via": ",".join(via)})
        except Exception as e:  # the research goes on; the old key just stays
            log.warning("run %s: board redirect %s → %s failed: %s", self.run_id, frm, to, e)
            return ""
        if not (isinstance(r, dict) and r.get("redirected")):
            return ""
        self._board_version += 1
        return f"доска: объект {r.get('from', frm)} теперь {to} (в источнике «{name}»)"

    async def more(self, call_id: str, offset: int = 0) -> str:
        """Next rows (or characters) of a stored source result — the ``more`` tool."""
        cid = self.short_id(None)
        args = {"call_id": call_id, "offset": offset}
        await self.emitter.emit("tool_call", call_id=cid, server="lens", tool="more", args=args)
        t0 = time.monotonic()
        info = self.registry.get(str(call_id))
        payload = self._payloads.get(info.call_id) if info else None
        if payload is None:
            msg = f"нет результата источника с call_id {call_id!r}"
            await self._result(cid, ok=False, t0=t0, error=msg)
            self._stall()
            return msg
        offset = max(0, int(offset or 0))
        view = render(info.call_id, payload, self.limits.result_chars, offset)
        if view is None:
            text = _text(payload)
            n = self.limits.result_chars
            chunk = text[offset:offset + n]
            nxt = offset + n
            view = (f"call_id={info.call_id} символы {offset}–{offset + len(chunk)} из "
                    f"{len(text)}\n{chunk}"
                    + (f"\n…ещё: more(call_id=\"{info.call_id}\", offset={nxt})"
                       if nxt < len(text) else ""), nxt < len(text))
            empty = not chunk
        else:
            empty = offset >= len(self._parsed(info.call_id)[0])
        text, truncated = view
        await self._result(cid, ok=True, t0=t0, text=text, truncated=truncated)
        if empty:
            self._stall()
        else:
            self._progress()
        return text

    def _namespaces(self) -> list[str]:
        return list(dict.fromkeys(i.namespace for i in self.registry.values()))

    def _as_key(self, value: Any, ns: str | None) -> str:
        """A relation end as a board key: keep ``ns:…`` keys, turn an object id / label into
        ``make_key(ns, …)`` (models write "Алексей Лихачёв" where the board wants
        "kb:алексей лихачев")."""
        v = str(value or "").strip()
        spaces = self._namespaces()
        if any(v.startswith(f"{n}:") for n in spaces) or not v:
            return v
        if ns is None:  # no call_id: the namespace whose key for it was written this run
            ns = next((n for n in spaces if make_key(n, v) in self._object_src),
                      spaces[0] if len(spaces) == 1 else None)
        return make_key(ns, v) if ns else v

    def _parsed(self, call_id: str) -> tuple[list[Row], list]:
        if call_id not in self._rows:
            payload = self._payloads.get(call_id)
            self._rows[call_id] = (entity_rows(payload), relation_rows(payload))
        return self._rows[call_id]

    def _source_calls(self) -> list[CallInfo]:
        """Distinct stored source calls of this run, latest first."""
        seen: dict[str, CallInfo] = {}
        for info in self.registry.values():
            seen.setdefault(info.call_id, info)
        return list(reversed(list(seen.values())))

    @staticmethod
    def _src(info: CallInfo) -> dict[str, str]:
        return {"server": info.server, "tool": info.tool, "call_id": info.call_id,
                "namespace": info.namespace}

    def _attach_objects(self, items: Any) -> tuple[list[dict], list[dict]]:
        ok, rejected = [], []
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                rejected.append({"item": it, "reason": "ожидался объект"})
                continue
            ref = str(it.get("call_id") or "").strip()
            info = self.registry.get(ref)
            if ref and info is None:
                rejected.append({"item": it, "reason": f"неизвестный call_id {ref!r} — укажи "
                                 "call_id из результата инструмента-источника этого запроса"})
                continue
            candidates = [info] if info else self._source_calls()
            hit = next(((i, r) for i in candidates
                        if (r := match_entity(self._parsed(i.call_id)[0], it)) is not None), None)
            if hit is None:
                rows = self._parsed(candidates[0].call_id)[0] if candidates else []
                where = f"результате {info.call_id}" if info else "результатах этого запроса"
                rejected.append({"item": it, "reason": (
                    f"в {where} нет такой сущности — укажи row, id или label строки из результата "
                    "(название и тип берутся из источника, придумывать нельзя)"),
                    "nearest": [{"row": r.index, "id": r.id, "label": r.label}
                                for r in nearest(rows, it, 3)]})
                continue
            info, row = hit
            clean: dict[str, Any] = {"id": row.id, "label": row.label, "type": row.type,
                                     "attrs": {"source_id": row.id},
                                     "source": self._src(info)}
            if row.description:
                clean["description"] = row.description[:1000]
            key = make_key(info.namespace, row.id)
            self._object_src.setdefault(key, info)
            self._object_names[key] = set(row.names)
            ok.append(clean)
        return ok, rejected

    async def _names(self, key: str, call_tool) -> set[str]:
        """Source names of a board object: written this run, else read from the board."""
        if key not in self._object_names:
            names = {key.split(":", 1)[-1]}
            try:
                o = await call_tool("get_object", {"key": key}, None)
            except Exception:
                o = None
            if isinstance(o, dict):
                attrs = o.get("attrs") if isinstance(o.get("attrs"), dict) else {}
                names |= {normalize_id(str(v)) for v in (o.get("label"), attrs.get("source_id"))
                          if v}
            self._object_names[key] = names
        return self._object_names[key]

    async def _attach_relations(self, items: Any, call_tool) -> tuple[list[dict], list[dict]]:
        ok, rejected = [], []
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                rejected.append({"item": it, "reason": "ожидался объект"})
                continue
            ref = str(it.get("call_id") or "").strip()
            info = self.registry.get(ref)
            if ref and info is None:
                rejected.append({"item": it, "reason": f"неизвестный call_id {ref!r}"})
                continue
            ns = info.namespace if info else None
            a, b = self._as_key(it.get("from"), ns), self._as_key(it.get("to"), ns)
            na, nb = await self._names(a, call_tool), await self._names(b, call_tool)
            candidates = [info] if info else self._source_calls()
            hit = next(((i, r) for i in candidates
                        if (r := match_relation(self._parsed(i.call_id)[1], na, nb)) is not None),
                       None)
            if hit is None:
                rejected.append({"item": it, "reason": (
                    f"в результатах источников нет связи между {a} и {b} — добавляй только "
                    "связи, которые есть в результате")})
                continue
            info, rel = hit
            src_first = normalize_id(rel.src) in {normalize_id(x) for x in na}
            ok.append({"from": a if src_first else b, "to": b if src_first else a,
                       "kind": rel.kind or it.get("kind") or "", "source": self._src(info)})
        return ok, rejected

    async def _board(self, cid: str, call_tool, name: str, args: dict[str, Any]) -> Any:
        t0 = time.monotonic()
        if self.counts["board"] >= self.limits.board_calls:
            msg = (f"лимит вызовов доски исчерпан ({self.limits.board_calls}) — "
                   "заверши ответ")
            await self._result(cid, ok=False, t0=t0, error=msg)
            self._stall()
            return msg
        read_key = None
        if name in _BOARD_READS:
            # get_board is a repeat whatever its limit/include_hidden: the board is the same
            read_args = {} if name == "get_board" else args
            read_key = json.dumps([name, read_args, self._board_version], sort_keys=True,
                                  ensure_ascii=False, default=str)
            first = self._board_reads.get(read_key)
            if first is not None:
                msg = (f"(повтор {first}: доска не менялась с того вызова) — снова её не "
                       "запрашивай. Добавь объекты (board_add_objects с call_id из результатов "
                       "источников) или заверши ответ.")
                await self._result(cid, ok=True, t0=t0, text=msg, cached_from=first)
                self._stall()
                return msg
        self.counts["board"] += 1
        if name in _BOARD_WRITES:
            field = _BOARD_WRITES[name]
            if field == "objects":
                items, rejected = self._attach_objects(args.get(field))
            else:
                items, rejected = await self._attach_relations(args.get(field), call_tool)
            if items:
                result = await self._call(cid, t0, call_tool, name, {field: items})
            else:
                result = {"added": 0, "rejected": []}
            result = {**result, "rejected": rejected + list(result.get("rejected", []))}
        else:
            result = await self._call(cid, t0, call_tool, name, args)
        await self.store.save_payload(CallPayload(run_id=self.run_id, call_id=cid,
                                                  server="board", tool=name, args=args,
                                                  payload=result))
        if read_key is not None:
            self._board_reads[read_key] = cid
        elif _changed(name, result):  # a real change: reads must see it; the run moves on
            self._board_version += 1
            self._progress()
        if name == "add_note":
            self.note_written = True
        elif name == "undo":
            self.undone = True
        await self._result(cid, ok=True, t0=t0, text=_text(result), result=result)
        self._stall_after_board(name, result)
        return result
