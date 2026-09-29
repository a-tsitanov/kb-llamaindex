"""Per-run tool-call guard: the ``process_tool_call`` hook of every MCP server.

What the model cannot be trusted with happens here:
- every call gets a fresh short ``call_id`` (c1, c2 …) that the model sees in source results
  and cites in board writes; the journal (``tool_call``/``tool_result``) uses the same id.
  Provider tool-call ids are not trusted to be unique (some backends restart them each turn);
- tool calls of a run are sequential (see ``runner``), so an identical call in the same turn
  already finds the first one's result in the cache;
- source results are stored in full and cut to ``result_chars`` for the model;
- an identical repeated source call is answered from the run cache (not counted twice);
- soft budgets per kind (source / board): over budget the call is not made and the model is
  told to finish with what it has;
- board writes: ``call_id`` is checked against this run's source calls and replaced by the
  full ``source {server, tool, call_id, namespace}``; unknown ids are rejected with a reason;
- board reads repeated while this run has not changed the board are answered from the cache
  with a nudge to add objects or answer (a weak model otherwise re-reads the board in a loop);
- consecutive calls that bring nothing new (cache hits, over-budget calls) are counted; at
  ``stall_calls`` the run is stopped (``RunStalled``) instead of burning the run timeout.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

from pydantic_ai import ModelRetry

from src.lens_agent.config import McpEntry
from src.lens_agent.store import AgentStore, CallPayload
from src.lens_agent.stream import RunEmitter

_BOARD_WRITES = {"add_objects": "objects", "add_relations": "relations"}
_BOARD_READS = ("get_board", "find_on_board", "get_object")


def _changed(name: str, result: Any) -> bool:
    """Did this board call change the board? Writes count only if something landed."""
    if name not in _BOARD_WRITES:
        return True  # note, hide/show, merge, undo
    return isinstance(result, dict) and (bool(result.get("added")) or bool(result.get("merged")))


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
        self._board_version = 0  # bumped by every board change this run makes
        self._board_reads: dict[str, str] = {}  # read key (incl. version) -> first call id
        self.stalls = 0  # consecutive calls that brought nothing new

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
        truncated = len(text) > n
        body = text[:n] + (f"\n…усечено, полный результат: call_id={cid}" if truncated else "")
        model_text = f"call_id={cid}\n{body}"
        self.registry[cid] = CallInfo(cid, entry.name, name, entry.ns)
        self._cache[key] = (cid, model_text)
        await self._result(cid, ok=True, t0=t0, text=text, result=result, truncated=truncated)
        return model_text

    def _attach_sources(self, items: Any) -> tuple[list[dict], list[dict]]:
        ok, rejected = [], []
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                rejected.append({"item": it, "reason": "ожидался объект"})
                continue
            ref = str(it.get("call_id") or "").strip()
            info = self.registry.get(ref)
            if info is None:
                rejected.append({"item": it, "reason": f"неизвестный call_id {ref!r} — укажи "
                                 "call_id из результата инструмента-источника этого запроса"})
                continue
            clean = {k: v for k, v in it.items() if k not in ("call_id", "source")}
            clean["source"] = {"server": info.server, "tool": info.tool,
                               "call_id": info.call_id, "namespace": info.namespace}
            ok.append(clean)
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
            items, rejected = self._attach_sources(args.get(field))
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
