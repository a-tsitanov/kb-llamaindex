"""Lens domain models: canvas elements, ops, workspaces, tool calls."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Ref(BaseModel):
    call_id: str
    path: str


class Source(BaseModel):
    """Where a board item came from. Injected by lens-agent (never written by the model)."""

    server: str
    tool: str
    call_id: str
    run_id: str | None = None
    namespace: str


class Column(BaseModel):
    name: str
    path: str  # relative to one row, starts with "$"


class ObjectEl(BaseModel):
    key: str
    type: str
    label: str
    description: str | None = None
    attrs: dict[str, Any] = Field(default_factory=dict)
    refs: list[Ref] = Field(default_factory=list)  # v1 (path refs); v2 uses ``sources``
    sources: list[Source] = Field(default_factory=list)


class RelationEl(BaseModel):
    from_key: str
    to_key: str
    kind: str
    confidence: float = 1.0
    attrs: dict[str, Any] = Field(default_factory=dict)
    refs: list[Ref] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)

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
