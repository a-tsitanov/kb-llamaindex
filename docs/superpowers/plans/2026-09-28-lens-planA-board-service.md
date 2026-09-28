# Lens v2 — Plan A: Board Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing Lens backend into the board service of Lens v2: one `BoardService` that owns every board rule, exposed to lens-agent as a board MCP (`/mcp/mcp`) and to the web over the existing HTTP/SSE API, with the old Router/Planner/Normalizer input path switched off by default.

**Architecture:** Board rules (keys, vocabularies, near-duplicate merge, limits, note canonicalization, undo) live in `src/lens/board.py` over the existing op log (`LensStore` + `fold`). `src/lens/board_mcp.py` is a FastMCP server of thin wrappers, guarded by a bearer token and reading `X-Workspace`/`X-Run` from request headers; it is mounted inside the Lens FastAPI app and its lifespan nested in the app's. Every write is an op tagged with the run id and published on the existing `EventBus`, so the web's board SSE works unchanged.

**Tech Stack:** Python 3.12, FastAPI, FastMCP 3.3 (`fastmcp.server.dependencies.get_http_headers`, `fastmcp.exceptions.ToolError`), pydantic v2, pytest (asyncio_mode=auto), ruff, uv.

**Spec:** `docs/superpowers/specs/2026-09-28-lens-v2-design.md` (r2) — §5 «Board service (lens) and board MCP». Roadmap: `docs/superpowers/plans/2026-09-28-lens-roadmap.md`, stage 2.

## Global Constraints

- Run everything with `uv run --frozen` (no dependency changes in this plan; fastmcp 3.3.1 is already locked).
- Test command: `uv run --frozen pytest tests/test_lens -q`; lint: `uv run --frozen ruff check src/lens tests/test_lens`. Both must be clean at the end of every task.
- Key = `namespace:normalized_id`; normalization: casefold, `ё→е`, collapsed whitespace, stripped quotes (`«»"'“”„\``).
- Type vocabulary: person, organization, event, location, document, topic, ip, domain, certificate, service, asn, other; unknown → `other`.
- Relation kinds: участник, связан, владеет, входит_в, работает_в, место, упоминает, related; free text → `related` with the original in `attrs.kind_original`.
- Limits: 50 objects per `add_objects` call, 200 per run (`LENS_BOARD_OBJECTS_PER_CALL`, `LENS_BOARD_OBJECTS_PER_RUN`).
- Sources are never written by the model; the board rejects an item without `source {server, tool, call_id, namespace}` (lens-agent injects it, plan B).
- Board MCP: bearer `LENS_BOARD_MCP_TOKEN` (empty = refuse everything), headers `X-Workspace` + `X-Run` required; endpoint `/mcp/mcp` in the Lens app.
- `LENS_LEGACY_INPUT=false` by default: `POST /workspaces/{id}/input` answers 410, McpHub/Planner/Normalizer are not started. Old code stays in the repo.
- Fold stays backward compatible: v1 ops (no `description`/`sources`) fold as before; existing «Демо»/«Росатом» data stays readable.
- Secrets only in the local `.env` (gitignored), never in the repo.
- Commits: local only, on the working branch; never push (push only on the user's explicit "push").

## Review Focus

- The model passes `call_id` but no `source` reaches the board (plan B not wired yet, or injection failed) → the item is rejected with a reason the agent can act on, nothing is written. Test: `test_rejects_without_source_or_id` (Task 3).
- The agent issues two board calls in parallel for the same workspace (pydantic-ai runs tool calls concurrently) → no duplicate object, exactly one added. Test: `test_parallel_calls_in_one_workspace_do_not_duplicate` (Task 3).
- A fresh deploy without `LENS_BOARD_MCP_TOKEN` → the board MCP refuses every call (401), the rest of the app works. Tests: `test_empty_token_refuses_everything` (Task 4), `test_board_mcp_mounted_writes_reach_state_and_stream` (Task 5).
- Existing workspaces written by v1 (ops without `description`/`sources`) → still fold and render. Test: `test_v1_ops_without_new_fields_still_fold` (Task 2).
- The old web/debug page still posts to `/input` after the switch → a clear 410 instead of a silent hang, pin still works. Test: `test_legacy_input_off_returns_410_and_health_without_hub` (Task 5).

## File Structure

| File | Responsibility |
|---|---|
| `src/lens/keys.py` (new) | key normalization, type/kind vocabularies, label matching (shared with the old router) |
| `src/lens/router.py` (modify) | old router uses `keys.match_labels` instead of its private copy |
| `src/lens/model.py` (modify) | `Source`; `ObjectEl.description/sources`; `RelationEl.attrs/sources` |
| `src/lens/state.py` (modify) | fold merges description/sources/types_seen, tracks `touched`, one note per key, returns aliases |
| `src/lens/board.py` (new) | `BoardService`: every board rule, independent of MCP/HTTP |
| `src/lens/board_mcp.py` (new) | FastMCP tools over `BoardService`, bearer guard, header context |
| `src/lens/config.py`, `src/lens/app.py` (modify) | settings, board in `LensDeps`, `/mcp` mount, legacy switch |
| `docker-compose.prod.yml` (modify) | `LENS_BOARD_MCP_TOKEN`, `LENS_LEGACY_INPUT` for the `lens` service |
| `tests/test_lens/fakes.py` (modify) | shared `lifespan_of` / `mcp_client` helpers for in-process MCP tests |

Diffs below are against local `main` at `696becf`. Apply them with `git apply` (save the block to a file) or by hand; the resulting files are what was verified.

---

### Task 1: Keys, vocabularies and label matching

**Files:**
- Create: `src/lens/keys.py`
- Modify: `src/lens/router.py` (drop private `_stem/_words/_WORD`, use `match_labels`)
- Test: `tests/test_lens/test_keys.py` (new); existing `tests/test_lens/test_router.py` must stay green

**Interfaces:**
- Produces: `TYPES: tuple[str, ...]`, `RELATION_KINDS: tuple[str, ...]`, `normalize_id(raw: str) -> str`, `make_key(namespace: str, raw_id: str) -> str`, `normalize_type(raw: str | None) -> str`, `normalize_kind(raw: str | None) -> tuple[str, str | None]`, `stem(word) -> str`, `words(text) -> list[str]`, `match_labels(target: str, labels: dict[str, str]) -> list[str]`.

- [ ] **Step 1: Write the failing test** — `tests/test_lens/test_keys.py`:

```python
from src.lens.keys import (
    make_key,
    match_labels,
    normalize_id,
    normalize_kind,
    normalize_type,
)


def test_normalize_id_case_yo_quotes_spaces():
    assert normalize_id("  Росатом  ") == "росатом"
    assert normalize_id("РОСАТОМ") == "росатом"
    assert normalize_id("Лихачёв") == normalize_id("Лихачев") == "лихачев"
    assert normalize_id("ГК «Росатом»") == "гк росатом"
    assert normalize_id("Росатом\n Квантовые   технологии") == "росатом квантовые технологии"


def test_make_key():
    assert make_key("kb", " Росатом ") == "kb:росатом"


def test_normalize_type():
    assert normalize_type("Organization") == "organization"
    assert normalize_type("spaceship") == "other"
    assert normalize_type(None) == "other"


def test_normalize_kind_vocab_aliases_and_free_text():
    assert normalize_kind("участник") == ("участник", None)
    assert normalize_kind("PARTICIPATED_IN") == ("участник", None)
    assert normalize_kind("works at") == ("работает_в", None)
    assert normalize_kind("REGULATION") == ("related", "REGULATION")
    assert normalize_kind("") == ("related", None)


def test_match_labels_exact_stem_no_substring():
    labels = {"kb:1": "Си Цзиньпин", "kb:2": "Россия", "kb:3": "Путин В."}
    assert match_labels("си цзиньпин", labels) == ["kb:1"]
    assert match_labels("Си", labels) == ["kb:1"]
    assert match_labels("Путина", labels) == ["kb:3"]
    assert match_labels("Байден", labels) == []
    assert match_labels("  ", labels) == []
```

- [ ] **Step 2: Run it, expect failure**

Run: `uv run --frozen pytest tests/test_lens/test_keys.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens.keys'`.

- [ ] **Step 3: Implement** — `src/lens/keys.py`:

```python
"""Board keys, vocabularies and label matching (shared by the board and the old router).

Keys are ``namespace:normalized_id``: the same entity written slightly differently
(«Росатом» / « РОСАТОМ » / "ГК «Росатом»" stays different — only case, ё/е, spaces and
quotes are normalized) lands on one object.
"""

from __future__ import annotations

import re

TYPES = (
    "person", "organization", "event", "location", "document", "topic",
    "ip", "domain", "certificate", "service", "asn", "other",
)

RELATION_KINDS = (
    "участник", "связан", "владеет", "входит_в", "работает_в", "место", "упоминает",
    "related",
)

# Free-text / source-specific kinds → the vocabulary. Keys are normalized (see _kind_key).
_KIND_ALIASES = {
    "participant": "участник", "participated_in": "участник", "participates": "участник",
    "участвовал": "участник", "участвует": "участник",
    "related_to": "связан", "связь": "связан", "linked": "связан",
    "owns": "владеет", "owner": "владеет", "владелец": "владеет",
    "part_of": "входит_в", "member_of": "входит_в", "affiliation": "входит_в",
    "subsidiary": "входит_в", "входит": "входит_в",
    "works_at": "работает_в", "employed_by": "работает_в", "работает": "работает_в",
    "located_in": "место", "location": "место", "place": "место",
    "mentions": "упоминает", "mentioned_in": "упоминает",
}

_QUOTES = re.compile(r"[«»\"'“”„`]")
_SPACES = re.compile(r"\s+")
_WORD = re.compile(r"\w+", re.U)


