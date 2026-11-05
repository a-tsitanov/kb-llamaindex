from unittest.mock import AsyncMock

import pytest

from src.config import settings
from src.intake.repository import IntakeRepository
from src.mcp._shared import attach_document_links, document_links
from src.mcp.search_server import _outcome_result
from src.tenancy.context import default_graph_context, new_graph_context
from src.workflow.contracts import SearchOutcome, SerializedNode

D1 = "d0c5e6a0-0000-0000-0000-000000000001"
D2 = "d0c5e6a0-0000-0000-0000-000000000002"


@pytest.mark.asyncio
async def test_links_scoped_to_graph_and_old_documents(monkeypatch):
    graph = new_graph_context("alpha")
    monkeypatch.setattr(settings.api, "document_url", "https://proxy/{graph_id}/{doc_id}")
    seen = []

    async def paths(repo, ids):
        seen.append((repo._graph, ids))
        return {D1: ("old.md", "folder/original.docx"), D2: ("folder/old.md", None)}

    monkeypatch.setattr(IntakeRepository, "paths_by_ids", paths)
    items = [{"doc_id": D1}, {"doc_id": D1}, {"doc_id": D2}, {"doc_id": "legacy"}]
    documents = await attach_document_links(items, graph)
    assert seen == [(graph, [D1, D2])]
    assert len(documents) == 2
    assert items[0]["file_name"] == "original.docx"
    assert items[2]["file_name"] == "old.md"
    assert items[0]["download_url"] == f"https://proxy/alpha/{D1}"
    assert "download_url" not in items[3]


@pytest.mark.asyncio
async def test_nondefault_graph_requires_explicit_graph_url(monkeypatch):
    monkeypatch.setattr(settings.api, "document_url", "https://proxy/{doc_id}")
    query = AsyncMock()
    monkeypatch.setattr(IntakeRepository, "paths_by_ids", query)
    assert await document_links([D1], new_graph_context("alpha")) == {}
    query.assert_not_awaited()


@pytest.mark.asyncio
async def test_database_failure_keeps_link(monkeypatch):
    monkeypatch.setattr(settings.api, "document_url", "https://proxy/{doc_id}")
    monkeypatch.setattr(IntakeRepository, "paths_by_ids", AsyncMock(side_effect=RuntimeError("offline")))
    assert await document_links([D1], default_graph_context()) == {
        D1: {"download_url": f"https://proxy/{D1}"}
    }


@pytest.mark.asyncio
async def test_search_sources_and_documents(monkeypatch):
    monkeypatch.setattr(settings.api, "document_url", "https://proxy/{doc_id}")
    monkeypatch.setattr(IntakeRepository, "paths_by_ids", AsyncMock(return_value={D1: ("a.md", None)}))
    node = SerializedNode(chunk_id="1", text="test", score=0.5, metadata={"doc_id": D1})
    outcome = SearchOutcome(query="q", mode="local", answer="a", sources=[node], documents=[D1])
    result = await _outcome_result(outcome, default_graph_context())
    assert result["sources"][0]["file_name"] == "a.md"
    assert len(result["documents"]) == 1


@pytest.mark.asyncio
async def test_disabled_links_skip_database(monkeypatch):
    monkeypatch.setattr(settings.api, "document_url", "")
    query = AsyncMock()
    monkeypatch.setattr(IntakeRepository, "paths_by_ids", query)
    assert await document_links([D1], default_graph_context()) == {}
    query.assert_not_awaited()
