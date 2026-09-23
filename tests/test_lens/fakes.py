"""Scripted fakes shared by Lens tests."""

from __future__ import annotations

from src.lens.llm import ChatReply


class FakeLLM:
    def __init__(self, chat_replies=None, json_replies=None):
        self.chat_replies = list(chat_replies or [])
        self.json_replies = list(json_replies or [])
        self.chat_calls: list[dict] = []
        self.json_calls: list[dict] = []

    async def chat(self, *, model, messages, tools=None, tool_choice=None):
        self.chat_calls.append({"model": model, "messages": list(messages), "tools": tools,
                                "tool_choice": tool_choice})
        if not self.chat_replies:
            return ChatReply(text="(no more scripted replies)")
        return self.chat_replies.pop(0)

    async def json(self, *, model, messages):
        self.json_calls.append({"model": model, "messages": list(messages)})
        reply = self.json_replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