def normalize_id(raw: str) -> str:
    """casefold, ё→е, quotes dropped, whitespace collapsed and stripped."""
    s = _QUOTES.sub("", str(raw)).casefold().replace("ё", "е")
    return _SPACES.sub(" ", s).strip()


def make_key(namespace: str, raw_id: str) -> str:
    return f"{namespace}:{normalize_id(raw_id)}"


def normalize_type(raw: str | None) -> str:
    t = (raw or "").strip().lower()
    return t if t in TYPES else "other"


def _kind_key(raw: str) -> str:
    return _SPACES.sub("_", str(raw).strip().casefold().replace("ё", "е"))


def normalize_kind(raw: str | None) -> tuple[str, str | None]:
    """→ (vocabulary kind, original text when it was mapped to ``related``)."""
    k = _kind_key(raw or "")
    if k in RELATION_KINDS:
        return k, None
    if k in _KIND_ALIASES:
        return _KIND_ALIASES[k], None
    return "related", (str(raw).strip() or None)


def stem(word: str) -> str:
    w = word.lower().replace("ё", "е")
    if len(w) > 5:
        return w[:-2]
    if len(w) > 4:
        return w[:-1]
    return w


def words(text: str) -> list[str]:
    return [stem(w) for w in _WORD.findall(text)]


def match_labels(target: str, labels: dict[str, str]) -> list[str]:
    """Keys whose label matches ``target``: exact (case-insensitive) label wins; otherwise
    every target word must match a label word by stem or as a ≥4-char prefix. Never a raw
    substring ("Си" must not hit "Россия")."""
    t = target.strip().lower()
    if not t:
        return []
    exact = [k for k, label in labels.items() if label.lower() == t]
    if exact:
        return exact[:1]
    want = words(t)
    found = []
    for k, label in labels.items():
        have = words(label)
        if want and all(any(h == w or (len(w) >= 4 and h.startswith(w)) for h in have)
                        for w in want):
            found.append(k)
    return found
```

Then switch the router to it:

```diff
diff --git a/src/lens/router.py b/src/lens/router.py
index 7715a43..4dd7143 100644
--- a/src/lens/router.py
+++ b/src/lens/router.py
@@ -10,6 +10,7 @@ from __future__ import annotations
 import re
 from dataclasses import dataclass, field
 
+from src.lens.keys import match_labels
 from src.lens.model import Column, OpKind, Ref, TableEl
 from src.lens.state import CanvasState
 
