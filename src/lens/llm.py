"""OpenAI-compatible chat client (LiteLLM proxy) for tool-use and JSON output."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import AsyncOpenAI, BadRequestError

from src.config import settings

_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


@dataclass
class ToolCallReq:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatReply:
    text: str | None
    tool_calls: list[ToolCallReq] = field(default_factory=list)


class LLMClient(Protocol):
    async def chat(
        self, *, model: str, messages: list[dict], tools: list[dict] | None = None,
        tool_choice: str | None = None,
    ) -> ChatReply: ...

    async def json(self, *, model: str, messages: list[dict]) -> dict: ...


def extract_json(text: str) -> dict:
    text = (text or "").strip()
    candidates = [text]
    m = _FENCE.search(text)
    if m:
        candidates.insert(0, m.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for c in candidates:
        try:
            v = json.loads(c)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(v, dict):
            return v
    raise ValueError(f"no JSON object in LLM output: {text[:200]!r}")


def _args(raw: str | None) -> dict:
    try:
        v = json.loads(raw or "{}")
    except (json.JSONDecodeError, ValueError):
        return {}
    return v if isinstance(v, dict) else {}


class OpenAICompatLLM:
    def __init__(self, client: Any | None = None) -> None:
        self._no_json_mode: set[str] = set()
        self._client = client or AsyncOpenAI(
            base_url=settings.litellm.base_url,
            api_key=settings.litellm.api_key.get_secret_value(),
            timeout=settings.litellm.timeout_s,
            max_retries=settings.litellm.max_retries,
        )

    async def chat(
        self, *, model: str, messages: list[dict], tools: list[dict] | None = None,
        tool_choice: str | None = None,
    ) -> ChatReply:
        kwargs: dict[str, Any] = {"model": model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            if tool_choice:
                kwargs["tool_choice"] = tool_choice
        resp = await self._client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        calls = [
            ToolCallReq(id=tc.id, name=tc.function.name, arguments=_args(tc.function.arguments))
            for tc in (msg.tool_calls or [])
            if getattr(tc, "type", "function") == "function"  # skip custom tool calls
        ]
        return ChatReply(text=msg.content, tool_calls=calls)

    async def json(self, *, model: str, messages: list[dict]) -> dict:
        if model not in self._no_json_mode:
            try:
                resp = await self._client.chat.completions.create(
                    model=model, messages=messages, response_format={"type": "json_object"},
                )
                return extract_json(resp.choices[0].message.content or "")
            except BadRequestError as e:
                # Some backends (MLX in Unsloth Studio, plain servers) have no JSON mode:
                # remember that and ask for plain text — extract_json handles fences.
                if "response_format" not in str(e):
                    raise
                self._no_json_mode.add(model)
        resp = await self._client.chat.completions.create(model=model, messages=messages)
        return extract_json(resp.choices[0].message.content or "")
