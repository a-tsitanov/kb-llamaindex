# Lens — Plan 1: Agent Core (backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone backend service (`src/lens/`) that turns one text input into operations on a persistent object canvas by calling MCP tools and normalizing their heterogeneous output through an LLM-written, path-validated view-spec, with an HTTP + SSE API.

**Architecture:** FastAPI app separate from the main API. Input → rule-based Router (workspace commands → ops) or tool-use Planner over all configured MCP servers → every raw tool response stored whole → Normalizer asks the LLM for a *view-spec* of JSONPath rules (never values), validates it by resolving the paths, caches it by `(server, tool, shape_hash + model + prompt version)` → relations may attach to objects already on the canvas / @mentions → materialized objects/relations/aggregates are appended to a per-workspace op log → canvas state is a fold of the log → patches streamed over SSE.

**Tech Stack:** Python 3.12, FastAPI, pydantic v2 / pydantic-settings, fastmcp 3.3 `Client`, `openai` AsyncOpenAI against the existing LiteLLM proxy, psycopg 3 async pool, pytest + pytest-asyncio (`asyncio_mode = "auto"`).

**Spec:** `docs/superpowers/specs/2026-09-22-lens-workspace-design.md`

**Revision 2 (after adversarial review, 2026-09-22):** namespaces instead of server names in keys; `$root`/`$args` path scopes + relations to known canvas objects; dedup before aggregation; full sample when it fits; normalizer degrades to raw on any LLM failure and skips empty results; word/stem router with whole-input commands, `стоп`, `открой`, table filter; MCP lazy reconnect + call timeout + blank-token fix; pins bypass the input lock; SSE `ready`/`resync` + `/ops?after_seq`; own `LENS_API_KEYS` + signed short-lived stream tokens; `same_as?` candidates; per-claim `[[key]]` citations. All code blocks below were executed: 119 passed (+4 PG cases green on a throwaway Postgres 16), ruff clean.

**Plan series:** Plan 1 (this) = agent core + API. Plan 2 = web frontend (canvas, input, SSE client). Plan 3 = Watcher / monitoring (`watch`, `watch_hit`, "+N"). Workspace snapshots (`workspace_snapshot`) are deferred until op logs get long enough to matter — fold-from-zero is used in Plan 1.

## Global Constraints

- **Never `git commit` / `git push` without the user's explicit go-ahead** (user's global rule). Every "Commit" step below means: stage the files, show the diff summary, and ask; commit only after "да/yes".
- All Lens code lives under `src/lens/`; tests under `tests/test_lens/`. Do not modify existing modules except `pyproject.toml` (Task 1) and `docker-compose.prod.yml` (Task 13).
- Lens Postgres tables are prefixed `lens_` and live in the existing DB (`settings.postgres.dsn`).
- Settings use env prefix `LENS_` in their own `LensSettings` class (`src/lens/config.py`).
- `workspace.owner_id` and `lens_ws_member` exist in the schema but are unused (single user in MVP).
- Object key format: `"{namespace}:{id}"` — `namespace` from `McpServerConfig` (all KB servers share `kb`), default = server name. Aggregate key: `"agg:{call_id}:{rule_name}"`. Table key: `"table:{aggregate_key}"`. Raw key: `"raw:{call_id}"`. Note key: `"note:{input_id}"`.
- `ref = {call_id, path}`; the LLM never writes values — every value on the canvas is read from a stored payload by path.
- Type vocabulary default: `person, organization, event, location, document, topic, ip, domain, certificate, service, asn, other`.
- Aggregate threshold default: 25 items per rule.
- Lens auth uses its own `LENS_API_KEYS` (never the main `API_KEYS`); the SSE stream takes a signed, workspace-bound, 5-minute `?token=`.
- Commands in the input are matched against the WHOLE input; anything else is a search.
- Line length 100 (ruff). Run tests with `uv run pytest tests/test_lens -q`.

## Review Focus

1. **A command word inside a real query** ("отмена санкций против России", "объедини усилия ЕС") — expect a search, never an undo/merge. (Task 9 `test_command_words_inside_a_query_are_searches`.)
2. **Results that should attach to what is already on the canvas** ("@Росатом соседи", "@A @B как связаны") — expect edges to the existing objects, not orphan duplicates. (Task 5 `test_relation_to_known_canvas_object_via_root_path`, `test_args_scope`; Task 10 `test_known_keys_attach_relations_and_reach_prompt`.)
3. **LLM or MCP server flaking mid-input** (timeout, restarted server, server not up at boot) — expect a `raw` node / reconnect, never a failed input. (Task 7 `test_transport_failure_reconnects_once_and_passes_timeout`, `test_down_server_recovers_on_refresh_after_backoff`; Task 10 `test_llm_timeout_degrades_to_raw`.)
4. **Repeated entities across rows** (the same 3 participants in 10 meetings) — expect 3 objects with 10 refs, not an aggregate. (Task 5 `test_duplicates_do_not_trigger_aggregate`.)
5. **Russian morphology / short names in commands** ("скрой Путина", "скрой Си" next to "Россия") — expect stem/word matching. (Task 9 `test_declension_matches_by_stem`, `test_word_match_not_substring`.)

---

## File Structure

```
src/lens/
  __init__.py        package marker
  config.py          LensSettings, McpServerConfig, lens_settings
  model.py           Ref, Column, ObjectEl, RelationEl, AggregateEl, TableEl, RawEl, NoteEl,
                     Op, OpKind, Workspace, ToolCallRecord
  paths.py           tiny JSONPath: parse, iter_path, resolve, PathError
  shape.py           shape_hash, skeleton, sample_json
  spec.py            ObjectRule, RelationRule, ViewSpec, Materialized, SpecError, materialize
  state.py           CanvasState, fold, state_to_dict
  store.py           LensStore protocol, MemoryLensStore, PgLensStore, SCHEMA_SQL
  mcp_hub.py         ToolInfo, ToolResult, McpHub
  llm.py             ChatReply, ToolCallReq, LLMClient protocol, OpenAICompatLLM, extract_json
  normalizer.py      NormalizeResult, Normalizer
  router.py          Command, Search, route
  planner.py         PlannerStatus, ToolCalled, PlannerFinal, Planner
  events.py          EventBus, sse_stream
  agent.py           Agent
  auth.py            require_key, make/check_stream_token
  app.py             LensDeps, create_app, app
scripts/
  lens_capture_fixture.py   record a real MCP response as a benchmark fixture
  lens_normalizer_bench.py  run the Normalizer benchmark with the real LLM
tests/test_lens/
  __init__.py, fakes.py, test_*.py
tests/eval/lens_normalizer/
  fixtures/*.json, scoring.py
```

---

### Task 1: Package scaffold, settings, domain models

**Files:**
- Modify: `pyproject.toml` (dependencies list)
- Create: `src/lens/__init__.py`, `src/lens/config.py`, `src/lens/model.py`
- Test: `tests/test_lens/__init__.py`, `tests/test_lens/test_config_model.py`

**Interfaces:**
- Produces:
  - `McpServerConfig(name: str, url: str, namespace: str | None = None, token: SecretStr | None = None)` — blank token → `None`; property `ns` = namespace or name
  - `LensSettings` fields: `mcp_servers: list[McpServerConfig]`, `model_planner: str`, `model_normalizer: str`, `max_tool_steps: int = 6`, `sample_chars: int = 6000`, `aggregate_threshold: int = 25`, `tool_timeout_s: float = 120`, `reconnect_backoff_s: float = 10`, `vocabulary: list[str]`, `api_keys: str`, `stream_secret: SecretStr`, `cors_origins: str`; methods `planner_model()`, `normalizer_model()`, `keys_list()`, `cors_list()`, `stream_secret_value()`
  - `lens_settings: LensSettings`
  - Models in `src/lens/model.py` exactly as in Step 4 (`TableEl.filter`, `NoteEl.calls`, `ToolCallRecord.namespace` + property `ns`).

- [ ] **Step 1: Add explicit `openai` dependency**

In `pyproject.toml` `dependencies`, after the `"httpx>=0.27,<1",` entry add:

```toml
    # Lens agent (src/lens): OpenAI-compatible chat + tool calling against the
    # LiteLLM proxy. Already present transitively via llama-index; pinned
    # explicitly because Lens imports it directly.
    "openai>=1.50,<2",
```

Run: `uv lock && uv sync --extra dev`
Expected: lock resolves, `openai` stays at 1.109.x.

- [ ] **Step 2: Write the failing test**

`tests/test_lens/__init__.py`: empty file.

`tests/test_lens/test_config_model.py`:

```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.lens.config import LensSettings
from src.lens.model import (
    AggregateEl,
    Column,
    ObjectEl,
    Op,
    Ref,
    RelationEl,
)


def test_mcp_servers_parse_from_json_env(monkeypatch):
    monkeypatch.setenv(
        "LENS_MCP_SERVERS",
        '[{"name":"kb-tools","url":"http://mcp-tools:9002/mcp","token":"k1"}]',
    )
    s = LensSettings()
    assert s.mcp_servers[0].name == "kb-tools"
    assert s.mcp_servers[0].token.get_secret_value() == "k1"


def test_role_models_fall_back_to_litellm_large(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings.litellm, "model_large", "big-model")
    s = LensSettings(model_planner="", model_normalizer="norm")
    assert s.planner_model() == "big-model"
    assert s.normalizer_model() == "norm"


def test_default_vocabulary_contains_core_types():
    s = LensSettings()
    assert {"person", "organization", "event", "ip", "certificate", "other"} <= set(s.vocabulary)


def test_relation_key_is_stable():
    r = RelationEl(from_key="kb:1", to_key="kb:2", kind="участник")
    assert r.key == "kb:1|участник|kb:2"


def test_aggregate_has_kind_discriminator():
    a = AggregateEl(
        key="agg:c1:hosts", label="ip · 30", item_type="ip", count=30,
        rows_ref=Ref(call_id="c1", path="$.hosts[*]"),
        columns=[Column(name="id", path="$.ip")],
    )
    assert a.model_dump()["kind"] == "aggregate"


def test_op_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        Op(workspace_id="w", seq=1, kind="explode", payload={}, input_id=None,
           created_at=datetime.now(UTC))


def test_object_defaults():
    o = ObjectEl(key="kb:1", type="person", label="X")
    assert o.attrs == {} and o.refs == []


def test_namespace_keys_and_cors_lists():
    s = LensSettings(api_keys=" a, b ,", cors_origins="http://x, http://y")
    assert s.keys_list() == ["a", "b"] and s.cors_list() == ["http://x", "http://y"]
    assert s.stream_secret_value() == "a"
    s2 = LensSettings(mcp_servers=[{"name": "kb-tools", "namespace": "kb", "url": "u"}])
    assert s2.mcp_servers[0].ns == "kb"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_lens/test_config_model.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens'`

- [ ] **Step 4: Implement**

`src/lens/__init__.py`:

```python
"""Lens — object-centric research workspace over MCP sources."""
```

`src/lens/config.py`:

```python
"""Lens settings (env prefix ``LENS_``).

``LENS_MCP_SERVERS`` is a JSON list, e.g.
``[{"name":"kb-tools","namespace":"kb","url":"http://mcp-tools:9002/mcp","token":"<key>"}]``.
``namespace`` groups servers that share one id space (all KB servers → ``kb``) so the
same entity from two servers gets one canvas key.  Role models default to the
LiteLLM large tier: planning and normalization need reliable tool-use + JSON.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.config import settings

DEFAULT_VOCABULARY = [
    "person", "organization", "event", "location", "document", "topic",
    "ip", "domain", "certificate", "service", "asn", "other",
]


class McpServerConfig(BaseModel):
    name: str
    url: str
    namespace: str | None = None
    token: SecretStr | None = None

    @field_validator("token", mode="before")
    @classmethod
    def _blank_token_is_none(cls, v: object) -> object:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return v

    @property
    def ns(self) -> str:
        return self.namespace or self.name


class LensSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LENS_", env_file=".env", extra="ignore")

    mcp_servers: list[McpServerConfig] = Field(default_factory=list)
    model_planner: str = ""
    model_normalizer: str = ""
    max_tool_steps: int = 6
    sample_chars: int = 6000
    aggregate_threshold: int = 25
    tool_timeout_s: float = 120.0
    reconnect_backoff_s: float = 10.0
    vocabulary: list[str] = Field(default_factory=lambda: list(DEFAULT_VOCABULARY))
    # Lens has its own keys: never reuse the main KB API keys (they would leak
    # through the SSE stream URL otherwise).
    api_keys: str = "dev-lens-key"
    stream_secret: SecretStr = SecretStr("")
    cors_origins: str = "http://localhost:5173"

    def planner_model(self) -> str:
        return self.model_planner or settings.litellm.model_large

    def normalizer_model(self) -> str:
        return self.model_normalizer or settings.litellm.model_large

    def keys_list(self) -> list[str]:
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]

    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def stream_secret_value(self) -> str:
        return self.stream_secret.get_secret_value() or (self.keys_list() or [""])[0]


lens_settings = LensSettings()
```

`src/lens/model.py`:

```python
"""Lens domain models: canvas elements, ops, workspaces, tool calls."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Ref(BaseModel):
    call_id: str
    path: str


class Column(BaseModel):
    name: str
    path: str  # relative to one row, starts with "$"


class ObjectEl(BaseModel):
    key: str
    type: str
    label: str
    attrs: dict[str, Any] = Field(default_factory=dict)
    refs: list[Ref] = Field(default_factory=list)


class RelationEl(BaseModel):
    from_key: str
    to_key: str
    kind: str
    confidence: float = 1.0
    refs: list[Ref] = Field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.from_key}|{self.kind}|{self.to_key}"


class AggregateEl(BaseModel):
    kind: Literal["aggregate"] = "aggregate"
    key: str
    label: str
    item_type: str
    count: int
    rows_ref: Ref
    columns: list[Column]


class TableEl(BaseModel):
    kind: Literal["table"] = "table"
    key: str
    source_key: str
    rows_ref: Ref
    columns: list[Column]
    # column name (or "*" = any column) → accepted values, compared as strings
    filter: dict[str, list[str]] = Field(default_factory=dict)


class RawEl(BaseModel):
    kind: Literal["raw"] = "raw"
    key: str
    call_id: str
    reason: str


class NoteEl(BaseModel):
    key: str
    text: str
    cites: list[str] = Field(default_factory=list)  # object keys the text marks as [[key]]
    calls: list[str] = Field(default_factory=list)  # tool call ids behind this answer


OpKind = Literal[
    "add_objects", "add_relations", "add_view", "add_note",
    "hide", "show", "pin", "unpin", "set_mode", "merge", "undo",
]


class Op(BaseModel):
    workspace_id: str
    seq: int
    kind: OpKind
    payload: dict[str, Any]
    input_id: str | None
    created_at: datetime


class Workspace(BaseModel):
    id: str
    title: str
    owner_id: str | None = None
    created_at: datetime


class ToolCallRecord(BaseModel):
    id: str
    input_id: str | None
    server: str
    namespace: str | None = None  # id space for canvas keys; None = server name
    tool: str
    args: dict[str, Any]
    payload: Any
    shape_hash: str
    is_error: bool = False
    error: str | None = None
    latency_ms: int

    @property
    def ns(self) -> str:
        return self.namespace or self.server
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_lens/test_config_model.py -q`
Expected: 8 passed

- [ ] **Step 6: Commit (after user go-ahead)**

```bash
git add pyproject.toml uv.lock src/lens/__init__.py src/lens/config.py src/lens/model.py tests/test_lens/
git commit -m "feat(lens): scaffold package, settings and domain models"
```

---

### Task 2: JSONPath resolver

**Files:**
- Create: `src/lens/paths.py`
- Test: `tests/test_lens/test_paths.py`

**Interfaces:**
- Produces:
  - `class PathError(ValueError)`
  - `parse(path: str) -> list[str | int | _Star]`
  - `iter_path(data: Any, path: str) -> list[tuple[str, Any]]` — every match as `(concrete_path, value)`; missing → `[]`; bad syntax → `PathError`
  - `resolve(data: Any, path: str) -> Any` — exactly one match else `PathError`
  - `join(base: str, rel: str) -> str` — `join("$.a[0]", "$.b") == "$.a[0].b"`

Syntax: `$`, `.key` (any chars except `.[]`, Unicode ok), `[n]` (negative ok), `[*]` (list items or dict values), `["key"]` / `['key']`.

- [ ] **Step 1: Write the failing test**

```python
import pytest

from src.lens.paths import PathError, iter_path, join, parse, resolve

DATA = {
    "results": [
        {"id": "Q1", "name": "Росатом", "tags": ["a", "b"]},
        {"id": "Q2", "name": "Си Цзиньпин"},
    ],
    "meta": {"total count": 2},
    "имя": "значение",
}


def test_parse_tokens():
    assert parse("$.results[0].name") == ["results", 0, "name"]
    assert parse('$["total count"]') == ["total count"]


def test_parse_rejects_missing_root():
    with pytest.raises(PathError):
        parse("results[0]")


def test_parse_rejects_garbage():
    with pytest.raises(PathError):
        parse("$.a[x]")


def test_star_expands_with_concrete_paths():
    got = iter_path(DATA, "$.results[*].id")
    assert got == [("$.results[0].id", "Q1"), ("$.results[1].id", "Q2")]


def test_missing_key_yields_empty():
    assert iter_path(DATA, "$.results[*].missing") == []
    assert iter_path(DATA, "$.results[9]") == []


def test_negative_index_is_normalized():
    assert iter_path(DATA, "$.results[-1].id") == [("$.results[1].id", "Q2")]


def test_unicode_and_quoted_keys():
    assert resolve(DATA, "$.имя") == "значение"
    assert resolve(DATA, "$.meta['total count']") == 2
    assert iter_path(DATA, '$.meta["total count"]')[0][0] == '$.meta["total count"]'


def test_star_over_dict_values():
    assert [v for _, v in iter_path({"a": 1, "b": 2}, "$[*]")] == [1, 2]


def test_resolve_requires_single_match():
    with pytest.raises(PathError):
        resolve(DATA, "$.results[*].id")
    with pytest.raises(PathError):
        resolve(DATA, "$.nope")


def test_join():
    assert join("$.results[0]", "$.name") == "$.results[0].name"
    assert join("$.results[0]", "$") == "$.results[0]"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lens/test_paths.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens.paths'`

- [ ] **Step 3: Implement**

```python
"""Minimal JSONPath subset used by view-specs.

Supported: ``$``, ``.key``, ``[n]``, ``[*]``, ``["key"]`` / ``['key']``.
``iter_path`` returns concrete paths so every canvas value can cite exactly
where it came from.
"""

from __future__ import annotations

import json
import re
from typing import Any

_TOKEN = re.compile(
    r"""\.(?P<key>[^.\[\]]+)"""
    r"""|\[(?P<idx>-?\d+)\]"""
    r"""|\[(?P<star>\*)\]"""
    r"""|\[(?P<q>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')\]"""
)
_PLAIN_KEY = re.compile(r"[^.\[\]\s'\"]+")


class PathError(ValueError):
    pass


class _Star:
    def __repr__(self) -> str:
        return "*"


STAR = _Star()


def parse(path: str) -> list[str | int | _Star]:
    if not isinstance(path, str) or not path.startswith("$"):
        raise PathError(f"path must start with '$': {path!r}")
    out: list[str | int | _Star] = []
    pos = 1
    while pos < len(path):
        m = _TOKEN.match(path, pos)
        if m is None:
            raise PathError(f"bad path syntax at {pos}: {path!r}")
        if m["key"] is not None:
            out.append(m["key"])
        elif m["idx"] is not None:
            out.append(int(m["idx"]))
        elif m["star"] is not None:
            out.append(STAR)
        else:
            q = m["q"]
            out.append(json.loads(q) if q[0] == '"' else q[1:-1].replace("\\'", "'"))
        pos = m.end()
    return out


def _fmt_key(key: str) -> str:
    if _PLAIN_KEY.fullmatch(key):
        return f".{key}"
    return f"[{json.dumps(key, ensure_ascii=False)}]"


def iter_path(data: Any, path: str) -> list[tuple[str, Any]]:
    results: list[tuple[str, Any]] = [("$", data)]
    for tok in parse(path):
        nxt: list[tuple[str, Any]] = []
        for cp, val in results:
            if tok is STAR:
                if isinstance(val, list):
                    nxt.extend((f"{cp}[{i}]", v) for i, v in enumerate(val))
                elif isinstance(val, dict):
                    nxt.extend((f"{cp}{_fmt_key(str(k))}", v) for k, v in val.items())
            elif isinstance(tok, int):
                if isinstance(val, list) and -len(val) <= tok < len(val):
                    i = tok % len(val)
                    nxt.append((f"{cp}[{i}]", val[i]))
            elif isinstance(val, dict) and tok in val:
                nxt.append((f"{cp}{_fmt_key(tok)}", val[tok]))
        results = nxt
    return results


def resolve(data: Any, path: str) -> Any:
    matches = iter_path(data, path)
    if len(matches) != 1:
        raise PathError(f"{path!r} matched {len(matches)} values, expected 1")
    return matches[0][1]


def join(base: str, rel: str) -> str:
    if not rel.startswith("$"):
        raise PathError(f"relative path must start with '$': {rel!r}")
    return base + rel[1:]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lens/test_paths.py -q`
