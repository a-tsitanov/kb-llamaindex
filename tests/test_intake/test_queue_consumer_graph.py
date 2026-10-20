"""Consumer workflow ids are graph-scoped: the default graph keeps the legacy
``ingest-<doc_id>`` bytes; any other graph gets ``ingest-<graph>-<doc_id>``,
for both the start and the attach-to-running path."""
from __future__ import annotations

import pytest
from temporalio.exceptions import WorkflowAlreadyStartedError

from src.intake.queue import consumer
from src.workflow.contracts import IngestParams


class _Handle:
    async def result(self):
        return None


class _Client:
    def __init__(self, already_started: bool = False):
        self.ids: list[str] = []
        self.attached: list[str] = []
        self._already = already_started

    async def execute_workflow(self, fn, params, *, id, **kw):
        self.ids.append(id)
        if self._already:
            raise WorkflowAlreadyStartedError(id, "DocumentIngestWorkflow")

    def get_workflow_handle(self, wf_id):
        self.attached.append(wf_id)
        return _Handle()


@pytest.mark.asyncio
async def test_default_graph_keeps_legacy_workflow_id():
    c = _Client()
    await consumer._start_or_attach(c, IngestParams(doc_id="d1", path="s3://b/k"))
    assert c.ids == ["ingest-d1"]


@pytest.mark.asyncio
async def test_other_graph_gets_scoped_workflow_id():
    c = _Client()
    await consumer._start_or_attach(
        c, IngestParams(doc_id="d1", path="s3://b/k", graph_id="acme"),
    )
    assert c.ids == ["ingest-acme-d1"]


@pytest.mark.asyncio
async def test_attach_uses_the_same_graph_scoped_id():
    c = _Client(already_started=True)
    await consumer._start_or_attach(
        c, IngestParams(doc_id="d1", path="s3://b/k", graph_id="acme"),
    )
    assert c.ids == ["ingest-acme-d1"]
    assert c.attached == ["ingest-acme-d1"]
