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
  full ``source {server, tool, call_id, namespace}``; unknown ids are rejected with a reason.
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


def _text(result: Any) -> str:
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False,
                                                             default=str)


def _summary(result: Any, text: str) -> dict[str, Any]:
    items = None
    if isinstance(result, list):
        items = len(result)
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
            return f"(повтор вызова {first}, тот же результат)\n{model_text}"
        if self.counts["source"] >= self.limits.source_calls:
            msg = (f"лимит вызовов источников исчерпан ({self.limits.source_calls}) — "
                   "завершай с тем, что есть")
            await self._result(cid, ok=False, t0=t0, error=msg)
            return msg
        self.counts["source"] += 1
        result = await self._call(cid, t0, call_tool, name, args)
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
        if name == "add_note":
            self.note_written = True
        elif name == "undo":
            self.undone = True
        await self._result(cid, ok=True, t0=t0, text=_text(result), result=result)
        return result
