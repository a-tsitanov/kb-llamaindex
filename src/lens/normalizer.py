"""Turn one raw MCP response into canvas elements via a validated view-spec.

Order: error/empty response → raw (no LLM); cached spec → materialize; else LLM →
validate → at most one repair → raw.  Any LLM/transport failure degrades to raw —
normalization never fails the whole input.  The cache key includes the model and
the prompt version, so switching either invalidates old specs.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Literal

from loguru import logger
from pydantic import ValidationError

from src.lens.llm import LLMClient
from src.lens.model import RawEl, ToolCallRecord
from src.lens.shape import sample_json
from src.lens.spec import Materialized, SpecError, ViewSpec, materialize
from src.lens.store import LensStore

PROMPT_VERSION = "v2"

SYSTEM = """You convert an MCP tool response into extraction rules for an object canvas.
Return ONLY a JSON object:
{"objects":[{"name":str,"each":path|null,"id":path,"label":path,"type":str,
             "attrs":{attr_name: path}}],
 "relations":[{"each":path,"from_id":path,"to_each":path|null,"to_id":path,"kind":str}]}
Path syntax: "$" then ".key", "[n]", "[*]", ["key with spaces"].
Path scopes:
- "each" is an absolute path to a list of items (or null: the whole response is ONE object).
- other paths are relative to ONE item and start with "$";
  "$root..." reads the whole response, "$args..." reads the tool call arguments
  (use them for the entity a call was ABOUT, e.g. the centre of a neighbours list).
- relation: from_id relative to the item; to_each relative to the item (a list of targets)
  or null (target = the item itself); to_id relative to the target.
  Endpoints may be objects already on the canvas (listed below) — use the same ids.
- "type" MUST be one of the vocabulary.
- NEVER copy values from the response; only write paths.
- Prefer stable identifiers (ids, qids, ips, domains) for "id"; human names for "label".
- If nothing in the response is an object (plain prose, counts only), return {"objects":[]}.
"""

_SPEC_ERRORS = (ValueError, ValidationError, SpecError)


@dataclass
class NormalizeResult:
    materialized: Materialized | None
    raw: RawEl | None
    source: Literal["cache", "llm", "repair", "raw"]


def is_empty_result(payload: Any) -> bool:
    """True when there is nothing object-like: no strings and no non-empty containers
    anywhere (e.g. ``{"results": [], "total": 0}``)."""
    if payload is None:
        return True
    if isinstance(payload, str):
        return not payload.strip()
    if isinstance(payload, (bool, int, float)):
        return True
    if isinstance(payload, dict):
        return all(is_empty_result(v) for v in payload.values())
    if isinstance(payload, list):
        return all(is_empty_result(v) for v in payload)
    return False


def _has_object_lists(payload: Any) -> bool:
    if isinstance(payload, list):
        return any(isinstance(x, dict) for x in payload) or any(
            _has_object_lists(x) for x in payload)
    if isinstance(payload, dict):
        return any(_has_object_lists(v) for v in payload.values())
    return False


def build_prompt(
    call: ToolCallRecord,
    tool_description: str,
    vocabulary: list[str],
    sample_chars: int,
    known_keys: Collection[str] = (),
) -> list[dict]:
    # Caller order matters: the Agent passes mentions first, then the most recently
    # added canvas objects, then everything else — so when there are more than 50
    # candidates, the ones most relevant to this request survive the cap.
    prefix = f"{call.ns}:"
    seen: set[str] = set()
    known: list[str] = []
    for k in known_keys:
        if not k.startswith(prefix) or k in seen:
            continue
        seen.add(k)
        known.append(k)
        if len(known) >= 50:
            break
    user = (
        f"Tool: {call.server}.{call.tool}\n"
        f"Description: {tool_description or '-'}\n"
        f"Arguments: {json.dumps(call.args, ensure_ascii=False)}\n"
        f"Vocabulary: {', '.join(vocabulary)}\n"
        f"On canvas (id space {call.ns!r}): {', '.join(known) or '-'}\n"
        f"Response sample:\n{sample_json(call.payload, sample_chars)}"
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


class Normalizer:
    def __init__(
        self,
        llm: LLMClient,
        store: LensStore,
        *,
        model: str,
        vocabulary: list[str],
        aggregate_threshold: int,
        sample_chars: int,
    ) -> None:
        self.llm, self.store, self.model = llm, store, model
        self.vocabulary, self.threshold = vocabulary, aggregate_threshold
        self.sample_chars = sample_chars
        self._salt = hashlib.sha1(f"{model}|{PROMPT_VERSION}".encode()).hexdigest()[:8]

    def cache_key(self, call: ToolCallRecord) -> str:
        return f"{call.shape_hash}:{self._salt}"

    def _raw(self, call: ToolCallRecord, reason: str) -> NormalizeResult:
        return NormalizeResult(None, RawEl(key=f"raw:{call.id}", call_id=call.id,
                                           reason=reason), "raw")

    def _materialize(
        self, spec: ViewSpec, call: ToolCallRecord, known_keys: Collection[str],
    ) -> Materialized:
        return materialize(spec, call.payload, namespace=call.ns, call_id=call.id,
                           vocabulary=self.vocabulary, aggregate_threshold=self.threshold,
                           args=call.args, known_keys=known_keys)

    async def normalize(
        self,
        call: ToolCallRecord,
        tool_description: str,
        known_keys: Collection[str] = (),
    ) -> NormalizeResult:
        if call.is_error:
            return self._raw(call, f"tool error: {call.error}")
        if is_empty_result(call.payload):
            return self._raw(call, "empty result")

        key = self.cache_key(call)
        cached = await self.store.get_spec(call.server, call.tool, key)
        if cached is not None:
            if not cached.objects:
                return self._raw(call, "no objects in response")
            try:
                m = self._materialize(cached, call, known_keys)
                if not m.is_empty():
                    return NormalizeResult(m, None, "cache")
            except SpecError as e:
                logger.info("lens: cached spec failed for {}.{}: {}", call.server, call.tool, e)

        messages = build_prompt(call, tool_description, self.vocabulary, self.sample_chars,
                                known_keys)
        for attempt, source in enumerate(("llm", "repair")):
            raw: dict = {}
            try:
                raw = await self.llm.json(model=self.model, messages=messages)
                spec = ViewSpec.model_validate(raw)
                if not spec.objects:
                    # An "empty" verdict on a response that does contain lists of
                    # records is suspicious (flaky model): don't cache it.
                    if not _has_object_lists(call.payload):
                        await self.store.put_spec(call.server, call.tool, key, spec,
                                                  self.model)
                    return self._raw(call, "no objects in response")
                m = self._materialize(spec, call, known_keys)
            except _SPEC_ERRORS as e:
                if attempt == 1:
                    return self._raw(call, f"normalization failed: {e}")
                messages = [*messages,
                            {"role": "assistant", "content": json.dumps(raw, ensure_ascii=False)},
                            {"role": "user", "content": (
                                f"Those rules are invalid: {e}\n"
                                "Fix them and return the full corrected JSON only.")}]
                continue
            except Exception as e:  # LLM transport/timeouts: degrade, never fail the input
                logger.warning("lens: normalizer LLM failed for {}.{}: {}",
                               call.server, call.tool, e)
                return self._raw(call, f"normalizer unavailable: {e}")
            if m.is_empty():
                return self._raw(call, "no objects in response")
            await self.store.put_spec(call.server, call.tool, key, spec, self.model)
            return NormalizeResult(m, None, source)  # type: ignore[arg-type]
        return self._raw(call, "normalization failed")