Expected: 10 passed

- [ ] **Step 5: Commit (after user go-ahead)**

```bash
git add src/lens/paths.py tests/test_lens/test_paths.py
git commit -m "feat(lens): minimal JSONPath resolver with concrete paths"
```

---

### Task 3: Payload shape hash and bounded sample

**Files:**
- Create: `src/lens/shape.py`
- Test: `tests/test_lens/test_shape.py`

**Interfaces:**
- Produces:
  - `shape_hash(payload: Any) -> str` — 16 hex chars; same for payloads differing only in values or list length (non-empty); differs when keys/types differ
  - `skeleton(payload: Any, max_items: int, max_str: int) -> Any`
  - `sample_json(payload: Any, budget_chars: int = 6000) -> str` — the full JSON when it fits the budget; otherwise a progressively truncated skeleton, `len(result) <= budget_chars + 20`

- [ ] **Step 1: Write the failing test**

```python
import json

from src.lens.shape import sample_json, shape_hash, skeleton


def test_shape_hash_ignores_values_and_length():
    a = {"hosts": [{"ip": "1.1.1.1", "port": 22}]}
    b = {"hosts": [{"ip": "2.2.2.2", "port": 443}, {"ip": "3.3.3.3", "port": 80}]}
    assert shape_hash(a) == shape_hash(b)


def test_shape_hash_sees_key_and_type_changes():
    base = {"hosts": [{"ip": "1.1.1.1", "port": 22}]}
    assert shape_hash(base) != shape_hash({"hosts": [{"ip": "1.1.1.1", "port": "22"}]})
    assert shape_hash(base) != shape_hash({"hosts": [{"ip": "1.1.1.1"}]})


def test_shape_hash_bool_is_not_number():
    assert shape_hash({"x": True}) != shape_hash({"x": 1})


def test_skeleton_truncates_lists_and_strings():
    sk = skeleton({"a": list(range(10)), "s": "x" * 50}, max_items=2, max_str=10)
    assert sk["a"] == [0, 1, "… 8 more"]
    assert sk["s"] == "x" * 10 + "…"


def test_sample_json_respects_budget():
    big = {"hosts": [{"ip": f"10.0.{i // 256}.{i % 256}", "banner": "b" * 500}
                     for i in range(10_000)]}
    out = sample_json(big, budget_chars=2000)
    assert len(out) <= 2020
    assert "10.0.0.0" in out


def test_sample_json_small_payload_is_valid_json():
    assert json.loads(sample_json({"a": [1, 2]})) == {"a": [1, 2]}


def test_sample_json_is_full_when_it_fits():
    payload = {"results": [{"id": f"Q{i}", "name": "x" * 200} for i in range(10)]}
    assert json.loads(sample_json(payload, budget_chars=6000)) == payload
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lens/test_shape.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens.shape'`

- [ ] **Step 3: Implement**

```python
"""Response shape fingerprint (spec-cache key) and LLM-sized samples."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _shape(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _shape(v[k]) for k in sorted(v, key=str)}
    if isinstance(v, list):
        shapes: list[Any] = []
        for item in v[:5]:
            s = _shape(item)
            if s not in shapes:
                shapes.append(s)
        return ["list", shapes]
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    return type(v).__name__


def shape_hash(payload: Any) -> str:
    canon = json.dumps(_shape(payload), sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(canon.encode()).hexdigest()[:16]


def skeleton(payload: Any, max_items: int, max_str: int) -> Any:
    if isinstance(payload, dict):
        return {k: skeleton(v, max_items, max_str) for k, v in payload.items()}
    if isinstance(payload, list):
        out = [skeleton(x, max_items, max_str) for x in payload[:max_items]]
        if len(payload) > max_items:
            out.append(f"… {len(payload) - max_items} more")
        return out
    if isinstance(payload, str) and len(payload) > max_str:
        return payload[:max_str] + "…"
    return payload


def sample_json(payload: Any, budget_chars: int = 6000) -> str:
    """Full JSON when it fits the budget; otherwise progressively truncated."""
    s = json.dumps(payload, ensure_ascii=False)
    if len(s) <= budget_chars:
        return s
    for max_items, max_str in ((3, 120), (2, 80), (1, 60), (1, 30)):
        s = json.dumps(skeleton(payload, max_items, max_str), ensure_ascii=False)
        if len(s) <= budget_chars:
            return s
    return s[:budget_chars] + "…(truncated)"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lens/test_shape.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit (after user go-ahead)**

```bash
git add src/lens/shape.py tests/test_lens/test_shape.py
git commit -m "feat(lens): payload shape hash and bounded LLM sample"
```

---

### Task 4: Canvas state fold

**Files:**
- Create: `src/lens/state.py`
- Test: `tests/test_lens/test_state.py`

**Interfaces:**
- Consumes: `Op`, `ObjectEl`, `RelationEl`, `NoteEl`, `Ref` from `src.lens.model`
- Produces:
  - `@dataclass CanvasState` with fields `objects: dict[str, ObjectEl]`, `object_inputs: dict[str, list[str]]`, `relations: dict[str, RelationEl]`, `views: dict[str, dict]`, `notes: list[NoteEl]`, `hidden: set[str]`, `pins: dict[str, dict[str, float]]`, `mode: str = "canvas"`, `aliases: dict[str, str]`, `inputs: list[str]` (undoable input ids, in order), `last_seq: int = 0`; method `canon(key: str) -> str`
  - `fold(ops: Sequence[Op]) -> CanvasState` — a relation seen again merges its refs
  - `state_to_dict(state: CanvasState) -> dict`

Op payloads (used by every later task):
- `add_objects`: `{"objects": [ObjectEl dict, ...]}`
- `add_relations`: `{"relations": [RelationEl dict, ...]}`
- `add_view`: `{"view": AggregateEl|TableEl|RawEl dict}` (has `kind`, `key`)
- `add_note`: `{"note": NoteEl dict}`
- `hide` / `show`: `{"keys": [str]}`
- `pin`: `{"key": str, "x": float, "y": float}`; `unpin`: `{"key": str}`
- `set_mode`: `{"mode": "canvas" | "table"}`
- `merge`: `{"keep": str, "drop": str}`
- `undo`: `{"input_id": str}` — removes every op of that input from the fold

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime

from src.lens.model import Op
from src.lens.state import fold, state_to_dict

_seq = 0


def op(kind, payload, input_id="i1"):
    global _seq
    _seq += 1
    return Op(workspace_id="w", seq=_seq, kind=kind, payload=payload,
              input_id=input_id, created_at=datetime.now(UTC))


def obj(key, label="L", attrs=None, call="c1"):
    return {"key": key, "type": "person", "label": label, "attrs": attrs or {},
            "refs": [{"call_id": call, "path": "$"}]}


def test_add_objects_merges_same_key():
    st = fold([
        op("add_objects", {"objects": [obj("kb:1", "Си", {"a": 1}, "c1")]}, "i1"),
        op("add_objects", {"objects": [obj("kb:1", "Xi", {"a": 9, "b": 2}, "c2")]}, "i2"),
    ])
    o = st.objects["kb:1"]
    assert o.label == "Си"
    assert o.attrs == {"a": 1, "b": 2}
    assert [r.call_id for r in o.refs] == ["c1", "c2"]
    assert st.object_inputs["kb:1"] == ["i1", "i2"]


def test_hide_show_and_pin():
    st = fold([
        op("add_objects", {"objects": [obj("kb:1")]}),
        op("hide", {"keys": ["kb:1"]}, "i2"),
        op("pin", {"key": "kb:1", "x": 10, "y": 20}, None),
    ])
    assert st.hidden == {"kb:1"}
    assert st.pins["kb:1"] == {"x": 10, "y": 20}
    st2 = fold([*[op("add_objects", {"objects": [obj("kb:1")]})],
                op("hide", {"keys": ["kb:1"]}), op("show", {"keys": ["kb:1"]})])
    assert st2.hidden == set()


def test_undo_removes_whole_input():
    st = fold([
        op("add_objects", {"objects": [obj("kb:1")]}, "i1"),
        op("add_objects", {"objects": [obj("kb:2")]}, "i2"),
        op("add_relations", {"relations": [
            {"from_key": "kb:1", "to_key": "kb:2", "kind": "k"}]}, "i2"),
        op("undo", {"input_id": "i2"}, "i3"),
    ])
    assert set(st.objects) == {"kb:1"}
    assert st.relations == {}
    assert st.inputs == ["i1"]


def test_merge_redirects_objects_relations_and_later_adds():
    st = fold([
        op("add_objects", {"objects": [obj("kb:1", "Росатом"), obj("fofa:x", "ROSATOM"),
                                       obj("kb:2", "Лихачёв")]}),
        op("add_relations", {"relations": [
            {"from_key": "kb:2", "to_key": "fofa:x", "kind": "глава"}]}),
        op("merge", {"keep": "kb:1", "drop": "fofa:x"}, "i2"),
        op("add_objects", {"objects": [obj("fofa:x", "ROSATOM", {"asn": 1}, "c9")]}, "i3"),
    ])
    assert "fofa:x" not in st.objects
    assert st.objects["kb:1"].attrs == {"asn": 1}
    assert list(st.relations) == ["kb:2|глава|kb:1"]
    assert st.canon("fofa:x") == "kb:1"


def test_views_notes_mode():
    st = fold([
        op("add_view", {"view": {"kind": "raw", "key": "raw:c1", "call_id": "c1",
                                 "reason": "x"}}),
        op("add_note", {"note": {"key": "note:i1", "text": "t", "cites": []}}),
        op("set_mode", {"mode": "table"}),
    ])
    assert st.views["raw:c1"]["kind"] == "raw"
    assert st.notes[0].text == "t"
    assert st.mode == "table"


def test_state_to_dict_is_json_ready():
    import json

    st = fold([op("add_objects", {"objects": [obj("kb:1")]}),
               op("hide", {"keys": ["kb:1"]})])
    d = state_to_dict(st)
    json.dumps(d)
    assert d["objects"][0]["hidden"] is True
    assert d["objects"][0]["inputs"] == ["i1"]
    assert d["last_seq"] == st.last_seq


def test_repeated_relation_merges_refs():
    rel = lambda c: {"from_key": "kb:1", "to_key": "kb:2", "kind": "k",  # noqa: E731
                     "refs": [{"call_id": c, "path": "$"}]}
    st = fold([op("add_relations", {"relations": [rel("c1")]}, "i1"),
               op("add_relations", {"relations": [rel("c2")]}, "i2")])
    assert [r.call_id for r in st.relations["kb:1|k|kb:2"].refs] == ["c1", "c2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lens/test_state.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens.state'`

- [ ] **Step 3: Implement**

```python
"""Canvas state = fold of the workspace op log."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from src.lens.model import NoteEl, ObjectEl, Op, RelationEl


@dataclass
class CanvasState:
    objects: dict[str, ObjectEl] = field(default_factory=dict)
    object_inputs: dict[str, list[str]] = field(default_factory=dict)
    relations: dict[str, RelationEl] = field(default_factory=dict)
    views: dict[str, dict[str, Any]] = field(default_factory=dict)
    notes: list[NoteEl] = field(default_factory=list)
    hidden: set[str] = field(default_factory=set)
    pins: dict[str, dict[str, float]] = field(default_factory=dict)
    mode: str = "canvas"
    aliases: dict[str, str] = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)
    last_seq: int = 0

    def canon(self, key: str) -> str:
        seen = set()
        while key in self.aliases and key not in seen:
            seen.add(key)
            key = self.aliases[key]
        return key


def _merge_obj(into: ObjectEl, other: ObjectEl) -> None:
    for k, v in other.attrs.items():
        into.attrs.setdefault(k, v)
    known = {(r.call_id, r.path) for r in into.refs}
    into.refs.extend(r for r in other.refs if (r.call_id, r.path) not in known)


def _add_input(st: CanvasState, key: str, input_id: str | None) -> None:
    if input_id is None:
        return
    lst = st.object_inputs.setdefault(key, [])
    if input_id not in lst:
        lst.append(input_id)


def _put_relation(st: CanvasState, rel: RelationEl) -> None:
    rel.from_key, rel.to_key = st.canon(rel.from_key), st.canon(rel.to_key)
    if rel.from_key == rel.to_key:
        return
    if rel.key in st.relations:
        known = {(r.call_id, r.path) for r in st.relations[rel.key].refs}
        st.relations[rel.key].refs.extend(
            r for r in rel.refs if (r.call_id, r.path) not in known)
    else:
        st.relations[rel.key] = rel


def _apply(st: CanvasState, op: Op) -> None:
    p = op.payload
    if op.kind == "add_objects":
        for d in p["objects"]:
            o = ObjectEl.model_validate(d)
            o.key = st.canon(o.key)
            if o.key in st.objects:
                _merge_obj(st.objects[o.key], o)
            else:
                st.objects[o.key] = o
            _add_input(st, o.key, op.input_id)
    elif op.kind == "add_relations":
        for d in p["relations"]:
            _put_relation(st, RelationEl.model_validate(d))
    elif op.kind == "add_view":
        st.views[p["view"]["key"]] = dict(p["view"])
    elif op.kind == "add_note":
        st.notes.append(NoteEl.model_validate(p["note"]))
    elif op.kind == "hide":
        st.hidden |= {st.canon(k) for k in p["keys"]}
    elif op.kind == "show":
        st.hidden -= {st.canon(k) for k in p["keys"]}
    elif op.kind == "pin":
        st.pins[st.canon(p["key"])] = {"x": p["x"], "y": p["y"]}
    elif op.kind == "unpin":
        st.pins.pop(st.canon(p["key"]), None)
    elif op.kind == "set_mode":
        st.mode = p["mode"]
    elif op.kind == "merge":
        _merge(st, st.canon(p["keep"]), st.canon(p["drop"]))


def _merge(st: CanvasState, keep: str, drop: str) -> None:
    if keep == drop:
        return
    st.aliases[drop] = keep
    if drop in st.objects:
        dobj = st.objects.pop(drop)
        if keep in st.objects:
            _merge_obj(st.objects[keep], dobj)
        else:
            dobj.key = keep
            st.objects[keep] = dobj
    for iid in st.object_inputs.pop(drop, []):
        _add_input(st, keep, iid)
    old = list(st.relations.values())
    st.relations = {}
    for rel in old:
        _put_relation(st, rel)
    if drop in st.hidden:
        st.hidden.discard(drop)
        st.hidden.add(keep)
    if drop in st.pins:
        st.pins.setdefault(keep, st.pins.pop(drop))


def fold(ops: Sequence[Op]) -> CanvasState:
    undone = {o.payload["input_id"] for o in ops if o.kind == "undo"}
    st = CanvasState()
    for o in sorted(ops, key=lambda x: x.seq):
        st.last_seq = o.seq
        if o.kind == "undo" or o.input_id in undone:
            continue
        _apply(st, o)
        if o.input_id and o.input_id not in st.inputs:
            st.inputs.append(o.input_id)
    return st


def state_to_dict(st: CanvasState) -> dict[str, Any]:
    return {
        "objects": [
            {**o.model_dump(mode="json"), "inputs": st.object_inputs.get(k, []),
             "hidden": k in st.hidden, "pin": st.pins.get(k)}
            for k, o in st.objects.items()
        ],
        "relations": [
            {**r.model_dump(mode="json"), "key": r.key} for r in st.relations.values()
        ],
        "views": [
            {**v, "hidden": k in st.hidden, "pin": st.pins.get(k)} for k, v in st.views.items()
        ],
        "notes": [n.model_dump(mode="json") for n in st.notes],
        "mode": st.mode,
        "inputs": list(st.inputs),
        "last_seq": st.last_seq,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lens/test_state.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit (after user go-ahead)**

```bash
git add src/lens/state.py tests/test_lens/test_state.py
git commit -m "feat(lens): canvas state as fold of op log (merge, undo, hide, pin)"
```

---

### Task 5: View-spec and validating materializer

**Files:**
- Create: `src/lens/spec.py`
- Test: `tests/test_lens/test_spec.py`

**Interfaces:**
- Consumes: `iter_path`, `PathError` (Task 2); `ObjectEl`, `RelationEl`, `AggregateEl`, `Column`, `Ref` (Task 1)
- Produces:
  - `ObjectRule(name: str, each: str | None = None, id: str, label: str, type: str, attrs: dict[str, str] = {})` — `each` absolute path to a list (or `None` = payload root is one object); `id`/`label`/`attrs` are paths relative to one item
  - `RelationRule(each: str, from_id: str, to_each: str | None = None, to_id: str, kind: str)` — `from_id` relative to the item; `to_each` relative to the item (list of targets) or `None` (target = item); `to_id` relative to the target
  - `ViewSpec(objects: list[ObjectRule] = [], relations: list[RelationRule] = [])` (extra fields forbidden)
  - `@dataclass Materialized(objects: list[ObjectEl], relations: list[RelationEl], aggregates: list[AggregateEl])` with `is_empty() -> bool`
  - `class SpecError(ValueError)` with `.errors: list[str]`
  - `materialize(spec, payload, *, namespace: str, call_id: str, vocabulary: Sequence[str], aggregate_threshold: int, args: dict | None = None, known_keys: Collection[str] = ()) -> Materialized` — raises `SpecError` listing every problem

Path scopes inside rules: `$...` = current item; `$root...` = whole payload; `$args...` = tool call arguments.

Rules: unknown type → error; `each` that matches nothing → error; a rule whose id/label resolve on no item → error; items whose id/label is missing, non-scalar or blank are skipped; objects are deduplicated by key (refs merged) BEFORE the threshold check; more than `aggregate_threshold` unique objects from one `each` rule → one `AggregateEl` instead; relation endpoints may be objects of this materialization or `known_keys` (canvas objects, @mentions), otherwise the edge is dropped; a repeated edge merges refs.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from pydantic import ValidationError

from src.lens.spec import ObjectRule, RelationRule, SpecError, ViewSpec, materialize

VOCAB = ["person", "event", "ip", "organization"]
PAYLOAD = {
    "events": [
        {"id": "E1", "title": "Визит в Пекин", "date": "2024-05-16",
         "participants": [{"qid": "Q1", "name": "Путин"}, {"qid": "Q2", "name": "Си"}]},
        {"id": "E2", "title": "ШОС", "participants": [{"qid": "Q1", "name": "Путин"}]},
        {"id": None, "title": "broken"},
    ]
}


def spec(**kw):
    return ViewSpec.model_validate(kw)


def run(s, payload=PAYLOAD, threshold=25, **kw):
    return materialize(s, payload, namespace="kb", call_id="c1", vocabulary=VOCAB,
                       aggregate_threshold=threshold, **kw)


def test_objects_and_relations_with_refs():
    s = spec(
        objects=[
            {"name": "ev", "each": "$.events[*]", "id": "$.id", "label": "$.title",
             "type": "event", "attrs": {"date": "$.date"}},
            {"name": "p", "each": "$.events[*].participants[*]", "id": "$.qid",
             "label": "$.name", "type": "person"},
        ],
        relations=[{"each": "$.events[*]", "from_id": "$.id", "to_each": "$.participants[*]",
                    "to_id": "$.qid", "kind": "участник"}],
    )
    m = run(s)
    keys = [o.key for o in m.objects]
    assert keys == ["kb:E1", "kb:E2", "kb:Q1", "kb:Q2"]
    e1 = m.objects[0]
    assert e1.attrs == {"date": "2024-05-16"}
    assert e1.refs[0].path == "$.events[0]"
    assert {r.key for r in m.relations} == {
        "kb:E1|участник|kb:Q1", "kb:E1|участник|kb:Q2", "kb:E2|участник|kb:Q1"}
    assert m.relations[0].refs[0].path == "$.events[0]"


def test_single_root_object():
    m = run(spec(objects=[{"name": "o", "id": "$.qid", "label": "$.name",
                           "type": "organization"}]),
            payload={"qid": "Q7", "name": "Росатом"})
    assert m.objects[0].key == "kb:Q7"
    assert m.objects[0].refs[0].path == "$"


def test_unknown_type_is_error():
    with pytest.raises(SpecError) as e:
        run(spec(objects=[{"name": "o", "each": "$.events[*]", "id": "$.id",
                           "label": "$.title", "type": "spaceship"}]))
    assert "spaceship" in str(e.value)


def test_each_matching_nothing_is_error():
    with pytest.raises(SpecError):
        run(spec(objects=[{"name": "o", "each": "$.nope[*]", "id": "$.id",
                           "label": "$.title", "type": "event"}]))


def test_id_resolving_nowhere_is_error():
    with pytest.raises(SpecError):
        run(spec(objects=[{"name": "o", "each": "$.events[*]", "id": "$.uuid",
                           "label": "$.title", "type": "event"}]))


def test_bad_path_syntax_is_error():
    with pytest.raises(SpecError):
        run(spec(objects=[{"name": "o", "each": "events", "id": "$.id",
                           "label": "$.title", "type": "event"}]))


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        ViewSpec.model_validate({"objects": [], "values": {"x": 1}})


def test_large_list_becomes_aggregate():
    hosts = {"hosts": [{"ip": f"10.0.0.{i}", "port": 22} for i in range(30)]}
    m = run(spec(objects=[{"name": "h", "each": "$.hosts[*]", "id": "$.ip", "label": "$.ip",
                           "type": "ip", "attrs": {"port": "$.port"}}]),
            payload=hosts, threshold=25)
    assert m.objects == []
    agg = m.aggregates[0]
    assert agg.key == "agg:c1:h" and agg.count == 30 and agg.label == "ip · 30"
    assert agg.rows_ref.path == "$.hosts[*]"
    assert [c.name for c in agg.columns] == ["id", "label", "port"]


def test_empty_spec_is_empty():
    assert run(spec()).is_empty()


def test_rules_are_models():
    assert ObjectRule(name="a", id="$.x", label="$.y", type="ip").each is None
    assert RelationRule(each="$[*]", from_id="$.a", to_id="$.b", kind="k").to_each is None


def test_duplicates_do_not_trigger_aggregate():
    # 10 meetings x the same 3 participants = 30 rows but 3 unique persons
    payload = {"events": [{"id": f"E{i}", "title": "t", "participants": [
        {"qid": "P1", "name": "Путин"}, {"qid": "P2", "name": "Си"}, {"qid": "P3", "name": "Ван"},
    ]} for i in range(10)]}
    m = run(spec(
        objects=[{"name": "p", "each": "$.events[*].participants[*]", "id": "$.qid",
                  "label": "$.name", "type": "person"}]), payload=payload, threshold=25)
    assert m.aggregates == []
    assert sorted(o.key for o in m.objects) == ["kb:P1", "kb:P2", "kb:P3"]
    assert len(m.objects[0].refs) == 10


def test_relation_to_known_canvas_object_via_root_path():
    # neighbours response: the centre is outside the items, and is already on canvas
    payload = {"center": "Q1", "neighbours": [{"id": "Q2", "name": "B"}]}
    s = spec(
        objects=[{"name": "n", "each": "$.neighbours[*]", "id": "$.id", "label": "$.name",
                  "type": "person"}],
        relations=[{"each": "$.neighbours[*]", "from_id": "$root.center", "to_id": "$.id",
                    "kind": "связан"}])
    assert run(s, payload=payload).relations == []  # Q1 unknown: dropped, not an error
    m = run(s, payload=payload, known_keys={"kb:Q1"})
    assert [r.key for r in m.relations] == ["kb:Q1|связан|kb:Q2"]


def test_args_scope():
    payload = {"neighbours": [{"id": "Q2", "name": "B"}]}
    s = spec(
        objects=[{"name": "n", "each": "$.neighbours[*]", "id": "$.id", "label": "$.name",
                  "type": "person"}],
        relations=[{"each": "$.neighbours[*]", "from_id": "$args.entity_id", "to_id": "$.id",
                    "kind": "связан"}])
    m = run(s, payload=payload, args={"entity_id": "Q1"}, known_keys={"kb:Q1"})
    assert [r.key for r in m.relations] == ["kb:Q1|связан|kb:Q2"]


def test_repeated_relation_keeps_all_refs():
    payload = {"pairs": [{"a": "E1", "b": "P1"}, {"a": "E1", "b": "P1"}],
               "objs": [{"id": "E1"}, {"id": "P1"}]}
    s = spec(
        objects=[{"name": "o", "each": "$.objs[*]", "id": "$.id", "label": "$.id",
                  "type": "person"}],
        relations=[{"each": "$.pairs[*]", "from_id": "$.a", "to_id": "$.b", "kind": "k"}])
    (rel,) = run(s, payload=payload).relations
    assert [r.path for r in rel.refs] == ["$.pairs[0]", "$.pairs[1]"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lens/test_spec.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens.spec'`