@@ -23,7 +24,6 @@ _CANVAS_MODE = re.compile(r"^(покажи\s+)?(полем|на поле|кар
 _HIDE = re.compile(r"^(скрой|убери|спрячь)\b\s*(?P<t>.*?)" + _END, re.I)
 _SHOW = re.compile(r"^(покажи|верни)\b\s*(?P<t>.*?)" + _END, re.I)
 _OPEN = re.compile(r"^открой\s+(?P<t>.+?)" + _END, re.I)
-_WORD = re.compile(r"\w+", re.U)
 _VALS_SPLIT = re.compile(r"\s*(?:,|\bи\b|\s)\s*", re.I)
 
 
@@ -44,34 +44,8 @@ def is_stop(text: str) -> bool:
     return bool(_STOP.match(text.strip()))
 
 
-def _stem(w: str) -> str:
-    w = w.lower().replace("ё", "е")
-    if len(w) > 5:
-        return w[:-2]
-    if len(w) > 4:
-        return w[:-1]
-    return w
-
-
-def _words(s: str) -> list[str]:
-    return [_stem(w) for w in _WORD.findall(s)]
-
-
 def _match(target: str, state: CanvasState, keys: list[str]) -> list[str]:
-    t = target.strip().lower()
-    if not t:
-        return []
-    exact = [k for k in keys if state.objects[k].label.lower() == t]
-    if exact:
-        return exact[:1]
-    want = _words(t)
-    found = []
-    for k in keys:
-        have = _words(state.objects[k].label)
-        if want and all(any(h == w or (len(w) >= 4 and h.startswith(w)) for h in have)
-                        for w in want):
-            found.append(k)
-    return found
+    return match_labels(target, {k: state.objects[k].label for k in keys})
 
 
 def _ambiguous(state: CanvasState, keys: list[str]) -> Command:
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run --frozen pytest tests/test_lens/test_keys.py tests/test_lens/test_router.py -q && uv run --frozen ruff check src/lens tests/test_lens`
Expected: all passed (5 in test_keys + the existing router tests), ruff clean.

- [ ] **Step 5: Commit (local)**

```bash
git add src/lens/keys.py src/lens/router.py tests/test_lens/test_keys.py
git commit -m "feat(lens): board keys, vocabularies and shared label matching"
```

---

### Task 2: Model and fold for v2 (description, sources, touched, aliases)

**Files:**
- Modify: `src/lens/model.py`, `src/lens/state.py`
- Test: `tests/test_lens/test_state.py` (extend)

**Interfaces:**
- Consumes: nothing new.
- Produces: `Source(server, tool, call_id, run_id: str | None, namespace)`; `ObjectEl.description: str | None`, `ObjectEl.sources: list[Source]`; `RelationEl.attrs: dict[str, Any]`, `RelationEl.sources: list[Source]`; `CanvasState.touched: dict[str, int]` (key → seq of last write); `add_note` with an existing note key replaces it; `state_to_dict(...)["aliases"]`. Merge rule: attrs `setdefault`, description = latest non-empty, sources dedup by `(call_id, run_id)`, differing type → kept, new one appended to `attrs["types_seen"]`.

- [ ] **Step 1: Write the failing tests** — apply to `tests/test_lens/test_state.py`:

```diff
diff --git a/tests/test_lens/test_state.py b/tests/test_lens/test_state.py
index ba225e8..04fd00e 100644
--- a/tests/test_lens/test_state.py
+++ b/tests/test_lens/test_state.py
@@ -122,3 +122,62 @@ def test_repeated_relation_merges_refs():
     st = fold([op("add_relations", {"relations": [rel("c1")]}, "i1"),
                op("add_relations", {"relations": [rel("c2")]}, "i2")])
     assert [r.call_id for r in st.relations["kb:1|k|kb:2"].refs] == ["c1", "c2"]
+
+
+def src(call, run="r1"):
+    return {"server": "kb-tools", "tool": "t", "call_id": call, "run_id": run,
+            "namespace": "kb"}
+
+
+def test_v2_merge_description_sources_and_type_conflict():
+    st = fold([
+        op("add_objects", {"objects": [{"key": "kb:москва", "type": "location",
+                                        "label": "Москва", "description": "город",
+                                        "sources": [src("c1")]}]}, "r1"),
+        op("add_objects", {"objects": [{"key": "kb:москва", "type": "organization",
+                                        "label": "Москва", "description": "",
+                                        "sources": [src("c2", "r2")]}]}, "r2"),
+        op("add_objects", {"objects": [{"key": "kb:москва", "type": "location",
+                                        "label": "Москва", "description": "столица",
+                                        "sources": [src("c1")]}]}, "r3"),
+    ])
+    o = st.objects["kb:москва"]
+    assert o.type == "location"
+    assert o.attrs["types_seen"] == ["location", "organization"]
+    assert o.description == "столица"
+    assert [(s.call_id, s.run_id) for s in o.sources] == [("c1", "r1"), ("c2", "r2")]
+
+
+def test_v1_ops_without_new_fields_still_fold():
+    st = fold([op("add_objects", {"objects": [obj("kb:1")]})])
+    assert st.objects["kb:1"].description is None and st.objects["kb:1"].sources == []
+
+
+def test_note_with_same_key_is_replaced():
+    st = fold([
+        op("add_note", {"note": {"key": "note:r1", "text": "первый"}}, "r1"),
+        op("add_note", {"note": {"key": "note:r1", "text": "второй"}}, "r1"),
+        op("add_note", {"note": {"key": "note:r2", "text": "другой"}}, "r2"),
+    ])
+    assert [n.text for n in st.notes] == ["второй", "другой"]
+
+
+def test_touched_and_aliases_in_output():
+    ops = [
+        op("add_objects", {"objects": [obj("kb:a"), obj("kb:b")]}, "r1"),
+        op("add_objects", {"objects": [obj("kb:a")]}, "r2"),
+        op("merge", {"keep": "kb:a", "drop": "kb:b"}, "r3"),
+    ]
+    st = fold(ops)
+    assert st.touched == {"kb:a": ops[-1].seq}
+    assert state_to_dict(st)["aliases"] == {"kb:b": "kb:a"}
+
+
+def test_relation_sources_merge():
+    rel = {"from_key": "kb:1", "to_key": "kb:2", "kind": "связан"}
+    st = fold([
+        op("add_objects", {"objects": [obj("kb:1"), obj("kb:2")]}),
+        op("add_relations", {"relations": [dict(rel, sources=[src("c1")])]}, "r1"),
+        op("add_relations", {"relations": [dict(rel, sources=[src("c2", "r2")])]}, "r2"),
+    ])
+    assert [s.call_id for s in st.relations["kb:1|связан|kb:2"].sources] == ["c1", "c2"]
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run --frozen pytest tests/test_lens/test_state.py -q`
Expected: FAIL — `ImportError: cannot import name 'Source'` / missing fields.

- [ ] **Step 3: Implement** — `src/lens/model.py`:

```diff
diff --git a/src/lens/model.py b/src/lens/model.py
index 56fe20a..9e59f1e 100644
--- a/src/lens/model.py
+++ b/src/lens/model.py
@@ -13,6 +13,16 @@ class Ref(BaseModel):
     path: str
 
 
+class Source(BaseModel):
+    """Where a board item came from. Injected by lens-agent (never written by the model)."""
+
+    server: str
+    tool: str
+    call_id: str
+    run_id: str | None = None
+    namespace: str
+
+
 class Column(BaseModel):
     name: str
     path: str  # relative to one row, starts with "$"
@@ -22,8 +32,10 @@ class ObjectEl(BaseModel):
     key: str
     type: str
     label: str
+    description: str | None = None
     attrs: dict[str, Any] = Field(default_factory=dict)
-    refs: list[Ref] = Field(default_factory=list)
+    refs: list[Ref] = Field(default_factory=list)  # v1 (path refs); v2 uses ``sources``
+    sources: list[Source] = Field(default_factory=list)
 
 
 class RelationEl(BaseModel):
@@ -31,7 +43,9 @@ class RelationEl(BaseModel):
     to_key: str
     kind: str
     confidence: float = 1.0
+    attrs: dict[str, Any] = Field(default_factory=dict)
     refs: list[Ref] = Field(default_factory=list)
+    sources: list[Source] = Field(default_factory=list)
 
     @property
     def key(self) -> str:
```

`src/lens/state.py`:

```diff
diff --git a/src/lens/state.py b/src/lens/state.py
index 199d05b..cbe5df2 100644
--- a/src/lens/state.py
+++ b/src/lens/state.py
@@ -6,7 +6,7 @@ from collections.abc import Sequence
 from dataclasses import dataclass, field
 from typing import Any
 
-from src.lens.model import NoteEl, ObjectEl, Op, RelationEl
+from src.lens.model import NoteEl, ObjectEl, Op, RelationEl, Source
 
 
 @dataclass
@@ -21,6 +21,7 @@ class CanvasState:
     mode: str = "canvas"
     aliases: dict[str, str] = field(default_factory=dict)
     inputs: list[str] = field(default_factory=list)
+    touched: dict[str, int] = field(default_factory=dict)  # key → seq of last add/merge
     last_seq: int = 0
 
     def canon(self, key: str) -> str:
@@ -31,11 +32,23 @@ class CanvasState:
         return key
 
 
+def _merge_sources(into: list[Source], other: list[Source]) -> None:
+    known = {(s.call_id, s.run_id) for s in into}
+    into.extend(s for s in other if (s.call_id, s.run_id) not in known)
+
+
 def _merge_obj(into: ObjectEl, other: ObjectEl) -> None:
     for k, v in other.attrs.items():
         into.attrs.setdefault(k, v)
     known = {(r.call_id, r.path) for r in into.refs}
     into.refs.extend(r for r in other.refs if (r.call_id, r.path) not in known)
+    _merge_sources(into.sources, other.sources)
+    if other.description:
+        into.description = other.description  # latest non-empty wins; history in the op log
+    if other.type != into.type:
+        seen = into.attrs.setdefault("types_seen", [into.type])
+        if other.type not in seen:
+            seen.append(other.type)
 
 
 def _add_input(st: CanvasState, key: str, input_id: str | None) -> None:
@@ -54,6 +67,7 @@ def _put_relation(st: CanvasState, rel: RelationEl) -> None:
         known = {(r.call_id, r.path) for r in st.relations[rel.key].refs}
         st.relations[rel.key].refs.extend(
             r for r in rel.refs if (r.call_id, r.path) not in known)
+        _merge_sources(st.relations[rel.key].sources, rel.sources)
     else:
         st.relations[rel.key] = rel
 
@@ -69,13 +83,16 @@ def _apply(st: CanvasState, op: Op) -> None:
             else:
                 st.objects[o.key] = o
             _add_input(st, o.key, op.input_id)
+            st.touched[o.key] = op.seq
     elif op.kind == "add_relations":
         for d in p["relations"]:
             _put_relation(st, RelationEl.model_validate(d))
     elif op.kind == "add_view":
         st.views[p["view"]["key"]] = dict(p["view"])
     elif op.kind == "add_note":
-        st.notes.append(NoteEl.model_validate(p["note"]))
+        note = NoteEl.model_validate(p["note"])
+        st.notes = [n for n in st.notes if n.key != note.key]  # one note per key (per run)
+        st.notes.append(note)
     elif op.kind == "hide":
         st.hidden |= {st.canon(k) for k in p["keys"]}
     elif op.kind == "show":
@@ -87,7 +104,9 @@ def _apply(st: CanvasState, op: Op) -> None:
     elif op.kind == "set_mode":
         st.mode = p["mode"]
     elif op.kind == "merge":
-        _merge(st, st.canon(p["keep"]), st.canon(p["drop"]))
+        keep = st.canon(p["keep"])
+        _merge(st, keep, st.canon(p["drop"]))
+        st.touched[keep] = op.seq
 
 
 def _merge(st: CanvasState, keep: str, drop: str) -> None:
@@ -112,6 +131,7 @@ def _merge(st: CanvasState, keep: str, drop: str) -> None:
         st.hidden.add(keep)
     if drop in st.pins:
         st.pins.setdefault(keep, st.pins.pop(drop))
+    st.touched.pop(drop, None)
 
 
 def fold(ops: Sequence[Op]) -> CanvasState:
@@ -144,5 +164,6 @@ def state_to_dict(st: CanvasState) -> dict[str, Any]:
         "notes": [n.model_dump(mode="json") for n in st.notes],
         "mode": st.mode,
         "inputs": list(st.inputs),
+        "aliases": dict(st.aliases),
         "last_seq": st.last_seq,
     }
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run --frozen pytest tests/test_lens -q && uv run --frozen ruff check src/lens tests/test_lens`
Expected: whole lens suite green (v1 fold tests unchanged), ruff clean.

- [ ] **Step 5: Commit (local)**

```bash
git add src/lens/model.py src/lens/state.py tests/test_lens/test_state.py
git commit -m "feat(lens): v2 board model — sources, description, touched, note replace"
```

---

### Task 3: BoardService — every board rule

**Files:**
- Create: `src/lens/board.py`
- Test: `tests/test_lens/test_board.py` (new)

**Interfaces:**
- Consumes: Task 1 `make_key`, `match_labels`, `normalize_id`, `normalize_kind`, `normalize_type`; Task 2 `Source`, `ObjectEl`, `RelationEl`, `NoteEl`, `CanvasState.touched`; existing `LensStore.append_ops(ws, input_id, ops) -> list[Op]`, `LensStore.list_ops(ws)`, `fold`, `EventBus.publish(ws, event)`.
- Produces (used by Tasks 4–5 and plan C):
  - `class BoardError(ValueError)`; `@dataclass(frozen=True) BoardLimits(objects_per_call=50, objects_per_run=200)`
  - `BoardService(store, bus, limits=None)`; attribute `.store`
  - `await state(ws) -> CanvasState`
  - `await get_board(ws, run_id, limit=50, include_hidden=False) -> {"objects":[{key,type,label}], "relations":[{from,to,kind}], "hidden":[...], "total": int}`
  - `await find_on_board(ws, query) -> [{key,label}]`; `await get_object(ws, key) -> dict | None`
  - `await add_objects(ws, run_id, objects) -> {"added", "merged":[{id,merged_into}], "keys", "rejected":[{item,reason}]}` (raises `BoardError` over a limit)
  - `await add_relations(ws, run_id, relations) -> {"added", "rejected"}`
  - `await add_note(ws, run_id, text) -> {"key","cites"} | {"skipped": ...}`
  - `await hide/show(ws, run_id, keys) -> {"changed": int}`; `await merge(ws, run_id, keep, drop) -> {"key"}` (raises `BoardError` on a missing key)
  - `await undo(ws, run_id) -> {"reverted_run", "operations"[, "message"]}`
  - `await pin(ws, key, x, y) -> Op` (web write, run id `None`)
  - Every write publishes `{"type": "ops", "ops": [...]}` on the bus.

- [ ] **Step 1: Write the failing test** — `tests/test_lens/test_board.py`:

```python
import asyncio

