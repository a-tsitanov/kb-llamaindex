# tests/test_analytics/conftest.py
from __future__ import annotations

from dataclasses import dataclass, field


class _FakeStore:
    """Captures the last Cypher + params and returns canned rows."""

    def __init__(self, rows=None, *, by_call=None):
        self._rows = rows or []
        self._by_call = list(by_call) if by_call else None  # rows per sequential call
        self.calls: list[tuple[str, dict]] = []
        self.last_cypher = None
        self.last_params = None

    def structured_query(self, cypher, param_map=None):
        self.last_cypher = cypher
        self.last_params = param_map or {}
        self.calls.append((cypher, self.last_params))
        if self._by_call is not None:
            i = len(self.calls) - 1
            return self._by_call[i] if i < len(self._by_call) else []
        return self._rows


class _NebulaStmtStore:
    """nGQL fake keyed on the EXACT statements the nebula seam issues.

    ``responses`` maps a full statement string to its canned rows; a statement
    not in the map answers ``[]`` (a legitimately empty read) and is still
    recorded in ``calls`` so tests can assert what was (not) issued.  Nebula
    binds no parameters, so a non-empty ``param_map`` is a test failure."""

    def __init__(self, responses: dict[str, list[dict]] | None = None):
        self._responses = dict(responses or {})
        self.calls: list[str] = []

    def structured_query(self, query, param_map=None):
        assert not param_map, f"nebula binds no params, got {param_map!r}"
        self.calls.append(query)
        return list(self._responses.get(query, []))


def _ngql_list(values) -> str:
    """Inline-quoted nGQL value list (vids or labels), in the given order
    (mirrors the seam's ``", ".join(_q(v) for v in values)``)."""
    from src.graph.nebula_store import _q

    return ", ".join(_q(v) for v in values)


@dataclass
class _StubLLM:
    """Minimal async chat LLM returning a canned reply (or raising)."""

    reply: str = ""
    raises: bool = False
    calls: list = field(default_factory=list)

    async def achat(self, messages):
        self.calls.append(messages)
        if self.raises:
            raise RuntimeError("llm down")

        class _Msg:
            content = self.reply

        class _Resp:
            message = _Msg()

        return _Resp()