- [ ] **Step 3: Implement**

```python
"""View-spec: LLM-written extraction rules made of paths, never values.

``materialize`` is also the validator: every path must resolve against the
real payload, every type must be in the vocabulary.  Any problem raises
``SpecError`` with all messages so the Normalizer can ask for one repair.

Path scopes inside a rule:
- ``$...``      relative to the current item (or the payload root when ``each`` is null)
- ``$root...``  the whole payload (e.g. the "center" of a neighbours response)
- ``$args...``  the tool call arguments (e.g. the entity id the call was about)

Relation endpoints may be objects of this call OR ``known_keys`` (objects already on
the canvas and the user's @mentions) — that is how new results attach to old ones.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.lens.model import AggregateEl, Column, ObjectEl, Ref, RelationEl
from src.lens.paths import PathError, iter_path


class ObjectRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    each: str | None = None
    id: str
    label: str
    type: str
    attrs: dict[str, str] = Field(default_factory=dict)


class RelationRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    each: str
    from_id: str
    to_each: str | None = None
    to_id: str
    kind: str


class ViewSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objects: list[ObjectRule] = Field(default_factory=list)
    relations: list[RelationRule] = Field(default_factory=list)


@dataclass
class Materialized:
    objects: list[ObjectEl] = field(default_factory=list)
    relations: list[RelationEl] = field(default_factory=list)
    aggregates: list[AggregateEl] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.objects or self.relations or self.aggregates)


class SpecError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class _Ctx:
    payload: Any
    args: dict


def _scoped(item: Any, path: str, ctx: _Ctx) -> list[tuple[str, Any]]:
    if path.startswith("$root"):
        return iter_path(ctx.payload, "$" + path[len("$root"):])
    if path.startswith("$args"):
        return iter_path(ctx.args, "$" + path[len("$args"):])
    return iter_path(item, path)


def _scalar(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return v.strip() or None
    return None


def _one(item: Any, path: str, ctx: _Ctx) -> str | None:
    m = _scoped(item, path, ctx)
    return _scalar(m[0][1]) if len(m) == 1 else None


def _items(ctx: _Ctx, each: str | None) -> list[tuple[str, Any]]:
    return _scoped(ctx.payload, each, ctx) if each else [("$", ctx.payload)]


def _objects_for(
    rule: ObjectRule, ctx: _Ctx, ns: str, call_id: str, errors: list[str],
) -> dict[str, ObjectEl] | None:
    """Objects of one rule, deduplicated by key (refs merged)."""
    try:
        items = _items(ctx, rule.each)
    except PathError as e:
        errors.append(f"object rule {rule.name!r}: {e}")
        return None
    if rule.each and not items:
        errors.append(f"object rule {rule.name!r}: each {rule.each!r} matched nothing")
        return None
    built: dict[str, ObjectEl] = {}
    try:
        for base, item in items:
            id_v, label_v = _one(item, rule.id, ctx), _one(item, rule.label, ctx)
            if id_v is None or label_v is None:
                continue
            attrs: dict[str, Any] = {}
            for name, rel in rule.attrs.items():
                m = _scoped(item, rel, ctx)
                if len(m) == 1:
                    attrs[name] = m[0][1]
                elif len(m) > 1:
                    attrs[name] = [v for _, v in m]
            key = f"{ns}:{id_v}"
            ref = Ref(call_id=call_id, path=base)
            if key in built:
                built[key].refs.append(ref)
            else:
                built[key] = ObjectEl(key=key, type=rule.type, label=label_v, attrs=attrs,
                                      refs=[ref])
    except PathError as e:
        errors.append(f"object rule {rule.name!r}: {e}")
        return None
    if not built:
        errors.append(
            f"object rule {rule.name!r}: id {rule.id!r} / label {rule.label!r} "
            "resolved on no item"
        )
        return None
    return built


def _add_relation(relations: dict[str, RelationEl], rel: RelationEl) -> None:
    if rel.key in relations:
        known = {(r.call_id, r.path) for r in relations[rel.key].refs}
        relations[rel.key].refs.extend(r for r in rel.refs if (r.call_id, r.path) not in known)
    else:
        relations[rel.key] = rel


def materialize(
    spec: ViewSpec,
    payload: Any,
    *,
    namespace: str,
    call_id: str,
    vocabulary: Sequence[str],
    aggregate_threshold: int,
    args: dict | None = None,
    known_keys: Collection[str] = (),
) -> Materialized:
    ctx = _Ctx(payload=payload, args=args or {})
    errors: list[str] = []
    out = Materialized()
    objects: dict[str, ObjectEl] = {}
    for rule in spec.objects:
        if rule.type not in vocabulary:
            errors.append(
                f"object rule {rule.name!r}: type {rule.type!r} not in vocabulary "
                f"{sorted(vocabulary)}"
            )
            continue
        built = _objects_for(rule, ctx, namespace, call_id, errors)
        if built is None:
            continue
        if rule.each and len(built) > aggregate_threshold:
            out.aggregates.append(AggregateEl(
                key=f"agg:{call_id}:{rule.name}",
                label=f"{rule.type} · {len(built)}",
                item_type=rule.type,
                count=len(built),
                rows_ref=Ref(call_id=call_id, path=rule.each),
                columns=[Column(name="id", path=rule.id), Column(name="label", path=rule.label),
                         *[Column(name=k, path=v) for k, v in rule.attrs.items()]],
            ))
            continue
        for key, o in built.items():
            if key in objects:
                objects[key].refs.extend(o.refs)
            else:
                objects[key] = o

    endpoints = set(objects) | set(known_keys)
    relations: dict[str, RelationEl] = {}
    for rule in spec.relations:
        try:
            items = _scoped(payload, rule.each, ctx)
            if not items:
                errors.append(f"relation {rule.kind!r}: each {rule.each!r} matched nothing")
                continue
            for base, item in items:
                from_v = _one(item, rule.from_id, ctx)
                if from_v is None:
                    continue
                targets = _scoped(item, rule.to_each, ctx) if rule.to_each else [("$", item)]
                for _, target in targets:
                    to_v = _one(target, rule.to_id, ctx)
                    fk, tk = f"{namespace}:{from_v}", f"{namespace}:{to_v}"
                    if to_v is None or fk == tk or fk not in endpoints or tk not in endpoints:
                        continue
                    _add_relation(relations, RelationEl(
                        from_key=fk, to_key=tk, kind=rule.kind,
                        refs=[Ref(call_id=call_id, path=base)]))
        except PathError as e:
            errors.append(f"relation {rule.kind!r}: {e}")

    if errors:
        raise SpecError(errors)
    out.objects = list(objects.values())
    out.relations = list(relations.values())
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lens/test_spec.py -q`
Expected: 14 passed

- [ ] **Step 5: Commit (after user go-ahead)**

```bash
git add src/lens/spec.py tests/test_lens/test_spec.py
git commit -m "feat(lens): view-spec rules and validating materializer with aggregates"
```

---

### Task 6: Stores (memory + Postgres)

**Files:**
- Create: `src/lens/store.py`
- Test: `tests/test_lens/test_store.py`

**Interfaces:**
- Consumes: `Workspace`, `Op`, `OpKind`, `ToolCallRecord` (Task 1); `ViewSpec` (Task 5)
- Produces `LensStore` protocol, implemented by `MemoryLensStore()` and `PgLensStore(pool: AsyncConnectionPool)`:
  - `async ensure_schema() -> None`
  - `async create_workspace(title: str, owner_id: str | None = None) -> Workspace`
  - `async list_workspaces() -> list[Workspace]` (newest first)
  - `async get_workspace(workspace_id: str) -> Workspace | None`
  - `async add_input(workspace_id: str, text: str, mentions: list[str]) -> str` (returns input id)
  - `async set_input_status(input_id: str, status: str) -> None`
  - `async get_input(input_id: str) -> dict | None` (`id, workspace_id, text, mentions, status`)
  - `async append_ops(workspace_id: str, input_id: str | None, ops: list[tuple[OpKind, dict]]) -> list[Op]` (seq contiguous per workspace, starting at 1)
  - `async list_ops(workspace_id: str, after_seq: int = 0) -> list[Op]` (seq ascending)
  - `async add_tool_call(rec: ToolCallRecord) -> None`
  - `async get_tool_call(call_id: str) -> ToolCallRecord | None`
  - `async get_spec(server: str, tool: str, shape_hash: str) -> ViewSpec | None` (increments hits)
  - `async put_spec(server: str, tool: str, shape_hash: str, spec: ViewSpec, model: str) -> None` (upsert)
- `SCHEMA_SQL: str` (`lens_tool_call.namespace` column included)

- [ ] **Step 1: Write the failing test**

The same contract runs against memory always and Postgres when `LENS_TEST_PG_DSN` is set (e.g. `postgresql://kb:kb@localhost:5432/kb`).

```python
import os
import uuid

import pytest

from src.lens.model import ToolCallRecord
from src.lens.spec import ViewSpec
from src.lens.store import MemoryLensStore, PgLensStore

PG_DSN = os.environ.get("LENS_TEST_PG_DSN")


@pytest.fixture(params=["memory", "pg"])
async def store(request):
    if request.param == "memory":
        yield MemoryLensStore()
        return
    if not PG_DSN:
        pytest.skip("LENS_TEST_PG_DSN not set")
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(PG_DSN, min_size=1, max_size=2, open=False)
    await pool.open()
    s = PgLensStore(pool)
    await s.ensure_schema()
    yield s
    await pool.close()


async def test_workspace_roundtrip(store):
    ws = await store.create_workspace(f"t-{uuid.uuid4().hex[:6]}")
    assert (await store.get_workspace(ws.id)).title == ws.title
    assert ws.id in [w.id for w in await store.list_workspaces()]
    assert await store.get_workspace("missing") is None


async def test_ops_sequence_and_after(store):
    ws = await store.create_workspace("ops")
    iid = await store.add_input(ws.id, "q", ["kb:1"])
    a = await store.append_ops(ws.id, iid, [("hide", {"keys": ["a"]}),
                                            ("show", {"keys": ["a"]})])
    b = await store.append_ops(ws.id, None, [("pin", {"key": "a", "x": 1, "y": 2})])
    assert [o.seq for o in a + b] == [1, 2, 3]
    assert [o.kind for o in await store.list_ops(ws.id, after_seq=1)] == ["show", "pin"]
    assert a[0].input_id == iid and b[0].input_id is None
    await store.set_input_status(iid, "done")
    got = await store.get_input(iid)
    assert got["status"] == "done" and got["mentions"] == ["kb:1"]
    assert await store.get_input("missing") is None


async def test_tool_call_roundtrip(store):
    rec = ToolCallRecord(id=uuid.uuid4().hex, input_id=None, server="kb-tools", namespace="kb",
                         tool="t",
                         args={"q": "x"}, payload={"a": [1]}, shape_hash="h",
                         latency_ms=5)
    await store.add_tool_call(rec)
    got = await store.get_tool_call(rec.id)
    assert got.payload == {"a": [1]} and got.args == {"q": "x"}
    assert got.ns == "kb"
    assert await store.get_tool_call("nope") is None


async def test_spec_cache_upsert(store):
    tool = f"t-{uuid.uuid4().hex[:6]}"
    assert await store.get_spec("kb", tool, "h") is None
    s1 = ViewSpec.model_validate({"objects": [
        {"name": "o", "id": "$.id", "label": "$.n", "type": "person"}]})
    await store.put_spec("kb", tool, "h", s1, "m")
    await store.put_spec("kb", tool, "h", ViewSpec(), "m2")
    assert await store.get_spec("kb", tool, "h") == ViewSpec()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lens/test_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens.store'`

- [ ] **Step 3: Implement**

