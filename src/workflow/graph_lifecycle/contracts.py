"""Temporal payloads for graph provisioning / deletion (ids only — the
physical names are always re-read from the registry row)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class GraphLifecycleIn(_Frozen):
    graph_id: str


class DeleteGraphIn(_Frozen):
    graph_id: str
    # > GraphRegistry TTL (30 s): every process sees `deleting` before teardown.
    registry_settle_s: int = 35
    # Let terminated workflows' in-flight activities finish before dropping.
    drain_grace_s: int = 60


class SetStatusIn(_Frozen):
    graph_id: str
    status: str
    error: str = ""
    # Only transition from this status (None = unconditional).
    expect: str | None = None


class LifecycleResult(_Frozen):
    graph_id: str
    status: str
    error: str = ""
