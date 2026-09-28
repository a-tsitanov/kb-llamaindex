from types import SimpleNamespace

import pytest

from src.lens.llm import OpenAICompatLLM, extract_json


def test_extract_json_plain_and_fenced():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('Вот:\n```json\n{"a": 2}\n```\nготово') == {"a": 2}
    with pytest.raises(ValueError):
        extract_json("no json here")


class _FakeCompletions:
    def __init__(self, message):
        self.message = message
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=self.message)])


def _client(message):
    comp = _FakeCompletions(message)
    return SimpleNamespace(chat=SimpleNamespace(completions=comp)), comp


async def test_chat_parses_tool_calls():
    msg = SimpleNamespace(content=None, tool_calls=[SimpleNamespace(
        id="t1", function=SimpleNamespace(name="kb__find", arguments='{"name": "X"}'))])
    client, comp = _client(msg)
    reply = await OpenAICompatLLM(client).chat(model="m", messages=[], tools=[{"x": 1}])
    assert reply.tool_calls[0].name == "kb__find"
    assert reply.tool_calls[0].arguments == {"name": "X"}
    assert comp.kwargs["tools"] == [{"x": 1}]


async def test_chat_bad_tool_arguments_become_empty_dict():
    msg = SimpleNamespace(content="", tool_calls=[SimpleNamespace(
        id="t1", function=SimpleNamespace(name="kb__find", arguments="{oops"))])
    client, _ = _client(msg)
    reply = await OpenAICompatLLM(client).chat(model="m", messages=[])
    assert reply.tool_calls[0].arguments == {}


async def test_json_uses_json_mode():
    client, comp = _client(SimpleNamespace(content='{"objects": []}', tool_calls=None))
    out = await OpenAICompatLLM(client).json(model="m", messages=[{"role": "user",
                                                                   "content": "x"}])
    assert out == {"objects": []}
    assert comp.kwargs["response_format"] == {"type": "json_object"}
    assert "tools" not in comp.kwargs


async def test_chat_skips_custom_tool_calls_and_passes_tool_choice():
    msg = SimpleNamespace(content="x", tool_calls=[
        SimpleNamespace(type="custom", id="c1", custom=SimpleNamespace(name="x", input="")),
        SimpleNamespace(type="function", id="t1",
                        function=SimpleNamespace(name="kb__find", arguments="{}")),
    ])
    client, comp = _client(msg)
    reply = await OpenAICompatLLM(client).chat(model="m", messages=[], tools=[{"x": 1}],
                                               tool_choice="none")
    assert [c.id for c in reply.tool_calls] == ["t1"]
    assert comp.kwargs["tool_choice"] == "none"


class _NoJsonModeCompletions:
    """Backend without response_format support (e.g. MLX in Unsloth Studio)."""

    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        import httpx
        from openai import BadRequestError

        self.calls.append(kwargs)
        if "response_format" in kwargs:
            req = httpx.Request("POST", "http://x/v1/chat/completions")
            raise BadRequestError(
                "response_format needs the llama.cpp grammar engine",
                response=httpx.Response(400, request=req), body=None)
        msg = SimpleNamespace(content='Вот:\n```json\n{"objects": []}\n```', tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


async def test_json_falls_back_when_backend_rejects_response_format():
    comp = _NoJsonModeCompletions()
    llm = OpenAICompatLLM(SimpleNamespace(chat=SimpleNamespace(completions=comp)))
    assert await llm.json(model="m", messages=[]) == {"objects": []}
    assert await llm.json(model="m", messages=[]) == {"objects": []}
    # first call: rejected + retried; second call goes straight to plain mode
    assert ["response_format" in c for c in comp.calls] == [True, False, False]