```python
"""Lens persistence: workspaces, inputs, op log, tool calls, spec cache."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from src.lens.model import Op, OpKind, ToolCallRecord, Workspace
from src.lens.spec import ViewSpec

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS lens_workspace (
    id text PRIMARY KEY,
    title text NOT NULL,
    owner_id text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS lens_ws_member (
    workspace_id text NOT NULL REFERENCES lens_workspace(id) ON DELETE CASCADE,
    user_id text NOT NULL,
    role text NOT NULL,
    PRIMARY KEY (workspace_id, user_id)
);
CREATE TABLE IF NOT EXISTS lens_input (
    id text PRIMARY KEY,
    workspace_id text NOT NULL REFERENCES lens_workspace(id) ON DELETE CASCADE,
    text text NOT NULL,
    mentions jsonb NOT NULL DEFAULT '[]',
    status text NOT NULL DEFAULT 'pending',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS lens_op (
    workspace_id text NOT NULL REFERENCES lens_workspace(id) ON DELETE CASCADE,
    seq bigint NOT NULL,
    kind text NOT NULL,
    payload jsonb NOT NULL,
    input_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (workspace_id, seq)
);
CREATE TABLE IF NOT EXISTS lens_tool_call (
    id text PRIMARY KEY,
    input_id text,
    server text NOT NULL,
    namespace text,
    tool text NOT NULL,
    args jsonb NOT NULL,
    payload jsonb,
    shape_hash text NOT NULL,
    is_error boolean NOT NULL DEFAULT false,
    error text,
    latency_ms integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS lens_spec_cache (
    server text NOT NULL,
    tool text NOT NULL,
    shape_hash text NOT NULL,
    spec jsonb NOT NULL,
    model text NOT NULL,
    hits integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (server, tool, shape_hash)
);
"""


def _new_id() -> str:
    return uuid.uuid4().hex


class LensStore(Protocol):
    async def ensure_schema(self) -> None: ...
    async def create_workspace(self, title: str, owner_id: str | None = None) -> Workspace: ...
    async def list_workspaces(self) -> list[Workspace]: ...
    async def get_workspace(self, workspace_id: str) -> Workspace | None: ...
    async def add_input(self, workspace_id: str, text: str, mentions: list[str]) -> str: ...
    async def set_input_status(self, input_id: str, status: str) -> None: ...
    async def get_input(self, input_id: str) -> dict[str, Any] | None: ...
    async def append_ops(
        self, workspace_id: str, input_id: str | None, ops: list[tuple[OpKind, dict]],
    ) -> list[Op]: ...
    async def list_ops(self, workspace_id: str, after_seq: int = 0) -> list[Op]: ...
    async def add_tool_call(self, rec: ToolCallRecord) -> None: ...
    async def get_tool_call(self, call_id: str) -> ToolCallRecord | None: ...
    async def get_spec(self, server: str, tool: str, shape_hash: str) -> ViewSpec | None: ...
    async def put_spec(
        self, server: str, tool: str, shape_hash: str, spec: ViewSpec, model: str,
    ) -> None: ...


class MemoryLensStore:
    def __init__(self) -> None:
        self.workspaces: dict[str, Workspace] = {}
        self.inputs: dict[str, dict[str, Any]] = {}
        self.ops: dict[str, list[Op]] = {}
        self.calls: dict[str, ToolCallRecord] = {}
        self.specs: dict[tuple[str, str, str], ViewSpec] = {}
        self.spec_hits: dict[tuple[str, str, str], int] = {}

    async def ensure_schema(self) -> None:
        return None

    async def create_workspace(self, title: str, owner_id: str | None = None) -> Workspace:
        ws = Workspace(id=_new_id(), title=title, owner_id=owner_id,
                       created_at=datetime.now(UTC))
        self.workspaces[ws.id] = ws
        self.ops[ws.id] = []
        return ws

    async def list_workspaces(self) -> list[Workspace]:
        return sorted(self.workspaces.values(), key=lambda w: w.created_at, reverse=True)

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        return self.workspaces.get(workspace_id)

    async def add_input(self, workspace_id: str, text: str, mentions: list[str]) -> str:
        iid = _new_id()
        self.inputs[iid] = {"workspace_id": workspace_id, "text": text,
                            "mentions": list(mentions), "status": "pending"}
        return iid

    async def set_input_status(self, input_id: str, status: str) -> None:
        self.inputs[input_id]["status"] = status

    async def get_input(self, input_id: str) -> dict[str, Any] | None:
        row = self.inputs.get(input_id)
        return {"id": input_id, **row} if row else None

    async def append_ops(
        self, workspace_id: str, input_id: str | None, ops: list[tuple[OpKind, dict]],
    ) -> list[Op]:
        log = self.ops.setdefault(workspace_id, [])
        out = []
        for kind, payload in ops:
            op = Op(workspace_id=workspace_id, seq=len(log) + 1, kind=kind, payload=payload,
                    input_id=input_id, created_at=datetime.now(UTC))
            log.append(op)
            out.append(op)
        return out

    async def list_ops(self, workspace_id: str, after_seq: int = 0) -> list[Op]:
        return [o for o in self.ops.get(workspace_id, []) if o.seq > after_seq]

    async def add_tool_call(self, rec: ToolCallRecord) -> None:
        self.calls[rec.id] = rec

    async def get_tool_call(self, call_id: str) -> ToolCallRecord | None:
        return self.calls.get(call_id)

    async def get_spec(self, server: str, tool: str, shape_hash: str) -> ViewSpec | None:
        key = (server, tool, shape_hash)
        if key in self.specs:
            self.spec_hits[key] = self.spec_hits.get(key, 0) + 1
        return self.specs.get(key)

    async def put_spec(
        self, server: str, tool: str, shape_hash: str, spec: ViewSpec, model: str,
    ) -> None:
        self.specs[(server, tool, shape_hash)] = spec


class PgLensStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self.pool = pool

    async def ensure_schema(self) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(SCHEMA_SQL)

    async def create_workspace(self, title: str, owner_id: str | None = None) -> Workspace:
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "INSERT INTO lens_workspace (id, title, owner_id) VALUES (%s, %s, %s) "
                "RETURNING id, title, owner_id, created_at",
                (_new_id(), title, owner_id),
            )
            return Workspace.model_validate(await cur.fetchone())

    async def list_workspaces(self) -> list[Workspace]:
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "SELECT id, title, owner_id, created_at FROM lens_workspace "
                "ORDER BY created_at DESC"
            )
            return [Workspace.model_validate(r) for r in await cur.fetchall()]

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "SELECT id, title, owner_id, created_at FROM lens_workspace WHERE id = %s",
                (workspace_id,),
            )
            row = await cur.fetchone()
            return Workspace.model_validate(row) if row else None

    async def add_input(self, workspace_id: str, text: str, mentions: list[str]) -> str:
        iid = _new_id()
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO lens_input (id, workspace_id, text, mentions) "
                "VALUES (%s, %s, %s, %s)",
                (iid, workspace_id, text, Jsonb(list(mentions))),
            )
        return iid

    async def set_input_status(self, input_id: str, status: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute("UPDATE lens_input SET status = %s WHERE id = %s",
                               (status, input_id))

    async def get_input(self, input_id: str) -> dict[str, Any] | None:
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "SELECT id, workspace_id, text, mentions, status FROM lens_input WHERE id = %s",
                (input_id,),
            )
            return await cur.fetchone()

    async def append_ops(
        self, workspace_id: str, input_id: str | None, ops: list[tuple[OpKind, dict]],
    ) -> list[Op]:
        out: list[Op] = []
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (workspace_id,))
            cur = await conn.execute(
                "SELECT coalesce(max(seq), 0) FROM lens_op WHERE workspace_id = %s",
                (workspace_id,),
            )
            (seq,) = await cur.fetchone()
            for kind, payload in ops:
                seq += 1
                c = await conn.execute(
                    "INSERT INTO lens_op (workspace_id, seq, kind, payload, input_id) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING created_at",
                    (workspace_id, seq, kind, Jsonb(payload), input_id),
                )
                (created_at,) = await c.fetchone()
                out.append(Op(workspace_id=workspace_id, seq=seq, kind=kind, payload=payload,
                              input_id=input_id, created_at=created_at))
        return out

    async def list_ops(self, workspace_id: str, after_seq: int = 0) -> list[Op]:
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "SELECT workspace_id, seq, kind, payload, input_id, created_at FROM lens_op "
                "WHERE workspace_id = %s AND seq > %s ORDER BY seq",
                (workspace_id, after_seq),
            )
            return [Op.model_validate(r) for r in await cur.fetchall()]

    async def add_tool_call(self, rec: ToolCallRecord) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO lens_tool_call (id, input_id, server, namespace, tool, args, "
                "payload, shape_hash, is_error, error, latency_ms) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (rec.id, rec.input_id, rec.server, rec.namespace, rec.tool, Jsonb(rec.args),
                 Jsonb(rec.payload), rec.shape_hash, rec.is_error, rec.error, rec.latency_ms),
            )

    async def get_tool_call(self, call_id: str) -> ToolCallRecord | None:
        async with self.pool.connection() as conn:
            cur = conn.cursor(row_factory=dict_row)
            await cur.execute(
                "SELECT id, input_id, server, namespace, tool, args, payload, shape_hash, "
                "is_error, error, latency_ms FROM lens_tool_call WHERE id = %s",
                (call_id,),
            )
            row = await cur.fetchone()
            return ToolCallRecord.model_validate(row) if row else None

    async def get_spec(self, server: str, tool: str, shape_hash: str) -> ViewSpec | None:
        async with self.pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE lens_spec_cache SET hits = hits + 1 "
                "WHERE server = %s AND tool = %s AND shape_hash = %s RETURNING spec",
                (server, tool, shape_hash),
            )
            row = await cur.fetchone()
            return ViewSpec.model_validate(row[0]) if row else None

    async def put_spec(
        self, server: str, tool: str, shape_hash: str, spec: ViewSpec, model: str,
    ) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO lens_spec_cache (server, tool, shape_hash, spec, model) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (server, tool, shape_hash) "
                "DO UPDATE SET spec = EXCLUDED.spec, model = EXCLUDED.model, hits = 0",
                (server, tool, shape_hash, Jsonb(spec.model_dump(mode="json")), model),
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lens/test_store.py -q`
Expected: 4 passed, 4 skipped (memory only). With a local Postgres:
`LENS_TEST_PG_DSN=postgresql://<user>:<pw>@localhost:5432/<db> uv run pytest tests/test_lens/test_store.py -q` → 8 passed.

- [ ] **Step 5: Commit (after user go-ahead)**

```bash
git add src/lens/store.py tests/test_lens/test_store.py
git commit -m "feat(lens): memory and Postgres stores for workspaces, ops, calls, spec cache"
```

---

### Task 7: MCP hub

**Files:**
- Create: `src/lens/mcp_hub.py`
- Test: `tests/test_lens/test_mcp_hub.py`

