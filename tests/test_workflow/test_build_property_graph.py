from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.ingestion.identifier_transform import _AUGMENT_METADATA_KEY
from src.workflow.activities.build_property_graph import (
    _strip_graph_unsafe_metadata,
    build_property_graph,
)
from src.workflow.contracts import Ctx, KGExtracted, Merged, Parsed


@pytest.fixture(autouse=True)
def _no_watch_journal_db():
    """The entity-watch journal write would reach for a real Postgres pool;
    tests that care about it patch it themselves."""
    with patch(
        "src.workflow.activities.build_property_graph.record_watch_journals",
        new=AsyncMock(),
    ):
        yield


def test_strip_graph_unsafe_removes_augment_key() -> None:
    """``canonical_identifiers_augment`` must be removed from Chunk node
    metadata before the graph upsert — consistent with fix #5's goal of keeping
    the augment block out of all stores."""
    node = MagicMock()
    node.metadata = {
        "safe_key": "value",
        _AUGMENT_METADATA_KEY: "Канонические идентификаторы: +79001234567 (PHONE)",
        "canonical_identifiers": [{"canonical": "+79001234567"}],
    }
    _strip_graph_unsafe_metadata([node])
    assert _AUGMENT_METADATA_KEY not in node.metadata
    assert "canonical_identifiers" not in node.metadata
    assert node.metadata.get("safe_key") == "value"


@pytest.mark.asyncio
async def test_trust_conflicts_are_resolved_and_logged_when_policy_configured(
    monkeypatch,
):
    """With a trust table configured, the write path resolves the stored belief
    first and logs the conflict to `fact_supersede` (see edge_conflicts.py)."""
    from types import SimpleNamespace

    from src.config import settings
    from src.graph.edge_conflicts import StoredEdge

    monkeypatch.setattr(settings.signals, "source_trust", {"news": 0.2})
    monkeypatch.setattr(settings.signals, "source_trust_default", 0.5)

    n = MagicMock(node_id="a")
    n.metadata = {}
    # A relation the graph already believes the OTHER way round, asserted by a
    # more trusted document.
    rel = SimpleNamespace(
        source_id="Иванов", target_id="ООО Ромашка", label="WORKS_AT",
        properties={"polarity": "negated"},
    )
    staging = MagicMock()
    staging.read_pickle.return_value = ([], [rel], [n])

    graph_store = MagicMock()
    recorded: list[list[dict]] = []

    class _PG:
        async def record_fact_conflicts(self, rows):
            recorded.append(rows)

    ctx = Ctx(
        doc_id="doc-new", local_path="/x", cleanup_dir=None, workflow_run_id="r",
        group="news",
    )
    parsed = Parsed(ctx=ctx, nodes_uri="s3://kb-staging/r/parsed.pkl", chunk_count=1)
    kg = KGExtracted(parsed=parsed, nodes_with_kg_uri="s3://kb-staging/r/kg.pkl")
    merged = Merged(kg=kg, merged_entities_uri="s3://kb-staging/r/merged.pkl")

    with patch(
        "src.workflow.activities.build_property_graph.build_staging_store",
        return_value=staging,
    ), patch(
        "src.workflow.activities.build_property_graph.build_graph_store",
        return_value=graph_store,
    ), patch(
        "src.graph.edge_conflicts.load_stored_edges",
        return_value={("Иванов", "ООО Ромашка"): StoredEdge("affirmed", 0.9, "doc-old")},
    ), patch(
        "src.storage.postgres.AsyncPostgres", return_value=_PG(),
    ), patch(
        "src.workflow.activities.build_property_graph.activity"
    ):
        await build_property_graph(merged)

    # The trusted stored belief survived the low-trust flip …
    graph_store.upsert_relations.assert_called_once_with([rel])
    assert rel.properties["polarity"] == "affirmed"
    # … and the rejected claim is on the audit log.
    assert len(recorded) == 1
    assert recorded[0][0]["winner"] == "stored"
    assert recorded[0][0]["new_polarity"] == "negated"
    assert recorded[0][0]["new_doc_id"] == "doc-new"


def test_build_property_graph_writes_without_retry_wrapper():
    # importlib, not ``import ... as``: the package re-exports the activity
    # FUNCTION under the same name, so ``import a.b.c as m`` binds the function.
    import importlib

    bpg = importlib.import_module("src.workflow.activities.build_property_graph")
    assert not hasattr(bpg, "write_with_retry")