import pytest

from src.lens.board import BoardError, BoardLimits, BoardService
from src.lens.events import EventBus
from src.lens.store import MemoryLensStore


def src(call="c1"):
    return {"server": "kb-tools", "tool": "find_entity_by_name", "call_id": call,
            "namespace": "kb"}


def obj(oid, label=None, type_="organization", **kw):
    return {"id": oid, "label": label or oid, "type": type_, "source": src(), **kw}


@pytest.fixture
async def board():
    store, bus = MemoryLensStore(), EventBus()
    b = BoardService(store, bus, BoardLimits(objects_per_call=3, objects_per_run=4))
    ws = await store.create_workspace("t")
    return b, ws.id, bus


async def test_add_objects_normalizes_keys_and_injects_run(board):
    b, ws, _ = board
    r = await b.add_objects(ws, "r1", [obj(" Росатом "), obj("РОСАТОМ")])
    assert r["keys"] == ["kb:росатом", "kb:росатом"] and r["added"] == 1
    o = await b.get_object(ws, "kb:росатом")
    assert o["sources"][0]["run_id"] == "r1" and o["type"] == "organization"


async def test_near_duplicate_by_label_reports_merged_into(board):
    b, ws, _ = board
    await b.add_objects(ws, "r1", [obj("ent_7", label="Росатом")])
    r = await b.add_objects(ws, "r2", [obj("Rosatom-id", label="  РОСАТОМ ")])
    assert r["added"] == 0 and r["merged"] == [{"id": "Rosatom-id", "merged_into": "kb:ent_7"}]


async def test_rejects_without_source_or_id(board):
    b, ws, _ = board
    r = await b.add_objects(ws, "r1", [{"id": "X", "label": "X"}, obj("", label="Y")])
    assert r["added"] == 0 and [x["reason"][:5] for x in r["rejected"]] == ["нет и", "нужны"]


async def test_unknown_type_becomes_other(board):
    b, ws, _ = board
    await b.add_objects(ws, "r1", [obj("X", type_="spaceship")])
    assert (await b.get_object(ws, "kb:x"))["type"] == "other"


async def test_limits_per_call_and_per_run(board):
    b, ws, _ = board
    with pytest.raises(BoardError, match="за вызов"):
        await b.add_objects(ws, "r1", [obj(f"o{i}") for i in range(4)])
    await b.add_objects(ws, "r1", [obj("a"), obj("b"), obj("c")])
    with pytest.raises(BoardError, match="за запуск"):
        await b.add_objects(ws, "r1", [obj("d"), obj("e")])
    assert (await b.add_objects(ws, "r2", [obj("d")]))["added"] == 1


async def test_relations_need_both_ends_and_map_kind(board):
    b, ws, _ = board
    await b.add_objects(ws, "r1", [obj("A"), obj("B")])
    r = await b.add_relations(ws, "r1", [
        {"from": "kb:a", "to": "kb:b", "kind": "REGULATION", "source": src()},
        {"from": "kb:a", "to": "kb:zzz", "kind": "связан", "source": src()},
        {"from": "kb:a", "to": "kb:a", "kind": "связан", "source": src()},
        {"from": "kb:a", "to": "kb:b", "kind": "связан"},
    ])
    assert r["added"] == 1 and len(r["rejected"]) == 3
    st = await b.state(ws)
    (rel,) = st.relations.values()
    assert rel.kind == "related" and rel.attrs == {"kind_original": "REGULATION"}


async def test_note_canonicalizes_citations(board):
    b, ws, _ = board
    await b.add_objects(ws, "r1", [obj("A", label="Росатом"), obj("B", label="Квантовый проект")])
    await b.merge(ws, "r1", "kb:a", "kb:b")
    r = await b.add_note(ws, "r2", "См. [[kb:b]], [[Росатом]] и [[kb:несуществующий]].")
    st = await b.state(ws)
    assert st.notes[-1].text == "См. [[kb:a]], [[kb:a]] и несуществующий."
    assert r["cites"] == ["kb:a"]
    await b.add_note(ws, "r2", "замена")
    assert [n.text for n in (await b.state(ws)).notes] == ["замена"]


async def test_undo_reverts_previous_run_not_current(board):
    b, ws, _ = board
    await b.add_objects(ws, "r1", [obj("A")])
    await b.add_objects(ws, "r2", [obj("B")])
    r = await b.undo(ws, "r3")
    assert r["reverted_run"] == "r2" and r["operations"] == 1
    assert set((await b.state(ws)).objects) == {"kb:a"}
    assert (await b.add_note(ws, "r3", "x")) == {"skipped": "в этом запуске была отмена — заметка не нужна"}
    assert (await b.undo(ws, "r4"))["reverted_run"] == "r1"
    assert (await b.undo(ws, "r5"))["message"] == "нечего отменять"


async def test_get_board_orders_by_touch_and_keeps_pinned_and_run(board):
    b, ws, _ = board
    await b.add_objects(ws, "r1", [obj("old"), obj("pinned")])
    await b.pin(ws, "kb:pinned", 1, 2)
    await b.add_objects(ws, "r2", [obj("new")])
    await b.add_objects(ws, "r3", [obj("mine")])
    await b.add_relations(ws, "r3", [{"from": "kb:mine", "to": "kb:old", "kind": "связан",
                                      "source": src()}])
    g = await b.get_board(ws, "r3", limit=2)
    keys = [o["key"] for o in g["objects"]]
    assert set(keys) == {"kb:pinned", "kb:mine"} and g["total"] == 4
    assert g["relations"] == []
    g = await b.get_board(ws, "r3", limit=4)
    assert g["relations"] == [{"from": "kb:mine", "to": "kb:old", "kind": "связан"}]


async def test_hide_show_find_and_merge_errors(board):
    b, ws, _ = board
    await b.add_objects(ws, "r1", [obj("A", label="Си Цзиньпин"), obj("B", label="Россия")])
    assert await b.find_on_board(ws, "Си") == [{"key": "kb:a", "label": "Си Цзиньпин"}]
    assert (await b.hide(ws, "r2", ["kb:a", "kb:nope"])) == {"changed": 1}
    assert await b.find_on_board(ws, "Си") == []
    assert (await b.show(ws, "r3", ["kb:a"])) == {"changed": 1}
    with pytest.raises(BoardError):
        await b.merge(ws, "r4", "kb:a", "kb:nope")


async def test_writes_publish_board_events(board):
    b, ws, bus = board
    q = bus.subscribe(ws)
    await b.add_objects(ws, "r1", [obj("A")])
    op = await b.pin(ws, "kb:a", 5, 6)
    events = [q.get_nowait() for _ in range(q.qsize())]
    assert [e["ops"][0]["kind"] for e in events] == ["add_objects", "pin"]
    assert op.input_id is None


async def test_parallel_calls_in_one_workspace_do_not_duplicate(board):
    b, ws, _ = board
    r1, r2 = await asyncio.gather(
        b.add_objects(ws, "r1", [obj("id-1", label="Росатом")]),
        b.add_objects(ws, "r1", [obj("id-2", label="РОСАТОМ")]))
    assert r1["added"] + r2["added"] == 1
    assert len((await b.state(ws)).objects) == 1
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run --frozen pytest tests/test_lens/test_board.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens.board'`.

- [ ] **Step 3: Implement** — `src/lens/board.py`:

```python
"""Board service core: every rule the board enforces, independent of MCP/HTTP.

The agent (through the board MCP) and the web (through HTTP) both land here. Each change
is an op in the workspace log tagged with the run that made it (``Op.input_id`` holds the
run id), published on the board event bus so the web redraws.
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from src.lens.events import EventBus
from src.lens.keys import make_key, match_labels, normalize_id, normalize_kind, normalize_type
from src.lens.model import NoteEl, ObjectEl, Op, OpKind, RelationEl, Source
from src.lens.state import CanvasState, fold
from src.lens.store import LensStore

_CITE = re.compile(r"\[\[([^\[\]]+)\]\]")
_SOURCE_FIELDS = ("server", "tool", "call_id", "namespace")


class BoardError(ValueError):
    """A request the board refuses as a whole (the message goes back to the agent)."""


@dataclass(frozen=True)
class BoardLimits:
    objects_per_call: int = 50
    objects_per_run: int = 200


def _source(raw: Any, run_id: str | None) -> Source | None:
    if not isinstance(raw, dict) or any(not raw.get(f) for f in _SOURCE_FIELDS):
        return None
    return Source(**{**raw, "run_id": raw.get("run_id") or run_id})


class BoardService:
    def __init__(self, store: LensStore, bus: EventBus, limits: BoardLimits | None = None):
        self.store, self.bus = store, bus
        self.limits = limits or BoardLimits()
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # ── plumbing ────────────────────────────────────────────────────────
    async def _ops(self, ws: str) -> list[Op]:
        return await self.store.list_ops(ws)

    async def _append(
        self, ws: str, run_id: str | None, ops: list[tuple[OpKind, dict]],
    ) -> list[Op]:
        if not ops:
            return []
        written = await self.store.append_ops(ws, run_id, ops)
        self.bus.publish(ws, {"type": "ops",
                              "ops": [o.model_dump(mode="json") for o in written]})
        return written

    # ── reads ───────────────────────────────────────────────────────────
    async def state(self, ws: str) -> CanvasState:
        return fold(await self._ops(ws))

    async def get_board(
        self, ws: str, run_id: str | None, limit: int = 50, include_hidden: bool = False,
    ) -> dict[str, Any]:
        st = await self.state(ws)
        visible = {k: o for k, o in st.objects.items() if include_hidden or k not in st.hidden}
        always = {k for k in visible
                  if k in st.pins or (run_id and run_id in st.object_inputs.get(k, []))}
        ranked = sorted(visible, key=lambda k: st.touched.get(k, 0), reverse=True)
        chosen = list(always) + [k for k in ranked if k not in always]
        chosen = chosen[:max(limit, len(always))]
        picked = set(chosen)
        return {
            "objects": [{"key": k, "type": visible[k].type, "label": visible[k].label}
                        for k in chosen],
            "relations": [{"from": r.from_key, "to": r.to_key, "kind": r.kind}
                          for r in st.relations.values()
                          if r.from_key in picked and r.to_key in picked],
            "hidden": sorted(st.hidden),
            "total": len(visible),
        }

    async def find_on_board(self, ws: str, query: str) -> list[dict[str, str]]:
        st = await self.state(ws)
        labels = {k: o.label for k, o in st.objects.items() if k not in st.hidden}
        return [{"key": k, "label": labels[k]} for k in match_labels(query, labels)]

    async def get_object(self, ws: str, key: str) -> dict[str, Any] | None:
        st = await self.state(ws)
        o = st.objects.get(st.canon(key))
        return None if o is None else o.model_dump(
            mode="json", include={"key", "type", "label", "description", "attrs", "sources"})

    # ── writes (agent) ──────────────────────────────────────────────────
    async def add_objects(self, ws: str, run_id: str, objects: list[dict]) -> dict[str, Any]:
        if len(objects) > self.limits.objects_per_call:
            raise BoardError(
                f"слишком много объектов за вызов ({len(objects)} > "
                f"{self.limits.objects_per_call}) — выбери самые относящиеся к вопросу")
        async with self._locks[ws]:
            ops = await self._ops(ws)
            st = fold(ops)
            already = sum(len(o.payload.get("objects", [])) for o in ops
                          if o.kind == "add_objects" and o.input_id == run_id)
            if already + len(objects) > self.limits.objects_per_run:
                raise BoardError(
                    f"лимит объектов за запуск ({self.limits.objects_per_run}) — "
                    "заверши ответ с тем, что уже на доске")
            by_label = {(o.type, normalize_id(o.label)): k for k, o in st.objects.items()}
            built: list[ObjectEl] = []
            keys, merged, rejected = [], [], []
            added = 0
            for item in objects:
                oid, label = str(item.get("id") or "").strip(), str(item.get("label") or "").strip()
                src = _source(item.get("source"), run_id)
                if not oid or not label:
                    rejected.append({"item": item, "reason": "нужны id и label"})
                    continue
                if src is None:
                    rejected.append({"item": item, "reason": "нет источника — укажи call_id "
                                     "вызова инструмента, из которого взят объект"})
                    continue
                otype = normalize_type(item.get("type"))
                key = st.canon(make_key(src.namespace, oid))
                if key not in st.objects and (otype, normalize_id(label)) in by_label:
                    key = by_label[(otype, normalize_id(label))]
                if key in st.objects:
                    merged.append({"id": oid, "merged_into": key})
                elif key not in keys:
                    added += 1
                built.append(ObjectEl(
                    key=key, type=otype, label=label,
                    description=(str(item["description"]).strip() or None)
                    if item.get("description") else None,
                    attrs=item.get("attrs") if isinstance(item.get("attrs"), dict) else {},
                    sources=[src]))
                by_label.setdefault((otype, normalize_id(label)), key)
                keys.append(key)
            await self._append(ws, run_id, [(
                "add_objects", {"objects": [o.model_dump(mode="json") for o in built]})]
                if built else [])
            return {"added": added, "merged": merged, "keys": keys, "rejected": rejected}

    async def add_relations(self, ws: str, run_id: str, relations: list[dict]) -> dict[str, Any]:
        async with self._locks[ws]:
            st = await self.state(ws)
            built: list[RelationEl] = []
            rejected = []
            for item in relations:
                src = _source(item.get("source"), run_id)
                a = st.canon(str(item.get("from") or "").strip())
                b = st.canon(str(item.get("to") or "").strip())
                missing = [k for k in (a, b) if k not in st.objects]
                if src is None:
                    rejected.append({"item": item, "reason": "нет источника (call_id)"})
                elif missing:
                    rejected.append({"item": item, "reason":
                                     f"нет объекта {missing[0]!r} на доске — сначала add_objects"})
                elif a == b:
                    rejected.append({"item": item, "reason": "связь объекта с самим собой"})
                else:
                    kind, original = normalize_kind(item.get("kind"))
                    built.append(RelationEl(
                        from_key=a, to_key=b, kind=kind, sources=[src],
                        attrs={"kind_original": original} if original else {}))
            await self._append(ws, run_id, [(
                "add_relations", {"relations": [r.model_dump(mode="json") for r in built]})]
                if built else [])
            return {"added": len(built), "rejected": rejected}

    async def add_note(self, ws: str, run_id: str, text: str) -> dict[str, Any]:
        async with self._locks[ws]:
            ops = await self._ops(ws)
            if any(o.kind == "undo" and o.input_id == run_id for o in ops):
                return {"skipped": "в этом запуске была отмена — заметка не нужна"}
            st = fold(ops)
            labels = {k: o.label for k, o in st.objects.items()}
            cites: list[str] = []

            def resolve(m: re.Match) -> str:
                raw = m.group(1).strip()
                key = st.canon(raw)
                if key not in st.objects:
                    query = raw.split(":", 1)[1] if ":" in raw else raw
                    found = match_labels(query, labels)
                    if len(found) != 1:
                        return query  # unresolved → plain text, never a broken link
                    key = found[0]
                if key not in cites:
                    cites.append(key)
                return f"[[{key}]]"

            body = _CITE.sub(resolve, text).strip()
            note = NoteEl(key=f"note:{run_id}", text=body, cites=cites)
            await self._append(ws, run_id, [("add_note", {"note": note.model_dump(mode="json")})])
            return {"key": note.key, "cites": cites}

    async def _set_hidden(self, ws: str, run_id: str | None, keys: list[str], hide: bool) -> int:
        async with self._locks[ws]:
            st = await self.state(ws)
            canon = [k for k in dict.fromkeys(st.canon(k) for k in keys) if k in st.objects]
            if not canon:
                return 0
            await self._append(ws, run_id, [("hide" if hide else "show", {"keys": canon})])
            return len(canon)

    async def hide(self, ws: str, run_id: str | None, keys: list[str]) -> dict[str, int]:
        return {"changed": await self._set_hidden(ws, run_id, keys, True)}

    async def show(self, ws: str, run_id: str | None, keys: list[str]) -> dict[str, int]:
        return {"changed": await self._set_hidden(ws, run_id, keys, False)}

    async def merge(self, ws: str, run_id: str, keep: str, drop: str) -> dict[str, str]:
        async with self._locks[ws]:
            st = await self.state(ws)
            k, d = st.canon(keep), st.canon(drop)
            for key in (k, d):
                if key not in st.objects:
                    raise BoardError(f"нет объекта {key!r} на доске")
            if k == d:
                return {"key": k}
            await self._append(ws, run_id, [("merge", {"keep": k, "drop": d})])
            return {"key": k}

    async def undo(self, ws: str, run_id: str) -> dict[str, Any]:
        """Revert the last run that changed the board, never the current one."""
        async with self._locks[ws]:
            ops = await self._ops(ws)
            st = fold(ops)
            previous = [i for i in st.inputs if i != run_id]
            if not previous:
                return {"reverted_run": None, "operations": 0, "message": "нечего отменять"}
            target = previous[-1]
            n = sum(1 for o in ops if o.input_id == target)
            await self._append(ws, run_id, [("undo", {"input_id": target})])
            return {"reverted_run": target, "operations": n}

    # ── writes (web) ────────────────────────────────────────────────────
    async def pin(self, ws: str, key: str, x: float, y: float) -> Op:
        (op,) = await self._append(ws, None, [("pin", {"key": key, "x": x, "y": y})])
        return op
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run --frozen pytest tests/test_lens -q && uv run --frozen ruff check src/lens tests/test_lens`
Expected: 12 passed in test_board, whole suite green, ruff clean.

- [ ] **Step 5: Commit (local)**

```bash
git add src/lens/board.py tests/test_lens/test_board.py
git commit -m "feat(lens): BoardService — limits, near-dup merge, notes, undo"
```

---

### Task 4: Board MCP

