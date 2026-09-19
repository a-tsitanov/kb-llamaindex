"""NuExtract3 (numind) template-extraction backend for ``ner_eval``.

NuExtract3 is a 4B Qwen3.5-derived extraction model: instead of a
free-form prompt it takes a JSON *template* whose leaves declare the
wanted type (``verbatim-string`` = span copied from the document) and
answers with JSON matching that template.  It emits NO relations and no
descriptions, so — exactly like ``gliner_extract`` — it can only ever be
an entity-stage candidate, never a drop-in for the LightRAG extractor.

Wire path is Ollama ``/api/generate`` with ``raw=True``: the model's own
chat template needs custom kwargs (``template``, ``mode``,
``enable_thinking``) that neither Ollama's ``/api/chat`` nor its
OpenAI-compatible endpoint can forward, so the 【task】/【template】/
【document】 prompt from ``chat_template.jinja`` is rendered here
verbatim.

Env knobs: ``NUEXTRACT_MODEL`` (default Q8_0 GGUF tag),
``NUEXTRACT_THINK=1`` (reasoning mode), ``OLLAMA_URL``.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

DEFAULT_MODEL = "hf.co/numind/NuExtract3-GGUF:Q8_0"
DEFAULT_OLLAMA = "http://localhost:11434"


def build_prompt(text: str, types: list[str], *, think: bool = False) -> str:
    """Render the structured-mode prompt exactly as chat_template.jinja does."""
    template = json.dumps(
        {t: ["verbatim-string"] for t in types}, ensure_ascii=False, indent=4
    )
    head = (
        "<|im_start|>user\n"
        "【task】structured\n"
        f"【template_start】{template}【template_end】\n"
        "【document_start】\n"
        f"{text}\n"
        "【document_end】<|im_end|>\n"
        "<|im_start|>assistant\n"
    )
    return head + ("<think>\n" if think else "<think>\n\n</think>\n\n")


def _extract_json(raw: str) -> dict[str, Any]:
    """Pull the answer object out of the completion (tolerates fences/think)."""
    s = raw
    if "</think>" in s:
        s = s.split("</think>")[-1]
    s = re.sub(r"^\s*```(?:json)?|```\s*$", "", s.strip(), flags=re.MULTILINE).strip()
    start = s.find("{")
    if start == -1:
        return {}
    depth, end = 0, None
    for i, ch in enumerate(s[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        return {}
    try:
        obj = json.loads(s[start:end])
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _flatten(obj: dict[str, Any], types: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for etype in types:
        val = obj.get(etype)
        if val is None:
            continue
        items = val if isinstance(val, list) else [val]
        for item in items:
            if isinstance(item, str) and item.strip():
                out.append((item.strip(), etype))
    return out


def nuextract_callable(
    model: str | None = None,
    ollama_url: str | None = None,
    *,
    think: bool | None = None,
    num_ctx: int = 8192,
    timeout: float = 300.0,
):
    """Return an ``Extractor`` callable for ``tests/eval/ner_eval.py``."""
    model = model or os.environ.get("NUEXTRACT_MODEL", DEFAULT_MODEL)
    base = (ollama_url or os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA)).rstrip("/")
    if think is None:
        think = os.environ.get("NUEXTRACT_THINK", "0").lower() in {"1", "true", "yes"}
    client = httpx.Client(timeout=timeout)

    def _run(text: str, types: list[str]) -> list[tuple[str, str]]:
        r = client.post(
            f"{base}/api/generate",
            json={
                "model": model,
                "prompt": build_prompt(text, types, think=think),
                "raw": True,
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "num_ctx": num_ctx,
                    "num_predict": 4096 if think else 1024,
                },
            },
        )
        r.raise_for_status()
        return _flatten(_extract_json(r.json().get("response", "")), types)

    return _run
