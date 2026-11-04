"""Download links of the ORIGINAL uploaded file next to every doc_id the MCP
tools return (settings.api.document_url / API_DOCUMENT_URL)."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock

import pytest

from src.config import settings
from src.mcp import _shared
from src.mcp import search_server as ss
from src.mcp import tools_server as ts
from src.retrieval.atomic_tools import ToolResult
from src.storage.postgres import AsyncPostgres
from src.workflow.contracts import SearchOutcome, SerializedNode

TEMPLATE = "http://10.10.113.12:8090/api/documents/{doc_id}?variant=original"
D1 = "d0c5e6a0-0000-0000-0000-000000000001"
D2 = "d0c5e6a0-0000-0000-0000-000000000002"


def url(doc_id: str) -> str:
    return TEMPLATE.format(doc_id=doc_id)


@pytest.fixture
def links_on(monkeypatch):
    monkeypatch.setattr(settings.api, "document_url", TEMPLATE)


@pytest.fixture
def pg(monkeypatch):
    """Stub the ONE batched documents lookup; records every call."""
    rows = {
        D1: (f"s3://kb-uploads/{D1}/3.md", f"s3://kb-uploads/{D1}/Протокол допроса.docx"),
        D2: (f"s3://kb-uploads/{D2}/post 17.md", None),
    }
    m = AsyncMock(side_effect=lambda ids: {i: rows[i] for i in ids if i in rows})
    monkeypatch.setattr(AsyncPostgres, "paths_by_ids", m)
    return m


# ── helper ──────────────────────────────────────────────────────────


async def test_empty_template_emits_no_links(monkeypatch, pg):
    monkeypatch.setattr(settings.api, "document_url", "")
    assert await _shared.document_links([D1]) == {}
    assert _shared.document_download_url(D1) is None
    pg.assert_not_called()


async def test_links_and_file_names_in_one_query(links_on, pg):
    out = await _shared.document_links([D1, D2, D1])
    assert out == {
        D1: {"download_url": url(D1), "file_name": "Протокол допроса.docx"},
        D2: {"download_url": url(D2), "file_name": "post 17.md"},
    }
    pg.assert_awaited_once()
    assert sorted(pg.await_args.args[0]) == [D1, D2]


async def test_non_uuid_ids_are_skipped(links_on, pg):
    out = await _shared.document_links(["/data/legacy/file.md", "", None, D1])
    assert list(out) == [D1]
    assert pg.await_args.args[0] == [D1]


async def test_only_non_uuid_ids_skip_the_query(links_on, pg):
    assert await _shared.document_links(["/data/legacy/file.md"]) == {}
    pg.assert_not_called()


async def test_db_failure_still_builds_links_without_file_name(links_on, monkeypatch):
    monkeypatch.setattr(
        AsyncPostgres, "paths_by_ids", AsyncMock(side_effect=RuntimeError("pg down")),
    )
    assert await _shared.document_links([D1]) == {D1: {"download_url": url(D1)}}


async def test_unknown_document_gets_link_without_file_name(links_on, pg):
    other = "d0c5e6a0-0000-0000-0000-0000000000ff"
    assert await _shared.document_links([other]) == {other: {"download_url": url(other)}}


def test_template_only_url(links_on):
    assert _shared.document_download_url(D1) == url(D1)
    assert _shared.document_download_url("not-a-uuid") is None


# ── search tools (MCP-1) ────────────────────────────────────────────


def _outcome() -> SearchOutcome:
    def node(cid, doc):
        return SerializedNode(chunk_id=cid, text="t", score=0.5, metadata={"doc_id": doc})
    return SearchOutcome(
        query="q", mode="local", answer="a",
        sources=[node("c1", D2), node("c2", D1), node("c3", D2),
                 SerializedNode(chunk_id="c4", text="t", metadata={"file_path": "/x.md"})],
        documents=[D1, D2],
    )


async def test_search_result_sources_and_documents_carry_links(links_on, pg):
    out = await ss._outcome_result(_outcome())
    s1, s2, _, s4 = out["sources"]
    assert s1["download_url"] == url(D2) and s1["file_name"] == "post 17.md"
    assert s2["download_url"] == url(D1) and s2["file_name"] == "Протокол допроса.docx"
    assert "download_url" not in s4  # file_path fallback is not a document id
    assert out["documents"] == [
        {"doc_id": D2, "download_url": url(D2), "file_name": "post 17.md"},
        {"doc_id": D1, "download_url": url(D1), "file_name": "Протокол допроса.docx"},
    ]
    pg.assert_awaited_once()


async def test_search_documents_include_outcome_only_documents(links_on, pg):
    outcome = SearchOutcome(query="q", mode="global", answer="a", documents=[D1])
    out = await ss._outcome_result(outcome)
    assert out["sources"] == []
    assert [d["doc_id"] for d in out["documents"]] == [D1]


async def test_search_result_unchanged_when_links_off(monkeypatch, pg):
    monkeypatch.setattr(settings.api, "document_url", "")
    out = await ss._outcome_result(_outcome())
    assert out == ss._outcome_to_dict(_outcome())
    assert "documents" not in out


async def test_search_server_instructions_mention_download_url():
    assert "download_url" in ss.mcp.instructions
    tools = {t.name: t for t in await ss.mcp._list_tools()}
    assert "download_url" in tools["kb_search"].description


# ── atomic tools (MCP-2) ────────────────────────────────────────────


async def test_vector_search_hits_and_documents_carry_links(links_on, pg):
    out = await ts._with_documents({"sources": [
        {"chunk_id": "c1", "doc_id": D1, "text": "t"},
        {"chunk_id": "c2", "doc_id": D1, "text": "t"},
        {"chunk_id": "c3", "doc_id": "", "text": "t"},
    ]})
    assert [s.get("download_url") for s in out["sources"]] == [url(D1), url(D1), None]
    assert out["documents"] == [
        {"doc_id": D1, "download_url": url(D1), "file_name": "Протокол допроса.docx"},
    ]


async def test_read_full_document_has_top_level_link(links_on, pg, monkeypatch):
    monkeypatch.setattr(ts, "_c", AsyncMock(return_value=object()))
    monkeypatch.setattr(ts.atomic_tools, "read_full_document",
                        AsyncMock(return_value=ToolResult(sources=[], observation="full text")))
    out = await ts.read_full_document(D1)
    assert out == {"text": "full text", "download_url": url(D1),
                   "file_name": "Протокол допроса.docx"}


async def test_read_full_document_error_has_no_link(links_on, pg, monkeypatch):
    monkeypatch.setattr(ts, "_c", AsyncMock(return_value=object()))
    monkeypatch.setattr(ts.atomic_tools, "read_full_document", AsyncMock(
        return_value=ToolResult(sources=[], observation=f"Error: document {D1} not found")))
    assert await ts.read_full_document(D1) == {"error": f"Error: document {D1} not found"}


async def test_get_chunks_by_doc_id_has_top_level_link(links_on, pg, monkeypatch):
    monkeypatch.setattr(ts, "_c", AsyncMock(return_value=object()))
    monkeypatch.setattr(ts.atomic_tools, "get_chunks_by_doc_id", AsyncMock(return_value=ToolResult(
        sources=[], observation=json.dumps([{"chunk_id": "c1", "doc_id": D2, "text": "t"}]))))
    out = await ts.get_chunks_by_doc_id(D2)
    assert out["chunks"][0]["chunk_id"] == "c1"
    assert out["download_url"] == url(D2) and out["file_name"] == "post 17.md"


async def test_get_chunks_error_has_no_link(links_on, pg, monkeypatch):
    monkeypatch.setattr(ts, "_c", AsyncMock(return_value=object()))
    monkeypatch.setattr(ts.atomic_tools, "get_chunks_by_doc_id", AsyncMock(return_value=ToolResult(
        sources=[], observation='{"error": "boom", "chunks": []}')))
    assert await ts.get_chunks_by_doc_id(D1) == {"chunks": {"error": "boom", "chunks": []}}


async def test_tools_server_instructions_mention_download_url():
    assert "download_url" in ts.mcp.instructions


# ── entity-watch feed ───────────────────────────────────────────────


def _feed_row(doc):
    return {"id": 1, "entity_vid": "v", "entity_name": "Блинов", "kind": "new_mention",
            "doc_id": doc, "doc_date": date(2024, 3, 12), "detail": {}, "why": "",
            "detected_at": datetime(2026, 10, 15, 9, 45, tzinfo=UTC),
            "seen_at": None, "acked_at": None,
            "doc_path": f"s3://kb-uploads/{doc}/3.md" if doc else None}


def test_feed_card_carries_original_download_url(links_on):
    card = ts.build_feed_cards([_feed_row(D1)])[0]
    assert card["download_url"] == url(D1)
    assert card["link"] == settings.monitor.document_link.format(doc_id=D1)


def test_feed_card_without_document_or_links_has_no_download_url(monkeypatch):
    monkeypatch.setattr(settings.api, "document_url", "")
    assert ts.build_feed_cards([_feed_row(D1)])[0]["download_url"] is None
    monkeypatch.setattr(settings.api, "document_url", TEMPLATE)
    assert ts.build_feed_cards([_feed_row(None)])[0]["download_url"] is None