@pytest.mark.asyncio
async def test_build_property_graph_upserts_entities_and_relations(monkeypatch):
    """R8: the nebula store receives exactly the staged entities/relations and
    the activity reports their counts."""
    from types import SimpleNamespace

    from src.config import settings

    monkeypatch.setattr(settings.signals, "source_trust", {})
    monkeypatch.setattr(settings.events, "first_seen_enabled", False)

    e1 = SimpleNamespace(id="id-a", name="Иванов")
    e2 = SimpleNamespace(id="id-b", name="ООО Ромашка")
    rel = SimpleNamespace(
        source_id="id-a", target_id="id-b", label="WORKS_AT", properties={},
    )
    n = MagicMock(node_id="c1")
    n.metadata = {}
    staging = MagicMock()
    staging.read_pickle.return_value = ([e1, e2], [rel], [n])
    graph_store = MagicMock()

    ctx = Ctx(doc_id="d1", local_path="/x", cleanup_dir=None, workflow_run_id="r")
    parsed = Parsed(ctx=ctx, nodes_uri="s3://kb-staging/r/parsed.pkl", chunk_count=1)
    kg = KGExtracted(parsed=parsed, nodes_with_kg_uri="s3://kb-staging/r/kg.pkl")
    merged = Merged(kg=kg, merged_entities_uri="s3://kb-staging/r/merged.pkl")

    with patch(
        "src.workflow.activities.build_property_graph.build_staging_store",
        return_value=staging,
    ), patch(
        "src.workflow.activities.build_property_graph.build_graph_store",
        return_value=graph_store,
    ), patch(
        "src.workflow.activities.build_property_graph.activity"
    ):
        out = await build_property_graph(merged)

    graph_store.upsert_nodes.assert_called_once_with([e1, e2])
    graph_store.upsert_relations.assert_called_once_with([rel])
    assert out.entities == 2
    assert out.relations == 1


@pytest.mark.asyncio
async def test_writes_watch_journals_with_the_pairs_the_graph_created(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings.signals, "source_trust", {})
    monkeypatch.setattr(settings.events, "first_seen_enabled", False)

    n = MagicMock(node_id="a")
    n.metadata = {}
    entities = [MagicMock()]
    relations = [MagicMock()]
    staging = MagicMock()
    staging.read_pickle.return_value = (entities, relations, [n])
    graph_store = MagicMock()
    graph_store.upsert_relations.return_value = [("va", "vb")]

    ctx = Ctx(doc_id="d", local_path="/x", cleanup_dir=None, workflow_run_id="r",
              doc_date_epoch=19794, backfill=True)
    parsed = Parsed(ctx=ctx, nodes_uri="s3://kb-staging/r/parsed.pkl", chunk_count=1)
    kg = KGExtracted(parsed=parsed, nodes_with_kg_uri="s3://kb-staging/r/kg.pkl")
    merged = Merged(kg=kg, merged_entities_uri="s3://kb-staging/r/merged.pkl")

    journal = AsyncMock()
    with patch(
        "src.workflow.activities.build_property_graph.build_staging_store",
        return_value=staging,
    ), patch(
        "src.workflow.activities.build_property_graph.build_graph_store",
        return_value=graph_store,
    ), patch(
        "src.workflow.activities.build_property_graph.record_watch_journals", new=journal,
    ), patch(
        "src.workflow.activities.build_property_graph.activity"
    ):
        await build_property_graph(merged)

    journal.assert_awaited_once()
    args, kwargs = journal.await_args
    assert args[1] is entities and args[2] is relations
    assert args[3] == [("va", "vb")]
    assert kwargs == {"doc_id": "d", "doc_date_epoch": 19794, "backfill": True}
    # the journal repository is scoped to the activity's graph
    assert args[0].graph.id == merged.graph_id == "default"


@pytest.mark.asyncio
async def test_skips_watch_journals_for_non_default_graph(monkeypatch):
    """Entity watch is default-only (the monitor sweep reads only the default
    graph's journals) — a non-default graph must not grow journals."""
    from src.config import settings

    monkeypatch.setattr(settings.signals, "source_trust", {})
    monkeypatch.setattr(settings.events, "first_seen_enabled", False)

    n = MagicMock(node_id="a")
    n.metadata = {}
    staging = MagicMock()
    staging.read_pickle.return_value = ([MagicMock()], [MagicMock()], [n])
    graph_store = MagicMock()
    graph_store.upsert_relations.return_value = [("va", "vb")]

    ctx = Ctx(doc_id="d", local_path="/x", cleanup_dir=None, workflow_run_id="r",
              graph_id="acme")
    parsed = Parsed(ctx=ctx, nodes_uri="s3://kb-staging/r/parsed.pkl", chunk_count=1)
    kg = KGExtracted(parsed=parsed, nodes_with_kg_uri="s3://kb-staging/r/kg.pkl")
    merged = Merged(kg=kg, merged_entities_uri="s3://kb-staging/r/merged.pkl")
    assert merged.graph_id == "acme"

    journal = AsyncMock()
    with patch(
        "src.workflow.activities.build_property_graph.build_staging_store",
        return_value=staging,
    ), patch(
        "src.workflow.activities.build_property_graph.build_graph_store",
        return_value=graph_store,
    ), patch(
        "src.workflow.activities.build_property_graph.record_watch_journals", new=journal,
    ), patch(
        "src.workflow.activities.build_property_graph.activity"
    ):
        out = await build_property_graph(merged)

    journal.assert_not_awaited()
    assert out.relations == 1


def test_backfill_flag_flows_from_ingest_params_to_ctx():
    from src.workflow.contracts import IngestParams

    assert IngestParams(doc_id="d", path="p").backfill is False
    assert IngestParams(doc_id="d", path="p", backfill=True).backfill is True
    assert Ctx(doc_id="d", local_path="/x", cleanup_dir=None, workflow_run_id="r").backfill is False
