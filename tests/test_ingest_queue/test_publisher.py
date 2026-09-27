"""publish_ingest stamps the RabbitMQ message priority. No live broker: the
process-global connection + topology declare are monkeypatched, and we inspect
the aio_pika.Message handed to the default exchange."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.ingest_queue import publisher
from src.ingest_queue.priorities import PRIO_LIVE
from src.workflow.contracts import IngestParams


def _params() -> IngestParams:
    return IngestParams(doc_id="doc-1", path="s3://bucket/doc-1/file.pdf")


def _fake_channel(captured: dict) -> MagicMock:
    async def _publish(message, routing_key):
        captured["msg"] = message
        captured["routing_key"] = routing_key

    channel = MagicMock()
    channel.default_exchange = MagicMock()
    channel.default_exchange.publish = _publish
    channel.close = AsyncMock()
    return channel


@pytest.mark.asyncio
async def test_publish_sets_backfill_priority(monkeypatch) -> None:
    captured: dict = {}
    channel = _fake_channel(captured)
    conn = MagicMock()
    conn.channel = AsyncMock(return_value=channel)
    monkeypatch.setattr(publisher, "_get_connection", AsyncMock(return_value=conn))
    monkeypatch.setattr(publisher, "declare_ingest_topology", AsyncMock())

    await publisher.publish_ingest(_params(), queue="ingest.pending", priority=0)

    assert captured["msg"].priority == 0
    assert captured["routing_key"] == "ingest.pending"


@pytest.mark.asyncio
async def test_publish_defaults_to_live_priority(monkeypatch) -> None:
    captured: dict = {}
    channel = _fake_channel(captured)
    conn = MagicMock()
    conn.channel = AsyncMock(return_value=channel)
    monkeypatch.setattr(publisher, "_get_connection", AsyncMock(return_value=conn))
    monkeypatch.setattr(publisher, "declare_ingest_topology", AsyncMock())

    await publisher.publish_ingest(_params())

    assert captured["msg"].priority == PRIO_LIVE


async def _publish_capture(monkeypatch, params: IngestParams) -> dict:
    captured: dict = {}
    channel = _fake_channel(captured)
    conn = MagicMock()
    conn.channel = AsyncMock(return_value=channel)
    monkeypatch.setattr(publisher, "_get_connection", AsyncMock(return_value=conn))
    monkeypatch.setattr(publisher, "declare_ingest_topology", AsyncMock())
    await publisher.publish_ingest(params)
    return captured


@pytest.mark.asyncio
async def test_default_graph_message_id_is_bare_doc_id(monkeypatch) -> None:
    captured = await _publish_capture(monkeypatch, _params())
    assert captured["msg"].message_id == "doc-1"


@pytest.mark.asyncio
async def test_other_graph_message_id_is_admission_key(monkeypatch) -> None:
    params = IngestParams(doc_id="doc-1", path="s3://b/k", graph_id="acme")
    captured = await _publish_capture(monkeypatch, params)
    assert captured["msg"].message_id == "acme:doc-1"