**Interfaces:**
- Consumes: `McpServerConfig` (Task 1)
- Produces:
  - `@dataclass ToolInfo(server: str, name: str, description: str, input_schema: dict, namespace: str = "")` with property `qualified -> str` = `f"{server}__{name}"`
  - `@dataclass ToolResult(payload: Any, is_error: bool = False, error: str | None = None)`
  - `McpHub(servers, client_factory=None, *, timeout_s: float = 120.0, backoff_s: float = 10.0, clock=time.monotonic)`
    - `async start() -> None` — connects every server; failures recorded, never raised
    - `async refresh() -> None` — retries down servers, at most once per `backoff_s`
    - `async close() -> None`
    - `catalog() -> list[ToolInfo]` — tools of live servers only
    - `find(qualified: str) -> ToolInfo | None`
    - `status() -> dict[str, str]` — `"up"` or `"down: <error>"`
    - `async call(server: str, tool: str, args: dict) -> ToolResult` — never raises; passes `timeout=timeout_s, raise_on_error=False`; a transport failure marks the server down, reconnects and retries once
  - `extract_payload(result: Any) -> Any` — `structured_content` (fastmcp's `{"result": x}` wrapper unwrapped, JSON strings parsed, scalars → `{"text": x}`); else JSON of the text blocks; else `{"text": joined}`

- [ ] **Step 1: Write the failing test**

```python
from types import SimpleNamespace

from fastmcp import Client, FastMCP

from src.lens.config import McpServerConfig
from src.lens.mcp_hub import McpHub

kb = FastMCP("kb")


@kb.tool
def find_entity(name: str) -> dict:
    """Find entity by name."""
    return {"results": [{"id": "Q1", "name": name}]}


@kb.tool
def as_text(q: str) -> str:
    return "plain text answer"


@kb.tool
def as_json_text(q: str) -> str:
    return '{"a": 1}'


@kb.tool
def as_list(q: str) -> list[dict]:
    return [{"id": "x"}]


@kb.tool
def boom(q: str) -> dict:
    raise ValueError("kaput")


class _DeadClient:
    async def __aenter__(self):
        raise ConnectionError("refused")

    async def __aexit__(self, *a):
        return False


class _FlakyClient:
    """Connects fine, first call_tool dies like a restarted server."""

    fail_next = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def list_tools(self):
        return [SimpleNamespace(name="ping", description="", inputSchema={})]

    async def call_tool(self, name, args, **kw):
        _FlakyClient.last_kw = kw
        if _FlakyClient.fail_next:
            _FlakyClient.fail_next = False
            raise ConnectionError("session terminated")
        return SimpleNamespace(structured_content={"ok": True}, content=[], is_error=False)


def cfg(name, **kw):
    return McpServerConfig(name=name, url=f"memory://{name}", **kw)


async def make_hub(*configs, factory=None, **kw):
    def default_factory(c):
        return {"dead": _DeadClient, "flaky": _FlakyClient}.get(c.name, lambda: Client(kb))()

    hub = McpHub(list(configs), client_factory=factory or default_factory, **kw)
    await hub.start()
    return hub


async def test_catalog_namespace_and_structured_call():
    hub = await make_hub(cfg("kb-tools", namespace="kb"))
    try:
        info = hub.find("kb-tools__find_entity")
        assert info.namespace == "kb"
        assert info.description.startswith("Find entity")
        assert "name" in info.input_schema["properties"]
        res = await hub.call("kb-tools", "find_entity", {"name": "Росатом"})
        assert res.is_error is False
        assert res.payload == {"results": [{"id": "Q1", "name": "Росатом"}]}
    finally:
        await hub.close()


async def test_wrapped_results_are_unwrapped():
    hub = await make_hub(cfg("kb"))
    try:
        assert (await hub.call("kb", "as_text", {"q": "x"})).payload == {
            "text": "plain text answer"}
        assert (await hub.call("kb", "as_json_text", {"q": "x"})).payload == {"a": 1}
        assert (await hub.call("kb", "as_list", {"q": "x"})).payload == [{"id": "x"}]
    finally:
        await hub.close()


async def test_call_error_is_result_not_exception():
    hub = await make_hub(cfg("kb"))
    try:
        res = await hub.call("kb", "boom", {"q": "x"})
        assert res.is_error is True and "kaput" in (res.error or "")
        unknown = await hub.call("nope", "x", {})
        assert unknown.is_error and "unknown server" in unknown.error
    finally:
        await hub.close()


async def test_dead_server_excluded_others_work():
    hub = await make_hub(cfg("dead"), cfg("kb"))
    try:
        st = hub.status()
        assert st["kb"] == "up" and st["dead"].startswith("down: ")
        assert all(t.server == "kb" for t in hub.catalog())
        assert (await hub.call("kb", "find_entity", {"name": "x"})).is_error is False
        assert (await hub.call("dead", "x", {})).error == "server 'dead' not connected"
    finally:
        await hub.close()


async def test_down_server_recovers_on_refresh_after_backoff():
    alive = {"on": False}
    now = {"t": 0.0}

    def factory(c):
        return Client(kb) if alive["on"] else _DeadClient()

    hub = await make_hub(cfg("kb"), factory=factory, backoff_s=10, clock=lambda: now["t"])
    try:
        assert hub.catalog() == []
        alive["on"] = True
        now["t"] = 5
        await hub.refresh()
        assert hub.catalog() == []  # still inside backoff
        now["t"] = 11
        await hub.refresh()
        assert hub.status()["kb"] == "up" and hub.find("kb__find_entity") is not None
    finally:
        await hub.close()


async def test_transport_failure_reconnects_once_and_passes_timeout():
    _FlakyClient.fail_next = True
    hub = await make_hub(cfg("flaky"), timeout_s=7)
    try:
        res = await hub.call("flaky", "ping", {})
        assert res.is_error is False and res.payload == {"ok": True}
        assert _FlakyClient.last_kw == {"timeout": 7, "raise_on_error": False}
    finally:
        await hub.close()


def test_blank_token_becomes_none():
    assert McpServerConfig(name="a", url="u", token="").token is None
    assert McpServerConfig(name="a", url="u", token="  ").token is None
    assert McpServerConfig(name="a", url="u", token="k").token.get_secret_value() == "k"
    assert McpServerConfig(name="a", url="u").ns == "a"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lens/test_mcp_hub.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens.mcp_hub'`

- [ ] **Step 3: Implement**

```python
"""Connections to all configured MCP servers + a merged tool catalog.

A server that is down (not yet listening at startup, restarted mid-session) is
reconnected lazily: ``refresh()`` retries down servers (at most once per
``backoff_s``) and a transport failure during ``call()`` marks the server down and
retries once after reconnecting.  One dead server never breaks the others.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from loguru import logger

from src.lens.config import McpServerConfig


@dataclass
class ToolInfo:
    server: str
    name: str
    description: str
    input_schema: dict
    namespace: str = ""

    @property
    def qualified(self) -> str:
        return f"{self.server}__{self.name}"


@dataclass
class ToolResult:
    payload: Any
    is_error: bool = False
    error: str | None = None


def _default_client(cfg: McpServerConfig) -> Client:
    headers = {}
    if cfg.token is not None:
        headers["Authorization"] = f"Bearer {cfg.token.get_secret_value()}"
    return Client(StreamableHttpTransport(url=cfg.url, headers=headers))


def _maybe_json(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return v
    return v


def extract_payload(result: Any) -> Any:
    """``structured_content`` (fastmcp wraps non-dict returns as ``{"result": x}`` —
    unwrapped, JSON strings parsed); else JSON of the text blocks; else ``{"text": ...}``."""
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        if isinstance(structured, dict) and set(structured) == {"result"}:
            inner = _maybe_json(structured["result"])
            return inner if isinstance(inner, (dict, list)) else {"text": inner}
        return structured
    texts = [getattr(c, "text", "") for c in (getattr(result, "content", None) or [])]
    joined = "\n".join(t for t in texts if t)
    parsed = _maybe_json(joined)
    return parsed if isinstance(parsed, (dict, list)) else {"text": joined}


class McpHub:
    def __init__(
        self,
        servers: list[McpServerConfig],
        client_factory: Callable[[McpServerConfig], Any] | None = None,
        *,
        timeout_s: float = 120.0,
        backoff_s: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._configs = {c.name: c for c in servers}
        self._factory = client_factory or _default_client
        self._timeout_s, self._backoff_s, self._clock = timeout_s, backoff_s, clock
        self._stacks: dict[str, AsyncExitStack] = {}
        self._clients: dict[str, Any] = {}
        self._tools: dict[str, ToolInfo] = {}
        self._status: dict[str, str] = {}
        self._last_try: dict[str, float] = {}

    async def _connect(self, name: str) -> bool:
        cfg = self._configs[name]
        self._last_try[name] = self._clock()
        stack = AsyncExitStack()
        try:
            client = await stack.enter_async_context(self._factory(cfg))
            tools = await client.list_tools()
        except Exception as e:  # one dead server must not kill the hub
            await stack.aclose()
            logger.warning("lens: MCP server {} unavailable: {}", name, e)
            self._status[name] = f"down: {e}"
            return False
        self._stacks[name], self._clients[name] = stack, client
        self._status[name] = "up"
        for t in tools:
            info = ToolInfo(server=name, name=t.name, description=t.description or "",
                            input_schema=dict(t.inputSchema or {}), namespace=cfg.ns)
            self._tools[info.qualified] = info
        return True

    async def _disconnect(self, name: str, reason: str) -> None:
        self._clients.pop(name, None)
        self._tools = {q: t for q, t in self._tools.items() if t.server != name}
        self._status[name] = f"down: {reason}"
        stack = self._stacks.pop(name, None)
        if stack is not None:
            try:
                await stack.aclose()
            except Exception as e:  # a broken session may fail to close; ignore
                logger.debug("lens: closing {} failed: {}", name, e)

    async def start(self) -> None:
        for name in self._configs:
            await self._connect(name)

    async def refresh(self) -> None:
        """Retry servers that are down, respecting the backoff."""
        now = self._clock()
        for name in self._configs:
            if name in self._clients:
                continue
            if now - self._last_try.get(name, float("-inf")) >= self._backoff_s:
                await self._connect(name)

    async def close(self) -> None:
        for name in list(self._stacks):
            await self._disconnect(name, "closed")

    def catalog(self) -> list[ToolInfo]:
        return list(self._tools.values())

    def find(self, qualified: str) -> ToolInfo | None:
        return self._tools.get(qualified)

    def status(self) -> dict[str, str]:
        return dict(self._status)

    async def call(self, server: str, tool: str, args: dict) -> ToolResult:
        if server not in self._configs:
            return ToolResult(payload=None, is_error=True, error=f"unknown server {server!r}")
        for attempt in range(2):
            client = self._clients.get(server)
            if client is None and not await self._connect(server):
                return ToolResult(payload=None, is_error=True,
                                  error=f"server {server!r} not connected")
            client = self._clients[server]
            try:
                res = await client.call_tool(tool, args, timeout=self._timeout_s,
                                             raise_on_error=False)
            except Exception as e:  # transport failure: reconnect once, then give up
                await self._disconnect(server, str(e))
                if attempt == 1:
                    return ToolResult(payload=None, is_error=True, error=str(e))
                continue
            payload = extract_payload(res)
            if getattr(res, "is_error", False):
                return ToolResult(payload=payload, is_error=True,
                                  error=str(payload.get("text", payload))
                                  if isinstance(payload, dict) else str(payload))
            return ToolResult(payload=payload)
        return ToolResult(payload=None, is_error=True, error="unreachable")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lens/test_mcp_hub.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit (after user go-ahead)**

```bash
git add src/lens/mcp_hub.py tests/test_lens/test_mcp_hub.py
git commit -m "feat(lens): MCP hub with merged catalog and failure-tolerant calls"
```

---

### Task 8: LLM client and test fakes

**Files:**
- Create: `src/lens/llm.py`, `tests/test_lens/fakes.py`
- Test: `tests/test_lens/test_llm.py`

**Interfaces:**
- Produces:
  - `@dataclass ToolCallReq(id: str, name: str, arguments: dict)`
  - `@dataclass ChatReply(text: str | None, tool_calls: list[ToolCallReq])`
  - `class LLMClient(Protocol)`: `async chat(*, model: str, messages: list[dict], tools: list[dict] | None = None, tool_choice: str | None = None) -> ChatReply` (non-`function` tool calls are skipped); `async json(*, model: str, messages: list[dict]) -> dict`
  - `OpenAICompatLLM(client: openai.AsyncOpenAI | None = None)` — default client from `settings.litellm.base_url` / `api_key` / `timeout_s`
  - `extract_json(text: str) -> dict` — accepts raw JSON or fenced ```json blocks; raises `ValueError`
  - `tests/test_lens/fakes.py`: `FakeLLM(chat_replies: list[ChatReply] = [], json_replies: list[dict | Exception] = [])` recording `.chat_calls` / `.json_calls`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lens/test_llm.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens.llm'`

- [ ] **Step 3: Implement**

`src/lens/llm.py`:

```python
"""OpenAI-compatible chat client (LiteLLM proxy) for tool-use and JSON output."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from openai import AsyncOpenAI

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
        resp = await self._client.chat.completions.create(
            model=model, messages=messages, response_format={"type": "json_object"},
        )
        return extract_json(resp.choices[0].message.content or "")
```

`tests/test_lens/fakes.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lens/test_llm.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit (after user go-ahead)**

```bash
git add src/lens/llm.py tests/test_lens/fakes.py tests/test_lens/test_llm.py
git commit -m "feat(lens): OpenAI-compatible LLM client with tool calls and JSON mode"
```

---

### Task 9: Router (workspace commands)

**Files:**
- Create: `src/lens/router.py`
- Test: `tests/test_lens/test_router.py`

**Interfaces:**
- Consumes: `CanvasState` (Task 4); `TableEl` (Task 1)
- Produces:
  - `@dataclass Command(ops: list[tuple[OpKind, dict]] = [], reply: str | None = None, open_query: str | None = None)`
  - `@dataclass Search(text: str)`
  - `route(text: str, mentions: list[str], state: CanvasState) -> Command | Search`
  - `is_stop(text: str) -> bool` — `стоп|останови(сь)|прекрати|stop` as the whole input (handled by the Agent before the lock)

`text` never contains the `@mentions`; the frontend sends them as keys in `mentions`.
Every command regex matches the WHOLE input (optional trailing `.`/`!`).

Rules, first match wins:
1. `отмени|отмена|undo` → `undo` of `state.inputs[-1]`; empty → reply `"Нечего отменять."`
2. `(да,)? это одно (и то же)? | объедини` → needs exactly 2 mentions → `merge {keep: m[0], drop: m[1]}`; else reply
3. `(покажи )?таблицей( только <v1>[, и ]<v2>…)?` → aggregate mentions → one `add_view` TableEl each (with `filter={"*": [values]}`); no mentions → `set_mode table` (with values → reply asking for an @aggregate); non-aggregate mentions → reply
4. `(покажи )?(полем|на поле|карточками)` → `set_mode canvas`
5. `скрой|убери|спрячь <target>` → hide mentions, else resolve target among visible objects; 0 → reply `"Не нашёл «<target>» на поле."`; >1 → reply listing up to 5 labels + `"Уточни через @."`
6. `покажи|верни <target>` → mentions and no text → show mentions; else resolve among hidden objects; exactly 1 → `show`; >1 → ambiguity reply; 0 → **Search** ("покажи встречи…", "покажи связи @X")
7. `открой <title>` (no mentions) → `Command(open_query=title)`; the Agent opens a matching workspace or treats the input as a search
8. anything else → `Search(text)`

Target resolution: case-insensitive exact label wins; else every target word must match a label word by crude Russian stem (`_stem`: drop 2 chars if len>5, 1 if len>4) or as a ≥4-char prefix — never raw substrings.

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime

from src.lens.model import Op
from src.lens.router import Command, Search, is_stop, route
from src.lens.state import fold


def st(*objs, hidden=(), views=()):
    ops, seq = [], 0

    def add(kind, payload, iid="i1"):
        nonlocal seq
        seq += 1
        ops.append(Op(workspace_id="w", seq=seq, kind=kind, payload=payload, input_id=iid,
                      created_at=datetime.now(UTC)))

    add("add_objects", {"objects": [{"key": k, "type": "person", "label": lbl}
                                    for k, lbl in objs]})
    for v in views:
        add("add_view", {"view": v})
    if hidden:
        add("hide", {"keys": list(hidden)}, "i2")
    return fold(ops)


S = st(("kb:1", "Си Цзиньпин"), ("kb:2", "Си Юань"), ("kb:3", "Путин В."))


def test_plain_query_is_search():
    assert route("встречи Путина в Китае", [], S) == Search("встречи Путина в Китае")


def test_undo_last_input():
    r = route("отмени", [], S)
    assert r.ops == [("undo", {"input_id": "i1"})]
    assert route("отмени", [], fold([])).reply == "Нечего отменять."


def test_hide_by_mention_and_unique_label():
    assert route("скрой", ["kb:3"], S).ops == [("hide", {"keys": ["kb:3"]})]
    assert route("скрой путин", [], S).ops == [("hide", {"keys": ["kb:3"]})]
    assert route("убери Си Цзиньпин", [], S).ops == [("hide", {"keys": ["kb:1"]})]


def test_hide_ambiguous_replies_with_candidates():
    r = route("скрой Си", [], S)
    assert isinstance(r, Command) and r.ops == []
    assert "Си Цзиньпин" in r.reply and "Си Юань" in r.reply and "@" in r.reply


def test_hide_not_found():
    r = route("скрой Байден", [], S)
    assert r.ops == [] and "Байден" in r.reply


def test_show_hidden_else_search():
    h = st(("kb:1", "Си Цзиньпин"), hidden=["kb:1"])
    assert route("покажи Си", [], h).ops == [("show", {"keys": ["kb:1"]})]
    assert route("покажи встречи в Пекине", [], h) == Search("покажи встречи в Пекине")


def test_merge_needs_two_mentions():
    assert route("да, это одно", ["kb:1", "fofa:x"], S).ops == [
        ("merge", {"keep": "kb:1", "drop": "fofa:x"})]
    assert route("объедини", ["kb:1"], S).ops == []


def test_table_from_aggregate_mention_and_modes():
    agg = {"kind": "aggregate", "key": "agg:c1:h", "label": "ip · 30", "item_type": "ip",
           "count": 30, "rows_ref": {"call_id": "c1", "path": "$.hosts[*]"},
           "columns": [{"name": "id", "path": "$.ip"}]}
    s = st(("kb:1", "X"), views=[agg])
    (kind, payload), = route("таблицей", ["agg:c1:h"], s).ops
    assert kind == "add_view"
    assert payload["view"]["kind"] == "table"
    assert payload["view"]["key"] == "table:agg:c1:h"
    assert payload["view"]["rows_ref"] == {"call_id": "c1", "path": "$.hosts[*]"}
    assert route("покажи таблицей", [], s).ops == [("set_mode", {"mode": "table"})]
    assert route("полем", [], s).ops == [("set_mode", {"mode": "canvas"})]
    assert route("IP Росатома таблицей", [], s) == Search("IP Росатома таблицей")


AGG = {"kind": "aggregate", "key": "agg:c1:h", "label": "ip · 30", "item_type": "ip",
       "count": 30, "rows_ref": {"call_id": "c1", "path": "$.hosts[*]"},
       "columns": [{"name": "id", "path": "$.ip"}]}


def test_command_words_inside_a_query_are_searches():
    s = st(("kb:1", "X"))
    assert route("отмена санкций против России", [], s) == Search(
        "отмена санкций против России")
    assert route("объедини усилия ЕС и США", [], s) == Search("объедини усилия ЕС и США")
    assert route("отмени!", [], s).ops == [("undo", {"input_id": "i1"})]


def test_word_match_not_substring():
    s = st(("kb:1", "Си Цзиньпин"), ("kb:2", "Россия"))
    assert route("скрой Си", [], s).ops == [("hide", {"keys": ["kb:1"]})]


def test_declension_matches_by_stem():
    assert route("скрой Путина", [], st(("kb:1", "Путин В."))).ops == [
        ("hide", {"keys": ["kb:1"]})]


def test_hide_table_by_mention_is_hide_not_search():
    s = st(("kb:1", "X"), views=[AGG])
    assert route("скрой таблицу", ["table:agg:c1:h"], s).ops == [
        ("hide", {"keys": ["table:agg:c1:h"]})]


def test_table_filter_values():
    s = st(("kb:1", "X"), views=[AGG])
    (_, payload), = route("таблицей только 22 и 3389", ["agg:c1:h"], s).ops
    assert payload["view"]["filter"] == {"*": ["22", "3389"]}
    assert "агрегат" in route("таблицей", ["kb:1"], s).reply
    assert "@" in route("таблицей только 22", [], s).reply


def test_show_with_mention_and_text_is_search():
    s = st(("kb:1", "X"))
    assert route("покажи", ["kb:1"], s).ops == [("show", {"keys": ["kb:1"]})]
    assert route("покажи связи", ["kb:1"], s) == Search("покажи связи")


def test_open_and_stop():
    s = st(("kb:1", "X"))
    assert route("открой Росатом/Китай", [], s).open_query == "Росатом/Китай"
    assert is_stop("стоп") and is_stop("Останови.") and not is_stop("стоп-кран в поездах")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lens/test_router.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens.router'`

- [ ] **Step 3: Implement**

```python
"""Rule-based router: workspace commands compile to ops without MCP/LLM.

Commands are matched against the WHOLE input (so "отмена санкций" is a search, not
an undo).  Text targets ("скрой Путина") are matched by words with a crude Russian
stem, never by raw substring (so "Си" does not hit "Россия").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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
_WORD = re.compile(r"\w+", re.U)
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


def _stem(w: str) -> str:
    w = w.lower().replace("ё", "е")
    if len(w) > 5:
        return w[:-2]
    if len(w) > 4:
        return w[:-1]
    return w


def _words(s: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall(s)]


def _match(target: str, state: CanvasState, keys: list[str]) -> list[str]:
    t = target.strip().lower()
    if not t:
        return []
    exact = [k for k in keys if state.objects[k].label.lower() == t]
    if exact:
        return exact[:1]
    want = _words(t)
    found = []
    for k in keys:
        have = _words(state.objects[k].label)
        if want and all(any(h == w or (len(w) >= 4 and h.startswith(w)) for h in have)
                        for w in want):
            found.append(k)
    return found


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lens/test_router.py -q`
Expected: 15 passed

- [ ] **Step 5: Commit (after user go-ahead)**

```bash
git add src/lens/router.py tests/test_lens/test_router.py
git commit -m "feat(lens): rule-based router for workspace commands"
```

---

### Task 10: Normalizer (cache → LLM → validate → repair → raw)

**Files:**
- Create: `src/lens/normalizer.py`
- Test: `tests/test_lens/test_normalizer.py`

**Interfaces:**
- Consumes: `LensStore` (Task 6), `LLMClient` (Task 8), `ViewSpec`, `materialize`, `SpecError`, `Materialized` (Task 5), `sample_json` (Task 3), `ToolCallRecord`, `RawEl` (Task 1)
- Produces:
  - `@dataclass NormalizeResult(materialized: Materialized | None, raw: RawEl | None, source: Literal["cache", "llm", "repair", "raw"])`
  - `Normalizer(llm: LLMClient, store: LensStore, *, model: str, vocabulary: list[str], aggregate_threshold: int, sample_chars: int)`
  - `async normalize(call: ToolCallRecord, tool_description: str, known_keys: Collection[str] = ()) -> NormalizeResult`
  - `cache_key(call) -> str` = `f"{shape_hash}:{sha1(model|PROMPT_VERSION)[:8]}"`; `PROMPT_VERSION = "v2"`
  - `is_empty_result(payload) -> bool` — no strings and no non-empty containers anywhere
  - `build_prompt(call, tool_description, vocabulary, sample_chars, known_keys=()) -> list[dict]`

Behavior: error calls → raw (no LLM); empty results (`{"results": [], "total": 0}`) → raw `"empty result"` (no LLM). Cache hit that materializes non-empty → `cache`. Otherwise LLM → validate; spec error → exactly one repair message containing the errors → validate; success stores the spec. Any other LLM exception (timeout, connection) → raw `"normalizer unavailable: …"` — normalization never fails the input. An empty spec (`{"objects": []}`) → raw `"no objects in response"`; it is cached only when the payload has no lists of records (otherwise a flaky model would poison the cache).

- [ ] **Step 1: Write the failing test**

```python
import httpx
from openai import APITimeoutError

from src.lens.model import ToolCallRecord
from src.lens.normalizer import Normalizer, is_empty_result
from src.lens.shape import shape_hash
from src.lens.spec import ViewSpec
from src.lens.store import MemoryLensStore
from tests.test_lens.fakes import FakeLLM

PAYLOAD = {"results": [{"qid": "Q1", "name": "Росатом"}, {"qid": "Q2", "name": "ТВЭЛ"}]}
GOOD = {"objects": [{"name": "org", "each": "$.results[*]", "id": "$.qid",
                     "label": "$.name", "type": "organization"}]}
BAD = {"objects": [{"name": "org", "each": "$.items[*]", "id": "$.qid",
                    "label": "$.name", "type": "organization"}]}


def call(payload=PAYLOAD, is_error=False, args=None):
    return ToolCallRecord(id="c1", input_id="i1", server="kb-tools", namespace="kb",
                          tool="find", args=args or {}, payload=payload,
                          shape_hash=shape_hash(payload), is_error=is_error,
                          error="boom" if is_error else None, latency_ms=1)


def norm(llm, store=None, model="m"):
    return Normalizer(llm, store or MemoryLensStore(), model=model,
                      vocabulary=["organization", "person"], aggregate_threshold=25,
                      sample_chars=4000)


async def test_llm_spec_validated_and_cached_under_namespace():
    store = MemoryLensStore()
    llm = FakeLLM(json_replies=[GOOD])
    n = norm(llm, store)
    r = await n.normalize(call(), "Find orgs")
    assert r.source == "llm"
    assert [o.key for o in r.materialized.objects] == ["kb:Q1", "kb:Q2"]
    assert await store.get_spec("kb-tools", "find", n.cache_key(call())) == \
        ViewSpec.model_validate(GOOD)
    prompt = llm.json_calls[0]["messages"][-1]["content"]
    assert "Росатом" in prompt and "organization" in prompt and "Find orgs" in prompt


async def test_cache_hit_skips_llm():
    store = MemoryLensStore()
    n = norm(FakeLLM(), store)
    await store.put_spec("kb-tools", "find", n.cache_key(call()),
                         ViewSpec.model_validate(GOOD), "m")
    other = {"results": [{"qid": "Q9", "name": "Другое"}]}
    r = await n.normalize(call(other), "")
    assert r.source == "cache" and r.materialized.objects[0].key == "kb:Q9"
    assert n.llm.json_calls == []


async def test_model_change_invalidates_cache():
    store = MemoryLensStore()
    await norm(FakeLLM(json_replies=[GOOD]), store, model="m1").normalize(call(), "")
    llm2 = FakeLLM(json_replies=[GOOD])
    r = await norm(llm2, store, model="m2").normalize(call(), "")
    assert r.source == "llm" and len(llm2.json_calls) == 1


async def test_bad_spec_repaired_once():
    llm = FakeLLM(json_replies=[BAD, GOOD])
    r = await norm(llm).normalize(call(), "")
    assert r.source == "repair"
    assert "$.items[*]" in llm.json_calls[1]["messages"][-1]["content"]


async def test_two_failures_fall_back_to_raw():
    llm = FakeLLM(json_replies=[BAD, ValueError("no JSON")])
    r = await norm(llm).normalize(call(), "")
    assert r.source == "raw" and r.raw.key == "raw:c1" and r.materialized is None


async def test_llm_timeout_degrades_to_raw():
    llm = FakeLLM(json_replies=[APITimeoutError(request=httpx.Request("POST", "http://x"))])
    r = await norm(llm).normalize(call(), "")
    assert r.source == "raw" and "unavailable" in r.raw.reason


async def test_empty_result_skips_llm():
    llm = FakeLLM()
    for payload in ({"results": [], "total": 0}, {"results": []}, [], None):
        r = await norm(llm).normalize(call(payload), "")
        assert r.source == "raw" and r.raw.reason == "empty result"
    assert llm.json_calls == []
    assert not is_empty_result({"text": "prose"})


async def test_empty_spec_cached_only_for_object_free_payload():
    store = MemoryLensStore()
    n = norm(FakeLLM(json_replies=[{"objects": []}, {"objects": []}]), store)
    prose = {"text": "just prose"}
    r = await n.normalize(call(prose), "")
    assert r.source == "raw" and r.raw.reason == "no objects in response"
    assert await store.get_spec("kb-tools", "find", n.cache_key(call(prose))) == ViewSpec()
    await n.normalize(call(PAYLOAD), "")  # model flaked on real records
    assert await store.get_spec("kb-tools", "find", n.cache_key(call(PAYLOAD))) is None


async def test_known_keys_attach_relations_and_reach_prompt():
    spec = {"objects": [{"name": "n", "each": "$.results[*]", "id": "$.qid",
                         "label": "$.name", "type": "organization"}],
            "relations": [{"each": "$.results[*]", "from_id": "$args.id", "to_id": "$.qid",
                           "kind": "связан"}]}
    llm = FakeLLM(json_replies=[spec])
    r = await norm(llm).normalize(call(args={"id": "Q0"}), "", known_keys={"kb:Q0"})
    assert {rel.key for rel in r.materialized.relations} == {
        "kb:Q0|связан|kb:Q1", "kb:Q0|связан|kb:Q2"}
    assert "kb:Q0" in llm.json_calls[0]["messages"][-1]["content"]


async def test_error_call_is_raw_without_llm():
    llm = FakeLLM()
    r = await norm(llm).normalize(call(is_error=True), "")
    assert r.source == "raw" and "boom" in r.raw.reason
    assert llm.json_calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lens/test_normalizer.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens.normalizer'`

- [ ] **Step 3: Implement**

```python
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
    known = sorted(k for k in known_keys if k.startswith(f"{call.ns}:"))[:50]
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lens/test_normalizer.py -q`
Expected: 10 passed

- [ ] **Step 5: Commit (after user go-ahead)**

```bash
git add src/lens/normalizer.py tests/test_lens/test_normalizer.py
git commit -m "feat(lens): normalizer with spec cache, one repair, raw fallback"
```

---

### Task 11: Planner (tool-use loop)

**Files:**
- Create: `src/lens/planner.py`
- Test: `tests/test_lens/test_planner.py`

**Interfaces:**
- Consumes: `McpHub`, `ToolInfo` (Task 7); `LLMClient`, `ChatReply`, `ToolCallReq` (Task 8); `LensStore` (Task 6); `shape_hash`, `sample_json` (Task 3); `ToolCallRecord` (Task 1)
- Produces:
  - `@dataclass PlannerStatus(server: str, tool: str, state: Literal["calling", "done", "error"], message: str = "")`
  - `@dataclass ToolCalled(record: ToolCallRecord, tool: ToolInfo)`
  - `@dataclass PlannerFinal(text: str)`
  - `Planner(llm, hub, store, *, model: str, max_steps: int, sample_chars: int)`
  - `run(*, input_id: str, text: str, mentions: list[dict], canvas_summary: str) -> AsyncIterator[PlannerStatus | ToolCalled | PlannerFinal]` — calls `hub.refresh()` first; records carry the tool's namespace; the system prompt asks for `[[namespace:id]]` citations; after `max_steps` one final call with `tool_choice="none"`; always ends with exactly one `PlannerFinal`
  - `openai_tools(catalog: list[ToolInfo]) -> list[dict]`

- [ ] **Step 1: Write the failing test**

```python
from src.lens.llm import ChatReply, ToolCallReq
from src.lens.mcp_hub import ToolInfo, ToolResult
from src.lens.planner import Planner, PlannerFinal, PlannerStatus, ToolCalled, openai_tools
from src.lens.store import MemoryLensStore
from tests.test_lens.fakes import FakeLLM

INFO = ToolInfo(server="kb", name="find", description="Find entity",
                input_schema={"type": "object", "properties": {"name": {"type": "string"}}},
                namespace="kbns")


class FakeHub:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def refresh(self):
        self.refreshed = True

    def catalog(self):
        return [INFO]

    def find(self, q):
        return INFO if q == INFO.qualified else None

    async def call(self, server, tool, args):
        self.calls.append((server, tool, args))
        return self.results.pop(0)


def tc(name="kb__find", args=None, id_="t1"):
    return ChatReply(text=None, tool_calls=[ToolCallReq(id=id_, name=name,
                                                        arguments=args or {"name": "X"})])


async def collect(planner, **kw):
    kw = {"input_id": "i1", "text": "кто такой X", "mentions": [], "canvas_summary": "",
          **kw}
    return [e async for e in planner.run(**kw)]


def make(llm, hub, store=None, max_steps=4):
    return Planner(llm, hub, store or MemoryLensStore(), model="m", max_steps=max_steps,
                   sample_chars=2000)


def test_openai_tools_shape():
    (t,) = openai_tools([INFO])
    assert t["type"] == "function"
    assert t["function"]["name"] == "kb__find"
    assert t["function"]["parameters"]["properties"]["name"]["type"] == "string"


async def test_tool_then_final():
    store = MemoryLensStore()
    hub = FakeHub([ToolResult(payload={"id": "Q1", "name": "X"})])
    llm = FakeLLM(chat_replies=[tc(), ChatReply(text="X — это ...")])
    evs = await collect(make(llm, hub, store))
    kinds = [type(e).__name__ for e in evs]
    assert kinds == ["PlannerStatus", "PlannerStatus", "ToolCalled", "PlannerFinal"]
    called = evs[2]
    assert isinstance(called, ToolCalled)
    assert called.record.ns == "kbns"
    assert hub.refreshed is True
    assert (await store.get_tool_call(called.record.id)).payload == {"id": "Q1", "name": "X"}
    assert evs[-1] == PlannerFinal("X — это ...")
    second_msgs = llm.chat_calls[1]["messages"]
    assert second_msgs[-1]["role"] == "tool" and '"Q1"' in second_msgs[-1]["content"]


async def test_tool_error_reported_and_loop_continues():
    hub = FakeHub([ToolResult(payload=None, is_error=True, error="kaput")])
    llm = FakeLLM(chat_replies=[tc(), ChatReply(text="не удалось")])
    evs = await collect(make(llm, hub))
    statuses = [e for e in evs if isinstance(e, PlannerStatus)]
    assert statuses[-1].state == "error" and "kaput" in statuses[-1].message
    assert evs[2].record.is_error is True
    assert "ERROR: kaput" in llm.chat_calls[1]["messages"][-1]["content"]


async def test_unknown_tool_is_told_to_llm():
    hub = FakeHub([])
    llm = FakeLLM(chat_replies=[tc(name="nope__x"), ChatReply(text="ok")])
    evs = await collect(make(llm, hub))
    assert hub.calls == []
    assert "unknown tool" in llm.chat_calls[1]["messages"][-1]["content"]
    assert isinstance(evs[-1], PlannerFinal)


async def test_step_limit_forces_final_without_tools():
    hub = FakeHub([ToolResult(payload={"a": i}) for i in range(5)])
    llm = FakeLLM(chat_replies=[tc(id_=f"t{i}") for i in range(2)]
                  + [ChatReply(text="итог")])
    evs = await collect(make(llm, hub, max_steps=2))
    assert evs[-1] == PlannerFinal("итог")
    assert llm.chat_calls[-1]["tool_choice"] == "none"
    assert llm.chat_calls[-1]["tools"] is not None


async def test_mentions_and_canvas_in_prompt():
    llm = FakeLLM(chat_replies=[ChatReply(text="ok")])
    await collect(make(llm, FakeHub([])),
                  mentions=[{"key": "kb:1", "type": "organization", "label": "Росатом"}],
                  canvas_summary="Росатом (organization)")
    user = llm.chat_calls[0]["messages"][-1]["content"]
    assert "kb:1" in user and "Росатом (organization)" in user


async def test_namespaces_and_key_rule_in_prompt():
    llm = FakeLLM(chat_replies=[ChatReply(text="ok")])
    await collect(make(llm, FakeHub([])))
    msgs = llm.chat_calls[0]["messages"]
    assert "[[" in msgs[0]["content"]
    assert "kb→kbns" in msgs[-1]["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lens/test_planner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens.planner'`

- [ ] **Step 3: Implement**

```python
"""Tool-use loop over the merged MCP catalog."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal

from src.lens.llm import LLMClient
from src.lens.mcp_hub import McpHub, ToolInfo
from src.lens.model import ToolCallRecord
from src.lens.shape import sample_json, shape_hash
from src.lens.store import LensStore

SYSTEM = """You are the research agent of an object-centric workspace.
Use the tools to find facts about the objects in the user's request.
- Selected objects (with their source keys and ids) are the context of the request;
  use their ids in tool arguments when a tool accepts ids.
- Call tools step by step; chain them (pivot) when one result gives ids for the next.
- Never state facts that no tool returned.
- Finish with a short answer (max 5 sentences) in the language of the request.
- In the answer, mark every object you mention with its canvas key in double brackets
  right after the name: "Росатом [[kb:Q1]]". A key is "<namespace>:<id>"; namespaces are
  listed with the tools; ids are the ones the tools returned. Never invent keys.
"""


@dataclass
class PlannerStatus:
    server: str
    tool: str
    state: Literal["calling", "done", "error"]
    message: str = ""


@dataclass
class ToolCalled:
    record: ToolCallRecord
    tool: ToolInfo


@dataclass
class PlannerFinal:
    text: str


def openai_tools(catalog: list[ToolInfo]) -> list[dict]:
    return [
        {"type": "function", "function": {
            "name": t.qualified,
            "description": t.description[:1024],
            "parameters": t.input_schema or {"type": "object", "properties": {}},
        }}
        for t in catalog
    ]


class Planner:
    def __init__(
        self, llm: LLMClient, hub: McpHub, store: LensStore, *,
        model: str, max_steps: int, sample_chars: int,
    ) -> None:
        self.llm, self.hub, self.store = llm, hub, store
        self.model, self.max_steps, self.sample_chars = model, max_steps, sample_chars

    async def run(
        self, *, input_id: str, text: str, mentions: list[dict], canvas_summary: str,
    ) -> AsyncIterator[PlannerStatus | ToolCalled | PlannerFinal]:
        await self.hub.refresh()
        catalog = self.hub.catalog()
        namespaces = sorted({f"{t.server}→{t.namespace}" for t in catalog})
        user = (
            f"Request: {text}\n"
            f"Selected objects: {json.dumps(mentions, ensure_ascii=False)}\n"
            f"Already on canvas: {canvas_summary or '-'}\n"
            f"Server namespaces: {', '.join(namespaces) or '-'}"
        )
        messages: list[dict] = [{"role": "system", "content": SYSTEM},
                                {"role": "user", "content": user}]
        tools = openai_tools(catalog)

        for _ in range(self.max_steps):
            reply = await self.llm.chat(model=self.model, messages=messages, tools=tools)
            if not reply.tool_calls:
                yield PlannerFinal(reply.text or "")
                return
            messages.append({"role": "assistant", "content": reply.text, "tool_calls": [
                {"id": c.id, "type": "function",
                 "function": {"name": c.name,
                              "arguments": json.dumps(c.arguments, ensure_ascii=False)}}
                for c in reply.tool_calls]})
            for c in reply.tool_calls:
                info = self.hub.find(c.name)
                if info is None:
                    messages.append({"role": "tool", "tool_call_id": c.id,
                                     "content": f"ERROR: unknown tool {c.name!r}"})
                    continue
                yield PlannerStatus(info.server, info.name, "calling")
                t0 = time.monotonic()
                res = await self.hub.call(info.server, info.name, c.arguments)
                rec = ToolCallRecord(
                    id=uuid.uuid4().hex, input_id=input_id, server=info.server,
                    namespace=info.namespace or None, tool=info.name, args=c.arguments, payload=res.payload,
                    shape_hash=shape_hash(res.payload), is_error=res.is_error,
                    error=res.error, latency_ms=int((time.monotonic() - t0) * 1000),
                )
                await self.store.add_tool_call(rec)
                if res.is_error:
                    yield PlannerStatus(info.server, info.name, "error", res.error or "")
                    content = f"ERROR: {res.error}"
                else:
                    yield PlannerStatus(info.server, info.name, "done")
                    content = sample_json(res.payload, self.sample_chars)
                yield ToolCalled(rec, info)
                messages.append({"role": "tool", "tool_call_id": c.id, "content": content})

        messages.append({"role": "user",
                         "content": "Step limit reached. Answer now from what you have."})
        # Keep tools declared (some providers reject tool messages without them) but
        # forbid further calls.
        final = await self.llm.chat(model=self.model, messages=messages, tools=tools or None,
                                    tool_choice="none" if tools else None)
        yield PlannerFinal(final.text or "")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lens/test_planner.py -q`
Expected: 7 passed

- [ ] **Step 5: Commit (after user go-ahead)**

```bash
git add src/lens/planner.py tests/test_lens/test_planner.py
git commit -m "feat(lens): tool-use planner over merged MCP catalog"
```

---

### Task 12: Event bus and Agent orchestration

**Files:**
- Create: `src/lens/events.py`, `src/lens/agent.py`
- Test: `tests/test_lens/test_events.py`, `tests/test_lens/test_agent.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `EventBus(queue_max: int = 1000)`: `subscribe`, `unsubscribe`, `subscriber_count(workspace_id) -> int`, `publish(workspace_id, event)` — non-blocking; a full queue is emptied, gets `{"type":"resync"}` and is unsubscribed
  - `sse_stream(bus, workspace_id, *, heartbeat_s: float = 15.0) -> AsyncIterator[str]` — first frame `ready`, then `"event: <type>\ndata: <json>\n\n"`; `": ping\n\n"` on idle; ends after `resync`
  - Event shapes: `{"type":"ops","ops":[Op json]}`, `{"type":"status","input_id","server","tool","state","message"}`, `{"type":"reply","input_id","text"}`, `{"type":"input_done","input_id","status":"done"|"failed"|"cancelled"}`, `{"type":"open_workspace","input_id","workspace_id","title"}`, `{"type":"ready"}`, `{"type":"resync"}`
  - `Agent(*, store, bus, planner, normalizer)`:
    - `async submit(workspace_id, text, mentions) -> str` — stores input; `стоп` cancels the running input of that workspace; otherwise schedules `process`
    - `async process(workspace_id, input_id, text, mentions) -> None` — serialized per workspace
    - `async pin(workspace_id, key, x, y) -> list[Op]` — does NOT take the input lock
  - `same_as_candidates(new: list[ObjectEl], existing: dict[str, ObjectEl]) -> list[RelationEl]` — cross-namespace, same type, same normalized label → `same_as?` (confidence 0.5)
  - `resolve_citations(text: str, known: set[str]) -> tuple[str, list[str]]` — keeps `[[key]]` markers naming real canvas elements, drops invented ones
    - `async drain() -> None` — awaits scheduled tasks (tests, shutdown)

- [ ] **Step 1: Write the failing tests**

`tests/test_lens/test_events.py`:

```python
import asyncio
import json

from src.lens.events import EventBus, sse_stream


async def test_publish_reaches_subscribers_of_that_workspace_only():
    bus = EventBus()
    a, b = bus.subscribe("w1"), bus.subscribe("w2")
    bus.publish("w1", {"type": "reply", "text": "x"})
    assert a.get_nowait() == {"type": "reply", "text": "x"}
    assert b.empty()
    bus.unsubscribe("w1", a)
    bus.publish("w1", {"type": "reply"})
    assert a.empty()


async def test_overflow_sends_resync_and_unsubscribes():
    bus = EventBus(queue_max=2)
    q = bus.subscribe("w")
    for i in range(3):
        bus.publish("w", {"type": "ops", "i": i})
    assert q.get_nowait() == {"type": "resync"} and q.empty()
    assert bus.subscriber_count("w") == 0


async def test_sse_stream_ready_event_then_data():
    bus = EventBus()
    gen = sse_stream(bus, "w", heartbeat_s=60)
    assert await gen.__anext__() == 'event: ready\ndata: {"type": "ready"}\n\n'
    bus.publish("w", {"type": "reply", "text": "привет"})  # subscription is live now
    frame = await gen.__anext__()
    assert frame.startswith("event: reply\n")
    assert json.loads(frame.split("data: ", 1)[1]) == {"type": "reply", "text": "привет"}
    await gen.aclose()
    assert bus.subscriber_count("w") == 0


async def test_sse_stream_heartbeat_when_idle():
    bus = EventBus()
    gen = sse_stream(bus, "w", heartbeat_s=0.01)
    await gen.__anext__()  # ready
    assert await asyncio.wait_for(gen.__anext__(), timeout=5) == ": ping\n\n"
    await gen.aclose()


async def test_sse_stream_ends_after_resync():
    bus = EventBus(queue_max=1)
    gen = sse_stream(bus, "w", heartbeat_s=60)
    await gen.__anext__()  # ready
    bus.publish("w", {"type": "ops"})
    bus.publish("w", {"type": "ops"})  # overflow
    assert (await gen.__anext__()).startswith("event: resync")
    try:
        await gen.__anext__()
        raise AssertionError("stream should have ended")
    except StopAsyncIteration:
        pass
```

`tests/test_lens/test_agent.py`:

```python
import asyncio

from src.lens.agent import Agent, resolve_citations, same_as_candidates
from src.lens.events import EventBus
from src.lens.llm import ChatReply, ToolCallReq
from src.lens.mcp_hub import ToolInfo, ToolResult
from src.lens.model import ObjectEl
from src.lens.normalizer import Normalizer
from src.lens.planner import Planner, PlannerFinal
from src.lens.state import fold
from src.lens.store import MemoryLensStore
from tests.test_lens.fakes import FakeLLM

INFO = ToolInfo(server="kb-tools", name="find", description="Find",
                input_schema={"type": "object", "properties": {}}, namespace="kb")
SPEC = {"objects": [{"name": "org", "each": "$.results[*]", "id": "$.qid",
                     "label": "$.name", "type": "organization"}]}


class FakeHub:
    def __init__(self, results):
        self.results = list(results)

    async def refresh(self):
        return None

    def catalog(self):
        return [INFO]

    def find(self, q):
        return INFO if q == INFO.qualified else None

    async def call(self, server, tool, args):
        return self.results.pop(0)


def build(chat, json_replies, results):
    store, bus = MemoryLensStore(), EventBus()
    llm = FakeLLM(chat_replies=chat, json_replies=json_replies)
    hub = FakeHub(results)
    planner = Planner(llm, hub, store, model="m", max_steps=4, sample_chars=2000)
    normalizer = Normalizer(llm, store, model="m", vocabulary=["organization"],
                            aggregate_threshold=25, sample_chars=2000)
    return Agent(store=store, bus=bus, planner=planner, normalizer=normalizer), store, bus


def call_reply():
    return ChatReply(text=None, tool_calls=[ToolCallReq(id="t1", name="kb-tools__find",
                                                        arguments={})])


def drain_queue(q):
    return [q.get_nowait() for _ in range(q.qsize())]


async def test_search_input_produces_objects_cited_note_and_events():
    agent, store, bus = build(
        [call_reply(), ChatReply(text="Нашёл Росатом [[kb:Q1]] и ещё [[kb:FAKE]].")], [SPEC],
        [ToolResult(payload={"results": [{"qid": "Q1", "name": "Росатом"}]})])
    ws = await store.create_workspace("t")
    q = bus.subscribe(ws.id)
    iid = await agent.submit(ws.id, "Росатом", [])
    await agent.drain()
    st = fold(await store.list_ops(ws.id))
    assert list(st.objects) == ["kb:Q1"]
    note = st.notes[0]
    assert note.text == "Нашёл Росатом [[kb:Q1]] и ещё."
    assert note.cites == ["kb:Q1"] and len(note.calls) == 1
    events = drain_queue(q)
    assert {"status", "ops"} <= {e["type"] for e in events}
    assert events[-1] == {"type": "input_done", "input_id": iid, "status": "done"}
    assert (await store.get_input(iid))["status"] == "done"


async def test_tool_error_becomes_raw_view():
    agent, store, _ = build(
        [call_reply(), ChatReply(text="Источник недоступен.")], [],
        [ToolResult(payload=None, is_error=True, error="kaput")])
    ws = await store.create_workspace("t")
    await agent.submit(ws.id, "Росатом", [])
    await agent.drain()
    st = fold(await store.list_ops(ws.id))
    (raw,) = [v for v in st.views.values() if v["kind"] == "raw"]
    assert "kaput" in raw["reason"]


async def test_command_input_skips_planner_and_replies():
    agent, store, bus = build([], [], [])
    ws = await store.create_workspace("t")
    q = bus.subscribe(ws.id)
    await agent.submit(ws.id, "отмени", [])
    await agent.drain()
    ev = q.get_nowait()
    assert ev["type"] == "reply" and ev["text"] == "Нечего отменять."


async def test_planner_crash_marks_input_failed():
    agent, store, bus = build([], [], [])

    async def boom(**kw):
        raise RuntimeError("llm down")
        yield  # pragma: no cover

    agent.planner.run = boom
    ws = await store.create_workspace("t")
    q = bus.subscribe(ws.id)
    iid = await agent.submit(ws.id, "Росатом", [])
    await agent.drain()
    assert (await store.get_input(iid))["status"] == "failed"
    assert drain_queue(q)[-1]["status"] == "failed"


def _blocking_planner(agent, started: asyncio.Event):
    async def slow(**kw):
        started.set()
        await asyncio.Event().wait()  # never finishes on its own
        yield PlannerFinal("never")  # pragma: no cover

    agent.planner.run = slow


async def test_pin_does_not_wait_for_running_search():
    agent, store, _ = build([], [], [])
    started = asyncio.Event()
    _blocking_planner(agent, started)
    ws = await store.create_workspace("t")
    await agent.submit(ws.id, "долгий поиск", [])
    await started.wait()
    (op,) = await asyncio.wait_for(agent.pin(ws.id, "kb:1", 10.0, 20.0), timeout=1)
    assert op.kind == "pin" and op.input_id is None
    await agent.submit(ws.id, "стоп", [])
    await agent.drain()


async def test_stop_cancels_running_input():
    agent, store, bus = build([], [], [])
    started = asyncio.Event()
    _blocking_planner(agent, started)
    ws = await store.create_workspace("t")
    q = bus.subscribe(ws.id)
    iid = await agent.submit(ws.id, "долгий поиск", [])
    await started.wait()
    await agent.submit(ws.id, "стоп", [])
    await agent.drain()
    assert (await store.get_input(iid))["status"] == "cancelled"
    texts = [e.get("text") for e in drain_queue(q) if e["type"] == "reply"]
    assert "Останавливаю текущий запрос." in texts and "Остановлено." in texts


async def test_open_workspace_or_fall_back_to_search():
    agent, store, bus = build([ChatReply(text="ничего")], [], [])
    ws = await store.create_workspace("Росатом/Китай")
    q = bus.subscribe(ws.id)
    await agent.submit(ws.id, "открой росатом", [])
    await agent.drain()
    (ev,) = [e for e in drain_queue(q) if e["type"] == "open_workspace"]
    assert ev["workspace_id"] == ws.id
    await agent.submit(ws.id, "открой данные по Тяньвань", [])
    await agent.drain()
    assert agent.planner.llm.chat_calls, "unknown workspace must go to the planner"


def test_same_as_candidates_cross_namespace_only():
    existing = {"fofa:x": ObjectEl(key="fofa:x", type="organization", label="РОСАТОМ"),
                "kb:Q7": ObjectEl(key="kb:Q7", type="organization", label="Росатом")}
    new = [ObjectEl(key="kb:Q1", type="organization", label="«Росатом»")]
    rels = same_as_candidates(new, existing)
    assert [(r.from_key, r.to_key, r.kind) for r in rels] == [("kb:Q1", "fofa:x", "same_as?")]


def test_resolve_citations():
    text, cites = resolve_citations("A [[kb:1]], B [[x:2]] и A [[kb:1]]", {"kb:1"})
    assert text == "A [[kb:1]], B и A [[kb:1]]" and cites == ["kb:1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_lens/test_events.py tests/test_lens/test_agent.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens.events'`

- [ ] **Step 3: Implement**

`src/lens/events.py`:

```python
"""Per-workspace pub/sub and SSE framing.

Client protocol (no lost updates):
1. open the stream and wait for ``ready`` (subscription is live);
2. ``GET /workspaces/{id}`` → state with ``last_seq``;
3. apply ``ops`` events, ignoring ops with ``seq <= last_seq``; on a seq gap call
   ``GET /workspaces/{id}/ops?after_seq=<last>``;
4. on ``resync`` (the client fell behind and its queue overflowed) the stream ends:
   reconnect and start again from 1.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

QUEUE_MAX = 1000


class EventBus:
    def __init__(self, queue_max: int = QUEUE_MAX) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = {}
        self._queue_max = queue_max

    def subscribe(self, workspace_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._queue_max)
        self._subs.setdefault(workspace_id, set()).add(q)
        return q

    def unsubscribe(self, workspace_id: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(workspace_id)
        if subs is not None:
            subs.discard(q)
            if not subs:
                del self._subs[workspace_id]

    def subscriber_count(self, workspace_id: str) -> int:
        return len(self._subs.get(workspace_id, ()))

    def publish(self, workspace_id: str, event: dict) -> None:
        for q in list(self._subs.get(workspace_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer: drop its backlog, tell it to resync, cut it off.
                while not q.empty():
                    q.get_nowait()
                q.put_nowait({"type": "resync"})
                self.unsubscribe(workspace_id, q)


def _frame(ev: dict) -> str:
    return f"event: {ev.get('type', 'message')}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"


async def sse_stream(
    bus: EventBus, workspace_id: str, *, heartbeat_s: float = 15.0,
) -> AsyncIterator[str]:
    q = bus.subscribe(workspace_id)
    try:
        yield _frame({"type": "ready"})
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=heartbeat_s)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            yield _frame(ev)
            if ev.get("type") == "resync":
                return
    finally:
        bus.unsubscribe(workspace_id, q)
```

`src/lens/agent.py`:

```python
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
    items = [f"{o.label} ({o.type}) [{k}]" for k, o in reversed(st.objects.items())
             if k not in st.hidden]
    return "; ".join(items[:limit])


def _norm_label(label: str) -> str:
    return _NORM.sub(" ", label.casefold().replace("ё", "е")).strip()


def _ns(key: str) -> str:
    return key.split(":", 1)[0]


def same_as_candidates(new: list[ObjectEl], existing: dict[str, ObjectEl]) -> list[RelationEl]:
    """Cross-namespace objects with the same type and normalized label → ``same_as?``."""
    index: dict[tuple[str, str], list[str]] = defaultdict(list)
    for k, o in existing.items():
        index[(o.type, _norm_label(o.label))].append(k)
    out: list[RelationEl] = []
    for o in new:
        for other in index.get((o.type, _norm_label(o.label)), []):
            if _ns(other) != _ns(o.key):
                out.append(RelationEl(from_key=o.key, to_key=other, kind="same_as?",
                                      confidence=0.5))
        index[(o.type, _norm_label(o.label))].append(o.key)
    return out


def resolve_citations(text: str, known: set[str]) -> tuple[str, list[str]]:
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
        self, *, store: LensStore, bus: EventBus, planner: Planner, normalizer: Normalizer,
    ) -> None:
        self.store, self.bus = store, bus
        self.planner, self.normalizer = planner, normalizer
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._tasks: set[asyncio.Task] = set()
        self._current: dict[str, asyncio.Task] = {}

    async def submit(self, workspace_id: str, text: str, mentions: list[str]) -> str:
        input_id = await self.store.add_input(workspace_id, text, mentions)
        if is_stop(text):
            running = self._current.get(workspace_id)
            if running is not None and not running.done():
                running.cancel()
                reply = "Останавливаю текущий запрос."
            else:
                reply = "Сейчас ничего не выполняется."
            await self.store.set_input_status(input_id, "done")
            self.bus.publish(workspace_id, {"type": "reply", "input_id": input_id,
                                            "text": reply})
            self.bus.publish(workspace_id, {"type": "input_done", "input_id": input_id,
                                            "status": "done"})
            return input_id
        task = asyncio.create_task(self.process(workspace_id, input_id, text, mentions))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return input_id

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def pin(self, workspace_id: str, key: str, x: float, y: float) -> list[Op]:
        return await self._append(workspace_id, None, [("pin", {"key": key, "x": x, "y": y})])

    async def _append(
        self, workspace_id: str, input_id: str | None, ops: list[tuple[OpKind, dict]],
    ) -> list[Op]:
        if not ops:
            return []
        written = await self.store.append_ops(workspace_id, input_id, ops)
        self.bus.publish(workspace_id, {"type": "ops",
                                        "ops": [o.model_dump(mode="json") for o in written]})
        return written

    def _reply(self, workspace_id: str, input_id: str, text: str) -> None:
        self.bus.publish(workspace_id, {"type": "reply", "input_id": input_id, "text": text})

    async def process(
        self, workspace_id: str, input_id: str, text: str, mentions: list[str],
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
            self.bus.publish(workspace_id, {"type": "input_done", "input_id": input_id,
                                            "status": status})

    async def _open(self, workspace_id: str, input_id: str, query: str) -> bool:
        q = query.casefold()
        found = [w for w in await self.store.list_workspaces() if q in w.title.casefold()]
        if len(found) == 1:
            self.bus.publish(workspace_id, {"type": "open_workspace", "input_id": input_id,
                                            "workspace_id": found[0].id,
                                            "title": found[0].title})
            return True
        if len(found) > 1:
            titles = ", ".join(w.title for w in found[:5])
            self._reply(workspace_id, input_id, f"Подходят несколько расследований: {titles}.")
            return True
        return False

    async def _process(
        self, workspace_id: str, input_id: str, text: str, mentions: list[str],
    ) -> None:
        state = fold(await self.store.list_ops(workspace_id))
        decision = route(text, mentions, state)
        if isinstance(decision, Command):
            if decision.open_query is not None:
                if await self._open(workspace_id, input_id, decision.open_query):
                    return
                decision = Search(text.strip())  # no such workspace: it's a query
            else:
                await self._append(workspace_id, input_id, decision.ops)
                if decision.reply:
                    self._reply(workspace_id, input_id, decision.reply)
                return
        await self._search(workspace_id, input_id, decision.text, mentions, state)

    async def _search(
        self, workspace_id: str, input_id: str, text: str, mentions: list[str],
        state: CanvasState,
    ) -> None:
        canon_mentions = [state.canon(m) for m in mentions]
        mention_ctx = [
            state.objects[k].model_dump(mode="json", include={"key", "type", "label", "attrs"})
            for k in canon_mentions if k in state.objects
        ]
        known_objects: dict[str, ObjectEl] = dict(state.objects)
        known_keys: set[str] = set(state.objects) | set(canon_mentions) | set(state.views)
        calls: list[str] = []
        async for ev in self.planner.run(input_id=input_id, text=text, mentions=mention_ctx,
                                         canvas_summary=_canvas_summary(state)):
            if isinstance(ev, PlannerStatus):
                self.bus.publish(workspace_id, {
                    "type": "status", "input_id": input_id, "server": ev.server,
                    "tool": ev.tool, "state": ev.state, "message": ev.message})
            elif isinstance(ev, ToolCalled):
                calls.append(ev.record.id)
                result = await self.normalizer.normalize(ev.record, ev.tool.description,
                                                         known_keys)
                ops: list[tuple[OpKind, dict]] = []
                m = result.materialized
                if m is not None:
                    relations = list(m.relations)
                    if m.objects:
                        fresh = [o for o in m.objects if o.key not in known_objects]
                        relations += same_as_candidates(fresh, known_objects)
                        ops.append(("add_objects", {"objects": [
                            o.model_dump(mode="json") for o in m.objects]}))
                        for o in m.objects:
                            known_objects.setdefault(o.key, o)
                            known_keys.add(o.key)
                    if relations:
                        ops.append(("add_relations", {"relations": [
                            r.model_dump(mode="json") for r in relations]}))
                    for agg in m.aggregates:
                        ops.append(("add_view", {"view": agg.model_dump(mode="json")}))
                        known_keys.add(agg.key)
                if result.raw is not None:
                    ops.append(("add_view", {"view": result.raw.model_dump(mode="json")}))
                await self._append(workspace_id, input_id, ops)
            elif isinstance(ev, PlannerFinal) and ev.text.strip():
                body, cites = resolve_citations(ev.text, known_keys)
                note = NoteEl(key=f"note:{input_id}", text=body, cites=cites, calls=calls)
                await self._append(workspace_id, input_id,
                                   [("add_note", {"note": note.model_dump(mode="json")})])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_lens/test_events.py tests/test_lens/test_agent.py -q`
Expected: 14 passed

- [ ] **Step 5: Commit (after user go-ahead)**

```bash
git add src/lens/events.py src/lens/agent.py tests/test_lens/test_events.py tests/test_lens/test_agent.py
git commit -m "feat(lens): event bus, SSE framing and agent orchestration"
```

---

### Task 13: HTTP API, service wiring, compose

**Files:**
- Create: `src/lens/auth.py`, `src/lens/app.py`
- Modify: `docker-compose.prod.yml` (add `lens` service after `mcp-stats`)
- Test: `tests/test_lens/test_app.py`

**Interfaces:**
- Consumes: `Agent`, `EventBus`, `LensStore`, `McpHub`, `fold`, `state_to_dict`, `iter_path`, `resolve`, `PathError`
- Produces:
  - `@dataclass LensDeps(store, bus, agent, hub)`
  - `create_app(deps: LensDeps | None = None) -> FastAPI` — `None` ⇒ lifespan builds real deps from `lens_settings`
  - `app = create_app()` (uvicorn target `src.lens.app:app`)
  - `src/lens/auth.py`: `require_key` (header `X-API-Key` ∈ `LENS_API_KEYS`), `make_stream_token(workspace_id, secret, *, ttl_s=300, now=None)`, `check_stream_token(token, workspace_id, secret, *, now=None)`, `require_stream_token`
  - Routes (all under `/lens/v1`; auth = `X-API-Key` header, except `/health` and `/stream`):
    - `GET /health` → `{"mcp": {server: status}}` (no auth)
    - `POST /workspaces` `{"title"}` → Workspace
    - `GET /workspaces` → list
    - `GET /workspaces/{id}` → `{"workspace", "state"}`; 404 unknown
    - `POST /workspaces/{id}/input` `{"text", "mentions": []}` → 202 `{"input_id"}`; 422 on blank text
    - `GET /workspaces/{id}/ops?after_seq=N` → ops with `seq > N` (gap fill)
    - `POST /workspaces/{id}/pin` `{"key","x","y"}` → `{"seq"}`
    - `POST /workspaces/{id}/stream_token` → `{"token"}` (5 min, bound to the workspace)
    - `GET /workspaces/{id}/stream?token=…` → `text/event-stream`; 401 on bad/expired/other-workspace token
    - `GET /tool_calls/{id}/value?path=$...` → `{"value"}` (provenance click); 404 unknown call, 400 bad path
    - `GET /tool_calls/{id}/rows?path=&columns=<json list of Column>&filter=<json {col|"*": [values]}>&offset=0&limit=100` → `{"total", "rows": [{col: value}]}` (`total` after filtering)

- [ ] **Step 1: Write the failing test**

```python
import json

import httpx
import pytest

from src.lens.app import LensDeps, create_app
from src.lens.auth import check_stream_token, make_stream_token
from src.lens.config import lens_settings
from src.lens.events import EventBus
from src.lens.model import ToolCallRecord
from src.lens.store import MemoryLensStore

KEY = "test-lens-key"


class FakeAgent:
    def __init__(self, store):
        self.store = store
        self.submitted = []

    async def submit(self, ws, text, mentions):
        self.submitted.append((ws, text, mentions))
        return "i1"

    async def pin(self, ws, key, x, y):
        return await self.store.append_ops(ws, None, [("pin", {"key": key, "x": x, "y": y})])


class FakeHub:
    def status(self):
        return {"kb": "up"}


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(lens_settings, "api_keys", KEY)
    store = MemoryLensStore()
    deps = LensDeps(store=store, bus=EventBus(), agent=FakeAgent(store), hub=FakeHub())
    app = create_app(deps)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://t", headers={"X-API-Key": KEY}) as c:
        c.deps = deps
        yield c


async def test_health_is_public(client):
    r = await client.get("/lens/v1/health", headers={"X-API-Key": ""})
    assert r.json() == {"mcp": {"kb": "up"}}


async def test_auth_header_only_and_own_keys(client):
    assert (await client.get("/lens/v1/workspaces", headers={"X-API-Key": ""})).status_code \
        == 401
    assert (await client.get(f"/lens/v1/workspaces?key={KEY}",
                             headers={"X-API-Key": ""})).status_code == 401
    assert (await client.get("/lens/v1/workspaces",
                             headers={"X-API-Key": "dev-local-key"})).status_code == 403


async def test_workspace_input_pin_state_ops(client):
    ws = (await client.post("/lens/v1/workspaces", json={"title": "Росатом"})).json()
    r = await client.post(f"/lens/v1/workspaces/{ws['id']}/input",
                          json={"text": "встречи", "mentions": ["kb:1"]})
    assert r.status_code == 202 and r.json() == {"input_id": "i1"}
    assert client.deps.agent.submitted == [(ws["id"], "встречи", ["kb:1"])]
    assert (await client.post(f"/lens/v1/workspaces/{ws['id']}/input",
                              json={"text": "  "})).status_code == 422
    for i in range(2):
        r = await client.post(f"/lens/v1/workspaces/{ws['id']}/pin",
                              json={"key": "kb:1", "x": i, "y": 2})
    assert r.json() == {"seq": 2}
    body = (await client.get(f"/lens/v1/workspaces/{ws['id']}")).json()
    assert body["workspace"]["title"] == "Росатом" and body["state"]["last_seq"] == 2
    ops = (await client.get(f"/lens/v1/workspaces/{ws['id']}/ops",
                            params={"after_seq": 1})).json()
    assert [o["seq"] for o in ops] == [2]
    assert (await client.get("/lens/v1/workspaces/nope")).status_code == 404


async def test_tool_call_value_rows_and_filter(client):
    payload = {"hosts": [{"ip": f"10.0.0.{i}", "port": 22 + i} for i in range(5)]}
    await client.deps.store.add_tool_call(ToolCallRecord(
        id="c1", input_id=None, server="fofa", tool="hosts", args={}, payload=payload,
        shape_hash="h", latency_ms=1))
    v = await client.get("/lens/v1/tool_calls/c1/value", params={"path": "$.hosts[1].ip"})
    assert v.json() == {"value": "10.0.0.1"}
    cols = json.dumps([{"name": "ip", "path": "$.ip"}, {"name": "port", "path": "$.port"}])
    r = (await client.get("/lens/v1/tool_calls/c1/rows",
                          params={"path": "$.hosts[*]", "columns": cols, "offset": 1,
                                  "limit": 2})).json()
    assert r == {"total": 5, "rows": [{"ip": "10.0.0.1", "port": 23},
                                      {"ip": "10.0.0.2", "port": 24}]}
    f = (await client.get("/lens/v1/tool_calls/c1/rows",
                          params={"path": "$.hosts[*]", "columns": cols,
                                  "filter": json.dumps({"*": ["22", "25"]})})).json()
    assert [row["port"] for row in f["rows"]] == [22, 25] and f["total"] == 2
    assert (await client.get("/lens/v1/tool_calls/zz/value",
                             params={"path": "$"})).status_code == 404
    assert (await client.get("/lens/v1/tool_calls/c1/value",
                             params={"path": "hosts"})).status_code == 400


async def test_stream_requires_workspace_bound_token(client):
    ws = (await client.post("/lens/v1/workspaces", json={"title": "s"})).json()
    other = (await client.post("/lens/v1/workspaces", json={"title": "o"})).json()
    token = (await client.post(f"/lens/v1/workspaces/{ws['id']}/stream_token")).json()["token"]
    url = f"/lens/v1/workspaces/{other['id']}/stream"
    assert (await client.get(url, params={"token": token})).status_code == 401
    assert (await client.get(f"/lens/v1/workspaces/{ws['id']}/stream",
                             params={"token": "bad"})).status_code == 401
    # The SSE body itself is covered by test_events.py; httpx's ASGITransport buffers
    # whole bodies, so an infinite stream can't be read here.


def test_stream_token_expiry():
    tok = make_stream_token("w", "s", ttl_s=10, now=1000)
    assert check_stream_token(tok, "w", "s", now=1005)
    assert not check_stream_token(tok, "w", "s", now=1011)
    assert not check_stream_token(tok, "w", "other-secret", now=1005)
    assert not check_stream_token("garbage", "w", "s", now=1005)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lens/test_app.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens.app'`

- [ ] **Step 3: Implement `src/lens/auth.py` and `src/lens/app.py`**

`src/lens/auth.py`:

```python
"""Lens auth: own API keys (``LENS_API_KEYS``) + short-lived signed SSE tokens.

``EventSource`` can't send headers, and a long-lived key in a URL ends up in proxy
access logs.  So the stream takes ``?token=`` minted by an authenticated POST: it is
bound to one workspace and expires after ``ttl_s``.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import HTTPException, Request, status

from src.lens.config import lens_settings

STREAM_TOKEN_TTL_S = 300


def _sig(secret: str, workspace_id: str, exp: int) -> str:
    msg = f"{workspace_id}.{exp}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()[:32]


def make_stream_token(
    workspace_id: str, secret: str, *, ttl_s: int = STREAM_TOKEN_TTL_S, now: float | None = None,
) -> str:
    exp = int(now if now is not None else time.time()) + ttl_s
    return f"{exp}.{_sig(secret, workspace_id, exp)}"


def check_stream_token(
    token: str, workspace_id: str, secret: str, *, now: float | None = None,
) -> bool:
    try:
        exp_s, sig = token.split(".", 1)
        exp = int(exp_s)
    except ValueError:
        return False
    if exp < (now if now is not None else time.time()):
        return False
    return hmac.compare_digest(sig, _sig(secret, workspace_id, exp))


async def require_key(request: Request) -> None:
    key = request.headers.get("X-API-Key")
    if not key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-API-Key")
    if key not in lens_settings.keys_list():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid X-API-Key")


async def require_stream_token(request: Request, workspace_id: str) -> None:
    token = request.query_params.get("token", "")
    if not check_stream_token(token, workspace_id, lens_settings.stream_secret_value()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired stream token")
```

`src/lens/app.py`:

```python
"""Lens HTTP API.  Run: ``uvicorn src.lens.app:app --host 0.0.0.0 --port 8010``."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from src.lens.auth import make_stream_token, require_key, require_stream_token
from src.lens.config import lens_settings
from src.lens.events import EventBus, sse_stream
from src.lens.model import Column
from src.lens.paths import PathError, iter_path, resolve
from src.lens.state import fold, state_to_dict


@dataclass
class LensDeps:
    store: Any
    bus: EventBus
    agent: Any
    hub: Any


class NewWorkspace(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class InputBody(BaseModel):
    text: str
    mentions: list[str] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be blank")
        return v


class PinBody(BaseModel):
    key: str
    x: float
    y: float


def _deps(request: Request) -> LensDeps:
    return request.app.state.deps


async def _workspace_or_404(deps: LensDeps, workspace_id: str):
    ws = await deps.store.get_workspace(workspace_id)
    if ws is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace not found")
    return ws


async def _call_or_404(deps: LensDeps, call_id: str):
    rec = await deps.store.get_tool_call(call_id)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "tool call not found")
    return rec


def _row_matches(row: dict[str, Any], flt: dict[str, list[str]]) -> bool:
    for col, allowed in flt.items():
        values = row.values() if col == "*" else [row.get(col)]
        flat = [str(x) for v in values for x in (v if isinstance(v, list) else [v])]
        if not any(v in allowed for v in flat):
            return False
    return True


def _routes() -> tuple[APIRouter, APIRouter, APIRouter]:
    public = APIRouter(prefix="/lens/v1")
    api = APIRouter(prefix="/lens/v1", dependencies=[Depends(require_key)])
    stream_api = APIRouter(prefix="/lens/v1", dependencies=[Depends(require_stream_token)])

    @public.get("/health")
    async def health(deps: LensDeps = Depends(_deps)):
        return {"mcp": deps.hub.status()}

    @api.post("/workspaces")
    async def create_workspace(body: NewWorkspace, deps: LensDeps = Depends(_deps)):
        return (await deps.store.create_workspace(body.title)).model_dump(mode="json")

    @api.get("/workspaces")
    async def list_workspaces(deps: LensDeps = Depends(_deps)):
        return [w.model_dump(mode="json") for w in await deps.store.list_workspaces()]

    @api.get("/workspaces/{workspace_id}")
    async def get_workspace(workspace_id: str, deps: LensDeps = Depends(_deps)):
        ws = await _workspace_or_404(deps, workspace_id)
        state = fold(await deps.store.list_ops(workspace_id))
        return {"workspace": ws.model_dump(mode="json"), "state": state_to_dict(state)}

    @api.get("/workspaces/{workspace_id}/ops")
    async def get_ops(
        workspace_id: str, after_seq: int = Query(0, ge=0), deps: LensDeps = Depends(_deps),
    ):
        await _workspace_or_404(deps, workspace_id)
        return [o.model_dump(mode="json")
                for o in await deps.store.list_ops(workspace_id, after_seq=after_seq)]

    @api.post("/workspaces/{workspace_id}/input", status_code=status.HTTP_202_ACCEPTED)
    async def post_input(workspace_id: str, body: InputBody, deps: LensDeps = Depends(_deps)):
        await _workspace_or_404(deps, workspace_id)
        input_id = await deps.agent.submit(workspace_id, body.text, body.mentions)
        return {"input_id": input_id}

    @api.post("/workspaces/{workspace_id}/pin")
    async def pin(workspace_id: str, body: PinBody, deps: LensDeps = Depends(_deps)):
        await _workspace_or_404(deps, workspace_id)
        (op,) = await deps.agent.pin(workspace_id, body.key, body.x, body.y)
        return {"seq": op.seq}

    @api.post("/workspaces/{workspace_id}/stream_token")
    async def stream_token(workspace_id: str, deps: LensDeps = Depends(_deps)):
        await _workspace_or_404(deps, workspace_id)
        return {"token": make_stream_token(workspace_id, lens_settings.stream_secret_value())}

    @stream_api.get("/workspaces/{workspace_id}/stream")
    async def stream(workspace_id: str, deps: LensDeps = Depends(_deps)):
        await _workspace_or_404(deps, workspace_id)
        return StreamingResponse(sse_stream(deps.bus, workspace_id),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @api.get("/tool_calls/{call_id}/value")
    async def call_value(call_id: str, path: str, deps: LensDeps = Depends(_deps)):
        rec = await _call_or_404(deps, call_id)
        try:
            return {"value": resolve(rec.payload, path)}
        except PathError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    @api.get("/tool_calls/{call_id}/rows")
    async def call_rows(
        call_id: str,
        path: str,
        columns: str,
        filter: str = "{}",  # public query parameter name
        offset: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
        deps: LensDeps = Depends(_deps),
    ):
        rec = await _call_or_404(deps, call_id)
        try:
            cols = [Column.model_validate(c) for c in json.loads(columns)]
            flt = {str(k): [str(x) for x in v] for k, v in json.loads(filter).items()}
            rows = []
            for _, item in iter_path(rec.payload, path):
                row = {}
                for c in cols:
                    m = iter_path(item, c.path)
                    row[c.name] = m[0][1] if len(m) == 1 else [v for _, v in m] or None
                if _row_matches(row, flt):
                    rows.append(row)
        except (PathError, ValueError, AttributeError) as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
        return {"total": len(rows), "rows": rows[offset:offset + limit]}

    return public, api, stream_api


async def _build_deps() -> LensDeps:
    from src.lens.agent import Agent
    from src.lens.llm import OpenAICompatLLM
    from src.lens.mcp_hub import McpHub
    from src.lens.normalizer import Normalizer
    from src.lens.planner import Planner
    from src.lens.store import PgLensStore
    from src.storage.pg_pool import get_pg_pool

    store = PgLensStore(await get_pg_pool())
    await store.ensure_schema()
    hub = McpHub(lens_settings.mcp_servers, timeout_s=lens_settings.tool_timeout_s,
                 backoff_s=lens_settings.reconnect_backoff_s)
    await hub.start()
    llm, bus = OpenAICompatLLM(), EventBus()
    planner = Planner(llm, hub, store, model=lens_settings.planner_model(),
                      max_steps=lens_settings.max_tool_steps,
                      sample_chars=lens_settings.sample_chars)
    normalizer = Normalizer(llm, store, model=lens_settings.normalizer_model(),
                            vocabulary=lens_settings.vocabulary,
                            aggregate_threshold=lens_settings.aggregate_threshold,
                            sample_chars=lens_settings.sample_chars)
    agent = Agent(store=store, bus=bus, planner=planner, normalizer=normalizer)
    return LensDeps(store=store, bus=bus, agent=agent, hub=hub)


def create_app(deps: LensDeps | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if deps is not None:
            app.state.deps = deps
            yield
            return
        from src.storage.pg_pool import close_pg_pool

        app.state.deps = await _build_deps()
        try:
            yield
        finally:
            await app.state.deps.agent.drain()
            await app.state.deps.hub.close()
            await close_pg_pool()

    app = FastAPI(title="Lens", lifespan=lifespan)
    if deps is not None:
        app.state.deps = deps
    app.add_middleware(CORSMiddleware, allow_origins=lens_settings.cors_list(),
                       allow_methods=["GET", "POST"], allow_headers=["X-API-Key",
                                                                    "Content-Type"])
    for router in _routes():
        app.include_router(router)
    return app


app = create_app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lens/test_app.py -q`
Expected: 6 passed

- [ ] **Step 5: Add the compose service**

In `docker-compose.prod.yml`, after the `mcp-stats` service block (before the `backing services` banner), add:

```yaml
  # Lens — object-centric research workspace (agent + API). Talks to the KB only
  # through its MCP servers, exactly like any future external source. All KB servers
  # share the "kb" namespace so one entity gets one canvas key. MCP auth = a key from
  # API_KEYS (build_sse_auth); Lens's own clients use LENS_API_KEYS. Lens reconnects
  # lazily, so service_started is enough for the MCP dependencies.
  lens:
    <<: [*app-build]
    command: ["uvicorn", "src.lens.app:app", "--host", "0.0.0.0", "--port", "8010"]
    environment:
      <<: *app-env
      LENS_API_KEYS: ${LENS_API_KEYS:?set LENS_API_KEYS}
      LENS_STREAM_SECRET: ${LENS_STREAM_SECRET:-}
      LENS_CORS_ORIGINS: ${LENS_CORS_ORIGINS:-http://localhost:5173}
      LENS_MCP_SERVERS: >-
        [{"name":"kb-search","namespace":"kb","url":"http://mcp-search:9001/mcp","token":"${LENS_MCP_TOKEN:?set LENS_MCP_TOKEN to a key from API_KEYS}"},
         {"name":"kb-tools","namespace":"kb","url":"http://mcp-tools:9002/mcp","token":"${LENS_MCP_TOKEN:?set LENS_MCP_TOKEN to a key from API_KEYS}"},
         {"name":"kb-stats","namespace":"kb","url":"http://mcp-stats:9003/mcp","token":"${LENS_MCP_TOKEN:?set LENS_MCP_TOKEN to a key from API_KEYS}"}]
    ports:
      - "${LENS_PORT:-8010}:8010"
    depends_on:
      postgres: {condition: service_healthy}
      mcp-search: {condition: service_started}
      mcp-tools: {condition: service_started}
      mcp-stats: {condition: service_started}
    restart: unless-stopped
```

Verify (compose needs the stack's required vars even for `config`):

```bash
LENS_API_KEYS=k LENS_MCP_TOKEN=t LITELLM_BASE_URL=x API_CORS_ORIGINS=x \
  docker compose -f docker-compose.prod.yml config --services | grep lens
```
Expected: `lens`. Without `LENS_API_KEYS` / `LENS_MCP_TOKEN` the same command must fail with `required variable … is missing` — that is intended (a Lens without keys, or with MCP auth that the KB servers reject, must not start silently). `LENS_MCP_TOKEN` must be one of the main `API_KEYS` (the KB MCP servers verify Bearer tokens against it).

- [ ] **Step 6: Full suite + lint**

Run: `uv run pytest tests/test_lens -q && uv run ruff check src/lens tests/test_lens`
Expected: `119 passed, 4 skipped` (the 4 PG store cases run when `LENS_TEST_PG_DSN` is set), ruff `All checks passed!`.

- [ ] **Step 7: Commit (after user go-ahead)**

```bash
git add src/lens/app.py tests/test_lens/test_app.py docker-compose.prod.yml
git commit -m "feat(lens): HTTP + SSE API and compose service"
```

---

### Task 14: Normalizer benchmark (fixtures, scoring, runner)

**Files:**
- Create: `tests/eval/lens_normalizer/__init__.py`, `tests/eval/lens_normalizer/scoring.py`, `tests/eval/lens_normalizer/fixtures/kb_find_entity_seed.json`, `scripts/lens_capture_fixture.py`, `scripts/lens_normalizer_bench.py`
- Test: `tests/test_lens/test_bench_scoring.py`

**Interfaces:**
- Consumes: `Normalizer`, `NormalizeResult` (Task 10); `McpHub` (Task 7); `shape_hash` (Task 3)
- Produces:
  - Fixture JSON: `{"server", "namespace", "tool", "description", "args", "payload", "golden": {"objects": [{"key", "type"}]}}` (`golden.objects` may be `[]` meaning "should be raw")
  - `score(result: NormalizeResult, golden: dict) -> dict` with keys `valid: bool`, `recall: float`, `precision: float`, `type_acc: float`
  - `aggregate(scores: list[dict]) -> dict` with `n`, `valid_rate`, `mean_recall`, `mean_precision`, `mean_type_acc`

Metrics (from spec): valid-path rate = share of fixtures where the result is not `raw` (or is `raw` when golden is empty); object recall/precision on keys; type accuracy on matched keys. Aggregated objects count as matched when golden keys share the aggregate's `item_type` (we can't list 212 keys in golden).

- [ ] **Step 1: Write the failing test**

```python
from src.lens.model import AggregateEl, Column, ObjectEl, RawEl, Ref
from src.lens.normalizer import NormalizeResult
from src.lens.spec import Materialized
from tests.eval.lens_normalizer.scoring import aggregate, score


def res(objs=(), aggs=(), raw=False):
    if raw:
        return NormalizeResult(None, RawEl(key="raw:c", call_id="c", reason="x"), "raw")
    return NormalizeResult(Materialized(objects=list(objs), aggregates=list(aggs)), None, "llm")


def o(key, type_):
    return ObjectEl(key=key, type=type_, label=key)


def test_perfect_match():
    s = score(res([o("kb:1", "person"), o("kb:2", "event")]),
              {"objects": [{"key": "kb:1", "type": "person"}, {"key": "kb:2", "type": "event"}]})
    assert s == {"valid": True, "recall": 1.0, "precision": 1.0, "type_acc": 1.0}


def test_partial_and_wrong_type():
    s = score(res([o("kb:1", "organization"), o("kb:9", "person")]),
              {"objects": [{"key": "kb:1", "type": "person"}, {"key": "kb:2", "type": "event"}]})
    assert s["recall"] == 0.5 and s["precision"] == 0.5 and s["type_acc"] == 0.0


def test_raw_is_valid_only_when_golden_empty():
    assert score(res(raw=True), {"objects": []})["valid"] is True
    assert score(res(raw=True), {"objects": [{"key": "kb:1", "type": "person"}]})["valid"] \
        is False


def test_aggregate_counts_by_item_type():
    agg = AggregateEl(key="agg:c:h", label="ip · 30", item_type="ip", count=30,
                      rows_ref=Ref(call_id="c", path="$.h[*]"),
                      columns=[Column(name="id", path="$.ip")])
    s = score(res(aggs=[agg]), {"objects": [{"key": "fofa:1.1.1.1", "type": "ip"}]})
    assert s["recall"] == 1.0 and s["type_acc"] == 1.0


def test_aggregate_scores():
    a = aggregate([{"valid": True, "recall": 1.0, "precision": 0.5, "type_acc": 1.0},
                   {"valid": False, "recall": 0.0, "precision": 0.0, "type_acc": 0.0}])
    assert a == {"n": 2, "valid_rate": 0.5, "mean_recall": 0.5, "mean_precision": 0.25,
                 "mean_type_acc": 0.5}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lens/test_bench_scoring.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'tests.eval.lens_normalizer'`

- [ ] **Step 3: Implement scoring, seed fixture, scripts**

`tests/eval/lens_normalizer/__init__.py`: empty file. (If `tests/eval/__init__.py` does not exist, create it empty too.)

`tests/eval/lens_normalizer/scoring.py`:

```python
"""Scoring for the Lens normalizer benchmark (spec §5 item 8)."""

from __future__ import annotations

from src.lens.normalizer import NormalizeResult


def score(result: NormalizeResult, golden: dict) -> dict:
    gold = {g["key"]: g["type"] for g in golden.get("objects", [])}
    if result.raw is not None or result.materialized is None:
        ok = not gold
        return {"valid": ok, "recall": 1.0 if ok else 0.0, "precision": 1.0 if ok else 0.0,
                "type_acc": 1.0 if ok else 0.0}
    got = {o.key: o.type for o in result.materialized.objects}
    agg_types = {a.item_type for a in result.materialized.aggregates}
    matched = [k for k in gold if k in got or gold[k] in agg_types]
    recall = len(matched) / len(gold) if gold else 1.0
    precision = (len([k for k in got if k in gold]) / len(got)) if got else (
        1.0 if matched or not gold else 0.0)
    type_ok = [k for k in matched if got.get(k, gold[k] if gold[k] in agg_types else None)
               == gold[k]]
    type_acc = len(type_ok) / len(matched) if matched else (1.0 if not gold else 0.0)
    return {"valid": True, "recall": recall, "precision": precision, "type_acc": type_acc}


def aggregate(scores: list[dict]) -> dict:
    n = len(scores)
    if n == 0:
        return {"n": 0, "valid_rate": 0.0, "mean_recall": 0.0, "mean_precision": 0.0,
                "mean_type_acc": 0.0}
    return {
        "n": n,
        "valid_rate": sum(s["valid"] for s in scores) / n,
        "mean_recall": sum(s["recall"] for s in scores) / n,
        "mean_precision": sum(s["precision"] for s in scores) / n,
        "mean_type_acc": sum(s["type_acc"] for s in scores) / n,
    }
```

`tests/eval/lens_normalizer/fixtures/kb_find_entity_seed.json` (synthetic seed so the runner works before real captures exist):

```json
{
  "server": "kb-tools",
  "namespace": "kb",
  "tool": "find_entity_by_name",
  "description": "Find an entity in the knowledge graph by (partial) name.",
  "args": {"name": "Росатом"},
  "payload": {
    "entities": [
      {"id": "ent_01", "name": "Росатом", "type": "Organization", "mentions": 1284},
      {"id": "ent_02", "name": "Алексей Лихачёв", "type": "Person", "mentions": 311}
    ]
  },
  "golden": {"objects": [
    {"key": "kb:ent_01", "type": "organization"},
    {"key": "kb:ent_02", "type": "person"}
  ]}
}
```

`scripts/lens_capture_fixture.py`:

```python
"""Record one real MCP response as a Lens normalizer benchmark fixture.

Usage:
  LENS_MCP_SERVERS='[...]' uv run python scripts/lens_capture_fixture.py \
      --server kb-tools --tool find_entity_by_name --args '{"name": "Росатом"}' \
      --out tests/eval/lens_normalizer/fixtures/kb_find_rosatom.json

Then fill ``golden.objects`` by hand: [{"key": "<namespace>:<id>", "type": "<vocab type>"}].
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from src.lens.config import lens_settings
from src.lens.mcp_hub import McpHub


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--server", required=True)
    p.add_argument("--tool", required=True)
    p.add_argument("--args", default="{}")
    p.add_argument("--out", required=True)
    a = p.parse_args()

    hub = McpHub([s for s in lens_settings.mcp_servers if s.name == a.server])
    await hub.start()
    try:
        info = hub.find(f"{a.server}__{a.tool}")
        res = await hub.call(a.server, a.tool, json.loads(a.args))
    finally:
        await hub.close()
    if res.is_error:
        raise SystemExit(f"tool error: {res.error}")
    ns = next(c.ns for c in lens_settings.mcp_servers if c.name == a.server)
    fixture = {"server": a.server, "namespace": ns, "tool": a.tool,
               "description": info.description if info else "",
               "args": json.loads(a.args), "payload": res.payload,
               "golden": {"objects": []}}
    Path(a.out).write_text(json.dumps(fixture, ensure_ascii=False, indent=2))
    print(f"wrote {a.out} — now fill golden.objects")


if __name__ == "__main__":
    asyncio.run(main())
```

`scripts/lens_normalizer_bench.py`:

```python
"""Run the Lens normalizer benchmark against the real LLM (no cache).

Usage:
  uv run python scripts/lens_normalizer_bench.py [--model <litellm model>] [--glob '*.json']
Prints per-fixture scores and the aggregate (valid_rate, recall, precision, type_acc).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from src.lens.config import lens_settings
from src.lens.llm import OpenAICompatLLM
from src.lens.model import ToolCallRecord
from src.lens.normalizer import Normalizer
from src.lens.shape import shape_hash
from src.lens.store import MemoryLensStore
from tests.eval.lens_normalizer.scoring import aggregate, score

FIXTURES = Path("tests/eval/lens_normalizer/fixtures")


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=lens_settings.normalizer_model())
    p.add_argument("--glob", default="*.json")
    a = p.parse_args()

    llm = OpenAICompatLLM()
    scores = []
    for path in sorted(FIXTURES.glob(a.glob)):
        fx = json.loads(path.read_text())
        norm = Normalizer(llm, MemoryLensStore(), model=a.model,
                          vocabulary=lens_settings.vocabulary,
                          aggregate_threshold=lens_settings.aggregate_threshold,
                          sample_chars=lens_settings.sample_chars)
        call = ToolCallRecord(id=path.stem, input_id=None, server=fx["server"],
                              namespace=fx.get("namespace"), tool=fx["tool"], args=fx["args"], payload=fx["payload"],
                              shape_hash=shape_hash(fx["payload"]), latency_ms=0)
        result = await norm.normalize(call, fx.get("description", ""))
        s = score(result, fx["golden"])
        scores.append(s)
        print(f"{path.name:40s} source={result.source:6s} {s}")
    print("AGGREGATE", json.dumps(aggregate(scores), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lens/test_bench_scoring.py -q`
Expected: 5 passed

Optional live check (needs LiteLLM reachable):
`uv run python scripts/lens_normalizer_bench.py --glob 'kb_find_entity_seed.json'`
Expected: one line with `source=llm` and an AGGREGATE block.

- [ ] **Step 5: Commit (after user go-ahead)**

```bash
git add tests/eval/lens_normalizer scripts/lens_capture_fixture.py scripts/lens_normalizer_bench.py tests/test_lens/test_bench_scoring.py
git commit -m "feat(lens): normalizer benchmark scoring, seed fixture, capture + run scripts"
```

Follow-up (not code, user-owned): capture ~30 real responses across kb-search / kb-tools / kb-stats (and FOFA when available) with `lens_capture_fixture.py`, fill goldens, run the bench for each candidate model, pick `LENS_MODEL_NORMALIZER` / `LENS_MODEL_PLANNER` by the numbers.

---

## After Plan 1

- `graphify update .` after the code lands (project rule).
- Live smoke on the stack: `curl -XPOST localhost:8010/lens/v1/workspaces -H 'X-API-Key: <LENS key>' -H 'Content-Type: application/json' -d '{"title":"t"}'`; get a token via `POST …/stream_token`; `curl -N "localhost:8010/lens/v1/workspaces/<id>/stream?token=<t>"` must print `event: ready`; post input "Росатом" and watch `status` → `ops` → `input_done`. Check `/lens/v1/health` shows all three KB servers `up`.
- Plan 2 (frontend) consumes: the SSE client protocol in `src/lens/events.py` docstring (ready → GET state → apply ops by seq → `/ops?after_seq` on gaps → reconnect on `resync`), `state_to_dict` shape, event types from Task 12 (incl. `open_workspace`), `/stream_token`, `/pin`, `/tool_calls/{id}/value`, `/tool_calls/{id}/rows` (+`filter`), `[[key]]` markers in notes.
- Plan 3 (watcher) adds `lens_watch`, `lens_watch_hit`, router rules "следи за …" / "что нового", and the "+N" data.
