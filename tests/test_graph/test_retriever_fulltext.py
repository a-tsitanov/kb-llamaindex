"""Tests for the entity-name lookup helper (``afind_entities_by_name``).

Row mapping / query shape under nebula live in
tests/test_retrieval/test_nebula_read_slice.py; this file keeps the
backend-agnostic blank-input + fail-open contract.
"""

from __future__ import annotations

import pytest


class _StubStore:
    def __init__(self, rows=None, raise_=False):
        self._rows = rows or []
        self._raise = raise_
        self.last = None

    def structured_query(self, query, param_map=None):
        self.last = (query, param_map)
        if self._raise:
            raise RuntimeError("entity name lookup failed")
        return self._rows


def _retriever(store):
    from src.graph.retriever import GraphRetriever
    r = GraphRetriever.__new__(GraphRetriever)  # bypass LlamaIndex wiring
    r._graph_store = store
    r._similarity_top_k = 10
    return r


@pytest.mark.asyncio
async def test_afind_entities_by_name_blank_and_failopen():
    store = _StubStore(rows=[{"name": "X"}])
    assert (await _retriever(store).afind_entities_by_name("   ")).entities == []
    assert store.last is None
    boom = _StubStore(raise_=True)
    assert (await _retriever(boom).afind_entities_by_name("Иванов")).entities == []
    assert (await _retriever(None).afind_entities_by_name("Иванов")).entities == []