**Files:**
- Create: `src/lens/board_mcp.py`
- Modify: `tests/test_lens/fakes.py` (shared in-process MCP helpers)
- Test: `tests/test_lens/test_board_mcp.py` (new)

**Interfaces:**
- Consumes: Task 3 `BoardService`, `BoardError`.
- Produces: `BearerGuard(app, token)` (ASGI; `.lifespan` = the wrapped app's); `build_board_mcp(board_of: Callable[[], BoardService]) -> FastMCP` with tools `get_board, find_on_board, get_object, add_objects, add_relations, add_note, hide, show, merge, undo`; `board_mcp_app(board_of, token) -> BearerGuard` — mount at `/mcp`, endpoint `/mcp/mcp`. `board_of` is resolved on every call (the host app builds deps in its lifespan). `BoardError` and header/workspace problems become `ToolError` (the model sees the message). Test helpers `lifespan_of(app)` and `mcp_client(app, url, headers)` in `tests/test_lens/fakes.py`.

- [ ] **Step 1: Write the failing test** — add the helpers to `tests/test_lens/fakes.py`:

```diff
diff --git a/tests/test_lens/fakes.py b/tests/test_lens/fakes.py
index eb678d5..7e35cda 100644
--- a/tests/test_lens/fakes.py
+++ b/tests/test_lens/fakes.py
@@ -2,9 +2,46 @@
 
 from __future__ import annotations
 
+import asyncio
+from contextlib import asynccontextmanager
+
+import httpx
+from fastmcp import Client
+from fastmcp.client.transports import StreamableHttpTransport
+
 from src.lens.llm import ChatReply
 
 
+@asynccontextmanager
+async def lifespan_of(app):
+    """httpx.ASGITransport does not run the ASGI lifespan; the mounted MCP app needs it."""
+    started, stopped, inbox = asyncio.Event(), asyncio.Event(), asyncio.Queue()
+
+    async def send(msg):
+        {"lifespan.startup.complete": started, "lifespan.shutdown.complete": stopped}.get(
+            msg["type"], asyncio.Event()).set()
+
+    task = asyncio.create_task(app({"type": "lifespan"}, inbox.get, send))
+    await inbox.put({"type": "lifespan.startup"})
+    await started.wait()
+    try:
+        yield
+    finally:
+        await inbox.put({"type": "lifespan.shutdown"})
+        await stopped.wait()
+        await task
+
+
+def mcp_client(app, url: str, headers: dict) -> Client:
+    """fastmcp Client talking to an in-process ASGI app (no sockets)."""
+    def factory(headers=None, timeout=None, auth=None, **_):
+        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
+                                 base_url="http://test", headers=headers,
+                                 timeout=timeout, auth=auth)
+    return Client(StreamableHttpTransport(url=url, headers=headers,
+                                          httpx_client_factory=factory))
+
+
 class FakeLLM:
     def __init__(self, chat_replies=None, json_replies=None):
         self.chat_replies = list(chat_replies or [])
```

and create `tests/test_lens/test_board_mcp.py`:

```python
import httpx
import pytest
from fastapi import FastAPI
from fastmcp.exceptions import ToolError

from src.lens.board import BoardLimits, BoardService
from src.lens.board_mcp import board_mcp_app
from src.lens.events import EventBus
from src.lens.store import MemoryLensStore
from tests.test_lens.fakes import lifespan_of, mcp_client

TOKEN = "board-secret"
SRC = {"server": "kb-tools", "tool": "find_entity_by_name", "call_id": "c1", "namespace": "kb"}


@pytest.fixture
async def env():
    store, bus = MemoryLensStore(), EventBus()
    board = BoardService(store, bus, BoardLimits(objects_per_call=2))
    ws = await store.create_workspace("t")
    mcp = board_mcp_app(lambda: board, TOKEN)
    app = FastAPI(lifespan=mcp.lifespan)
    app.mount("/mcp", mcp)
    async with lifespan_of(app):
        yield app, ws.id, board


def client(app, headers):
    return mcp_client(app, "http://test/mcp/mcp", headers)


def hdr(ws, run="r1", token=TOKEN):
    return {"Authorization": f"Bearer {token}", "X-Workspace": ws, "X-Run": run}


async def test_tools_round_trip_under_run_headers(env):
    app, ws, board = env
    async with client(app, hdr(ws)) as c:
        names = {t.name for t in await c.list_tools()}
        assert {"get_board", "add_objects", "add_relations", "add_note", "undo"} <= names
        r = await c.call_tool("add_objects", {"objects": [
            {"id": "A", "type": "organization", "label": "Росатом", "source": SRC},
            {"id": "B", "type": "person", "label": "Лихачёв", "source": SRC}]})
        assert r.data["keys"] == ["kb:a", "kb:b"]
        await c.call_tool("add_relations", {"relations": [
            {"from": "kb:b", "to": "kb:a", "kind": "работает_в", "source": SRC}]})
        g = (await c.call_tool("get_board", {})).data
        assert g["total"] == 2 and len(g["relations"]) == 1
    st = await board.state(ws)
    assert st.object_inputs["kb:a"] == ["r1"]


async def test_board_errors_become_tool_errors(env):
    app, ws, _ = env
    async with client(app, hdr(ws)) as c:
        with pytest.raises(ToolError, match="за вызов"):
            await c.call_tool("add_objects", {"objects": [
                {"id": str(i), "label": str(i), "source": SRC} for i in range(3)]})
        with pytest.raises(ToolError, match="нет объекта"):
            await c.call_tool("get_object", {"key": "kb:nope"})


async def test_unknown_workspace_or_missing_run_header(env):
    app, ws, _ = env
    async with client(app, hdr("nope")) as c:
        with pytest.raises(ToolError, match="нет расследования"):
            await c.call_tool("get_board", {})
    async with client(app, {"Authorization": f"Bearer {TOKEN}", "X-Workspace": ws}) as c:
        with pytest.raises(ToolError, match="X-Run"):
            await c.call_tool("get_board", {})


async def test_bearer_token_required(env):
    app, _, _ = env
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as h:
        for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}):
            r = await h.post("/mcp/mcp", json={}, headers=headers)
            assert r.status_code == 401


async def test_empty_token_refuses_everything():
    store, bus = MemoryLensStore(), EventBus()
    board = BoardService(store, bus)
    mcp = board_mcp_app(lambda: board, "")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mcp),
                                 base_url="http://test") as h:
        r = await h.post("/mcp", json={}, headers={"Authorization": "Bearer "})
        assert r.status_code == 401
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run --frozen pytest tests/test_lens/test_board_mcp.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.lens.board_mcp'`.

- [ ] **Step 3: Implement** — `src/lens/board_mcp.py`:

```python
"""Board MCP: the agent's view of the board (thin wrappers over ``BoardService``).

Mounted in the Lens app at ``/mcp``. lens-agent calls it with ``Authorization: Bearer
<LENS_BOARD_MCP_TOKEN>`` plus ``X-Workspace`` / ``X-Run`` set per run, so the model can
never pick the workspace or pose as another run. Sources inside ``add_objects`` /
``add_relations`` items are injected by lens-agent (the model only passes ``call_id``).
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers

from src.lens.board import BoardError, BoardService


class BearerGuard:
    """ASGI wrapper: HTTP requests need the bearer token; lifespan passes through."""

    def __init__(self, app: Any, token: str):
        self.app, self._token = app, token.encode()
        self.lifespan = getattr(app, "lifespan", None)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not self._ok(scope):
            body = json.dumps({"detail": "invalid or missing bearer token"}).encode()
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)

    def _ok(self, scope) -> bool:
        auth = dict(scope.get("headers") or []).get(b"authorization", b"")
        scheme, _, value = auth.partition(b" ")
        return (bool(self._token) and scheme.lower() == b"bearer"
                and hmac.compare_digest(value.strip(), self._token))


def build_board_mcp(board_of: Callable[[], BoardService]) -> FastMCP:
    """``board_of`` is resolved per call: the host app builds its BoardService in its
    lifespan, after the MCP app is mounted."""
    mcp = FastMCP(name="lens-board")

    async def ctx() -> tuple[BoardService, str, str]:
        board = board_of()
        h = get_http_headers()
        ws, run = h.get("x-workspace", "").strip(), h.get("x-run", "").strip()
        if not ws or not run:
            raise ToolError("нет заголовков X-Workspace / X-Run")
        if await board.store.get_workspace(ws) is None:
            raise ToolError(f"нет расследования {ws!r}")
        return board, ws, run

    async def call(fn, *args):  # BoardError → message the agent can act on
        try:
            return await fn(*args)
        except BoardError as e:
            raise ToolError(str(e)) from e

    @mcp.tool
    async def get_board(limit: int = 50, include_hidden: bool = False) -> dict:
        """Объекты на доске (свежие первыми; закреплённые и объекты этого запуска всегда
        включены), связи между ними и скрытые ключи. Смотри сюда перед добавлением."""
        board, ws, run = await ctx()
        return await board.get_board(ws, run, max(1, min(limit, 200)), include_hidden)

    @mcp.tool
    async def find_on_board(query: str) -> list[dict]:
        """Найти объекты доски по названию (нормализованное совпадение слов)."""
        board, ws, _ = await ctx()
        return await board.find_on_board(ws, query)

    @mcp.tool
    async def get_object(key: str) -> dict:
        """Карточка объекта: тип, название, описание, атрибуты, источники."""
        board, ws, _ = await ctx()
        o = await board.get_object(ws, key)
        if o is None:
            raise ToolError(f"нет объекта {key!r} на доске")
        return o

    @mcp.tool
    async def add_objects(objects: list[dict[str, Any]]) -> dict:
        """Добавить объекты: [{id, type, label, description?, attrs?, call_id}].
        call_id — вызов инструмента-источника, из результата которого взят объект.
        Не больше 50 за вызов. Возвращает ключи (key) для связей и заметки."""
        board, ws, run = await ctx()
        return await call(board.add_objects, ws, run, objects)

    @mcp.tool
    async def add_relations(relations: list[dict[str, Any]]) -> dict:
        """Связи между объектами доски: [{from, to, kind, call_id}], from/to — ключи.
        kind: участник, связан, владеет, входит_в, работает_в, место, упоминает."""
        board, ws, run = await ctx()
        return await call(board.add_relations, ws, run, relations)

    @mcp.tool
    async def add_note(text: str) -> dict:
        """Короткий ответ на доске; объекты упоминай как [[key]]. Одна заметка на запуск."""
        board, ws, run = await ctx()
        return await call(board.add_note, ws, run, text)

    @mcp.tool
    async def hide(keys: list[str]) -> dict:
        """Скрыть объекты (ничего не удаляется)."""
        board, ws, run = await ctx()
        return await board.hide(ws, run, keys)

    @mcp.tool
    async def show(keys: list[str]) -> dict:
        """Вернуть скрытые объекты."""
        board, ws, run = await ctx()
        return await board.show(ws, run, keys)

    @mcp.tool
    async def merge(keep: str, drop: str) -> dict:
        """Слить дубликат drop в keep."""
        board, ws, run = await ctx()
        return await call(board.merge, ws, run, keep, drop)

    @mcp.tool
    async def undo() -> dict:
        """Отменить изменения предыдущего запроса (не текущего)."""
        board, ws, run = await ctx()
        return await call(board.undo, ws, run)

    return mcp


def board_mcp_app(board_of: Callable[[], BoardService], token: str) -> BearerGuard:
    """ASGI app to mount at ``/mcp`` (endpoint ``/mcp/mcp``); its ``lifespan`` must run
    inside the host app's lifespan."""
    return BearerGuard(build_board_mcp(board_of).http_app(path="/mcp"), token)
```

Note: `httpx.ASGITransport` does not run the ASGI lifespan, and the FastMCP session manager refuses requests without it — that is why tests wrap the app in `lifespan_of`. Do not use `timeout` in shell commands on macOS (not installed).

- [ ] **Step 4: Run, expect pass**

Run: `uv run --frozen pytest tests/test_lens -q && uv run --frozen ruff check src/lens tests/test_lens`
Expected: 5 passed in test_board_mcp, whole suite green, ruff clean.

- [ ] **Step 5: Commit (local)**

```bash
git add src/lens/board_mcp.py tests/test_lens/fakes.py tests/test_lens/test_board_mcp.py
git commit -m "feat(lens): board MCP with bearer guard and run headers"
```

---

### Task 5: Wire the board into the Lens app; legacy input off

**Files:**
- Modify: `src/lens/config.py`, `src/lens/app.py`, `docker-compose.prod.yml`
- Test: `tests/test_lens/test_app.py` (update fakes, add 2 tests)

**Interfaces:**
- Consumes: Task 3 `BoardService`, `BoardLimits`; Task 4 `board_mcp_app`, test helpers.
- Produces: settings `legacy_input: bool = False`, `board_mcp_token: SecretStr`, `board_objects_per_call: int = 50`, `board_objects_per_run: int = 200`; `LensDeps(store, bus, agent=None, hub=None, board=None)` — builds a `BoardService` itself when `board` is None; `POST .../input` → 410 when `agent is None`; `POST .../pin` → `BoardService.pin`; `/health` → `{"mcp": {}}` without a hub; `/mcp/mcp` mounted, its lifespan nested in the app lifespan; `_build_deps()` starts McpHub/Planner/Normalizer only when `LENS_LEGACY_INPUT=true` (`_build_legacy_deps`).

- [ ] **Step 1: Write the failing tests** — apply to `tests/test_lens/test_app.py` (drops `FakeAgent.pin`, pin now goes through the board):

```diff
diff --git a/tests/test_lens/test_app.py b/tests/test_lens/test_app.py
index 62a4711..87b8c5b 100644
--- a/tests/test_lens/test_app.py
+++ b/tests/test_lens/test_app.py
@@ -2,6 +2,7 @@ import json
 
 import httpx
 import pytest
+from pydantic import SecretStr
 
 from src.lens.app import LensDeps, create_app
 from src.lens.auth import check_stream_token, make_stream_token
@@ -9,6 +10,7 @@ from src.lens.config import lens_settings
 from src.lens.events import EventBus
 from src.lens.model import ToolCallRecord
 from src.lens.store import MemoryLensStore
+from tests.test_lens.fakes import lifespan_of, mcp_client
 
 KEY = "test-lens-key"
 
@@ -22,9 +24,6 @@ class FakeAgent:
         self.submitted.append((ws, text, mentions))
         return "i1"
 
-    async def pin(self, ws, key, x, y):
-        return await self.store.append_ops(ws, None, [("pin", {"key": key, "x": x, "y": y})])
-
 
 class FakeHub:
     def status(self):
@@ -164,3 +163,41 @@ def test_key_is_valid_checks_all_keys():
     assert not key_is_valid("c", ["a", "b"])
     assert not key_is_valid("", [])
     assert key_is_valid("ключ", ["ключ"])
+
+
+async def test_legacy_input_off_returns_410_and_health_without_hub(monkeypatch):
+    monkeypatch.setattr(lens_settings, "api_keys", KEY)
+    app = create_app(LensDeps(store=MemoryLensStore(), bus=EventBus()))
+    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t",
+                                 headers={"X-API-Key": KEY}) as c:
+        ws = (await c.post("/lens/v1/workspaces", json={"title": "t"})).json()
+        r = await c.post(f"/lens/v1/workspaces/{ws['id']}/input", json={"text": "x"})
+        assert r.status_code == 410
+        assert (await c.get("/lens/v1/health")).json() == {"mcp": {}}
+        r = await c.post(f"/lens/v1/workspaces/{ws['id']}/pin",
+                         json={"key": "kb:1", "x": 1, "y": 2})
+        assert r.json() == {"seq": 1}
+
+
+async def test_board_mcp_mounted_writes_reach_state_and_stream(monkeypatch):
+    monkeypatch.setattr(lens_settings, "api_keys", KEY)
+    monkeypatch.setattr(lens_settings, "board_mcp_token", SecretStr("mcp-token"))
+    deps = LensDeps(store=MemoryLensStore(), bus=EventBus())
+    app = create_app(deps)
+    async with lifespan_of(app):
+        ws = await deps.store.create_workspace("t")
+        q = deps.bus.subscribe(ws.id)
+        headers = {"Authorization": "Bearer mcp-token", "X-Workspace": ws.id, "X-Run": "r1"}
+        async with mcp_client(app, "http://test/mcp/mcp", headers) as c:
+            await c.call_tool("add_objects", {"objects": [{
+                "id": "A", "type": "organization", "label": "Росатом",
+                "source": {"server": "kb-tools", "tool": "t", "call_id": "c1",
+                           "namespace": "kb"}}]})
+        assert q.get_nowait()["type"] == "ops"
+        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
+                                     base_url="http://t") as h:
+            body = (await h.get(f"/lens/v1/workspaces/{ws.id}",
+                                headers={"X-API-Key": KEY})).json()
+            assert [o["key"] for o in body["state"]["objects"]] == ["kb:a"]
+            r = await h.post("/mcp/mcp", json={}, headers={"Authorization": "Bearer nope"})
+            assert r.status_code == 401
```

- [ ] **Step 2: Run, expect failure**

Run: `uv run --frozen pytest tests/test_lens/test_app.py -q`
Expected: FAIL — `LensDeps.__init__() missing ... 'agent'` and `/mcp/mcp` 404.

- [ ] **Step 3: Implement** — `src/lens/config.py`:

```diff
diff --git a/src/lens/config.py b/src/lens/config.py
index d68e8a3..996a002 100644
--- a/src/lens/config.py
+++ b/src/lens/config.py
@@ -56,6 +56,12 @@ class LensSettings(BaseSettings):
     api_keys: str = "dev-lens-key"
     stream_secret: SecretStr = SecretStr("")
     cors_origins: str = "http://localhost:5173"
+    # v2: lens-agent drives the board through the board MCP (/mcp); the old
+    # Router/Planner/Normalizer input path stays in the repo behind this flag.
+    legacy_input: bool = False
+    board_mcp_token: SecretStr = SecretStr("")
+    board_objects_per_call: int = 50
+    board_objects_per_run: int = 200
 
     def planner_model(self) -> str:
         return self.model_planner or settings.litellm.model_large
```

`src/lens/app.py`:

```diff
diff --git a/src/lens/app.py b/src/lens/app.py
index eb33f1b..b0f43aa 100644
--- a/src/lens/app.py
+++ b/src/lens/app.py
@@ -13,6 +13,8 @@ from fastapi.responses import StreamingResponse
 from pydantic import BaseModel, Field, field_validator
 
 from src.lens.auth import make_stream_token, require_key, require_stream_token
+from src.lens.board import BoardLimits, BoardService
+from src.lens.board_mcp import board_mcp_app
 from src.lens.config import lens_settings
 from src.lens.events import EventBus, sse_stream
 from src.lens.model import Column
@@ -24,8 +26,15 @@ from src.lens.state import fold, state_to_dict
 class LensDeps:
     store: Any
     bus: EventBus
-    agent: Any
-    hub: Any
+    agent: Any = None  # legacy input path only (LENS_LEGACY_INPUT=true)
+    hub: Any = None
+    board: BoardService | None = None
+
+    def __post_init__(self) -> None:
+        if self.board is None:
+            self.board = BoardService(self.store, self.bus, BoardLimits(
+                objects_per_call=lens_settings.board_objects_per_call,
+                objects_per_run=lens_settings.board_objects_per_run))
 
 
 class NewWorkspace(BaseModel):
@@ -106,12 +115,12 @@ def _routes() -> tuple[APIRouter, APIRouter, APIRouter]:
         # Public: bucketed to "up"/"down" only — the raw status can carry connection
         # exception text (hostnames, ports, stack-adjacent detail) that's not for
         # anonymous callers.
-        return {"mcp": {name: "up" if s == "up" else "down"
-                       for name, s in deps.hub.status().items()}}
+        status_ = deps.hub.status() if deps.hub else {}
+        return {"mcp": {name: "up" if s == "up" else "down" for name, s in status_.items()}}
 
     @api.get("/health/details")
     async def health_details(deps: LensDeps = Depends(_deps)):
-        return {"mcp": deps.hub.status()}
+        return {"mcp": deps.hub.status() if deps.hub else {}}
 
     @api.post("/workspaces")
     async def create_workspace(body: NewWorkspace, deps: LensDeps = Depends(_deps)):
@@ -138,13 +147,16 @@ def _routes() -> tuple[APIRouter, APIRouter, APIRouter]:
     @api.post("/workspaces/{workspace_id}/input", status_code=status.HTTP_202_ACCEPTED)
     async def post_input(workspace_id: str, body: InputBody, deps: LensDeps = Depends(_deps)):
         await _workspace_or_404(deps, workspace_id)
+        if deps.agent is None:
+            raise HTTPException(status.HTTP_410_GONE,
+                                "legacy input is disabled; send requests to lens-agent")
         input_id = await deps.agent.submit(workspace_id, body.text, body.mentions)
         return {"input_id": input_id}
 
     @api.post("/workspaces/{workspace_id}/pin")
     async def pin(workspace_id: str, body: PinBody, deps: LensDeps = Depends(_deps)):
         await _workspace_or_404(deps, workspace_id)
-        (op,) = await deps.agent.pin(workspace_id, body.key, body.x, body.y)
+        op = await deps.board.pin(workspace_id, body.key, body.x, body.y)
         return {"seq": op.seq}
 
     @api.post("/workspaces/{workspace_id}/stream_token")
@@ -198,20 +210,28 @@ def _routes() -> tuple[APIRouter, APIRouter, APIRouter]:
 
 
 async def _build_deps() -> LensDeps:
+    from src.lens.store import PgLensStore
+    from src.storage.pg_pool import get_pg_pool
+
+    store = PgLensStore(await get_pg_pool())
+    await store.ensure_schema()
+    bus = EventBus()
+    if not lens_settings.legacy_input:
+        return LensDeps(store=store, bus=bus)
+    return await _build_legacy_deps(store, bus)
+
+
+async def _build_legacy_deps(store: Any, bus: EventBus) -> LensDeps:
     from src.lens.agent import Agent
     from src.lens.llm import OpenAICompatLLM
     from src.lens.mcp_hub import McpHub
     from src.lens.normalizer import Normalizer
     from src.lens.planner import Planner
-    from src.lens.store import PgLensStore
-    from src.storage.pg_pool import get_pg_pool
 
-    store = PgLensStore(await get_pg_pool())
-    await store.ensure_schema()
     hub = McpHub(lens_settings.mcp_servers, timeout_s=lens_settings.tool_timeout_s,
                  backoff_s=lens_settings.reconnect_backoff_s)
     await hub.start()
-    llm, bus = OpenAICompatLLM(), EventBus()
+    llm = OpenAICompatLLM()
     planner = Planner(llm, hub, store, model=lens_settings.planner_model(),
                       max_steps=lens_settings.max_tool_steps,
                       sample_chars=lens_settings.sample_chars)
@@ -225,21 +245,28 @@ async def _build_deps() -> LensDeps:
 
 
 def create_app(deps: LensDeps | None = None) -> FastAPI:
+    # Board MCP for lens-agent; resolves the board per call (deps are built in lifespan).
+    board_mcp = board_mcp_app(lambda: app.state.deps.board,
+                              lens_settings.board_mcp_token.get_secret_value())
+
     @asynccontextmanager
     async def lifespan(app: FastAPI):
-        if deps is not None:
-            app.state.deps = deps
-            yield
-            return
-        from src.storage.pg_pool import close_pg_pool
-
-        app.state.deps = await _build_deps()
-        try:
-            yield
-        finally:
-            await app.state.deps.agent.drain()
-            await app.state.deps.hub.close()
-            await close_pg_pool()
+        async with board_mcp.lifespan(app):
+            if deps is not None:
+                app.state.deps = deps
+                yield
+                return
+            from src.storage.pg_pool import close_pg_pool
+
+            app.state.deps = await _build_deps()
+            try:
+                yield
+            finally:
+                if app.state.deps.agent is not None:
+                    await app.state.deps.agent.drain()
+                if app.state.deps.hub is not None:
+                    await app.state.deps.hub.close()
+                await close_pg_pool()
 
     app = FastAPI(title="Lens", lifespan=lifespan)
     if deps is not None:
@@ -249,6 +276,7 @@ def create_app(deps: LensDeps | None = None) -> FastAPI:
                                                                     "Content-Type"])
     for router in _routes():
         app.include_router(router)
+    app.mount("/mcp", board_mcp)  # endpoint: /mcp/mcp
     return app
 
 
```

`docker-compose.prod.yml` (lens service):

```diff
diff --git a/docker-compose.prod.yml b/docker-compose.prod.yml
index c184645..3249edf 100644
--- a/docker-compose.prod.yml
+++ b/docker-compose.prod.yml
@@ -238,6 +238,10 @@ services:
       LENS_API_KEYS: ${LENS_API_KEYS:?set LENS_API_KEYS}
       LENS_STREAM_SECRET: ${LENS_STREAM_SECRET:-}
       LENS_CORS_ORIGINS: ${LENS_CORS_ORIGINS:-http://localhost:5173}
+      # v2: lens-agent writes the board through /mcp/mcp with this bearer token (empty =
+      # board MCP refuses every call). The old /input path is off unless LENS_LEGACY_INPUT.
+      LENS_BOARD_MCP_TOKEN: ${LENS_BOARD_MCP_TOKEN:-}
+      LENS_LEGACY_INPUT: ${LENS_LEGACY_INPUT:-false}
       # Role models (empty = LITELLM_MODEL_LARGE) and a Lens-only LLM timeout: a CPU-only
       # local model needs minutes per planner/normalizer step, other services keep theirs.
       LENS_MODEL_PLANNER: ${LENS_MODEL_PLANNER:-}
```

- [ ] **Step 4: Run, expect pass**

Run: `uv run --frozen pytest tests/test_lens -q && uv run --frozen ruff check src/lens tests/test_lens`
Expected: 177 passed, 5 skipped (the counts verified on `696becf` + this plan), ruff clean.

- [ ] **Step 5: Update the code graph and commit (local)**

```bash
graphify update .
git add src/lens/config.py src/lens/app.py docker-compose.prod.yml tests/test_lens/test_app.py graphify-out
git commit -m "feat(lens): board service wiring — /mcp mount, legacy input off by default"
```

---

## After this plan

- Live check (needs the user's «да» first — live-test rule): rebuild `lens`, set `LENS_BOARD_MCP_TOKEN` in the local `.env`, call `/mcp/mcp` `get_board` for the «Росатом» workspace, confirm the debug page still renders it.
- Plan B (lens-agent) consumes: the tool names/args above, `X-Workspace`/`X-Run` + bearer, `source` injection into `add_objects`/`add_relations` items, `ToolError` messages as model-visible retries.
- Plan C (web + compose) consumes: 410 on `/input`, `state_to_dict()["aliases"]`, the unchanged board SSE.
