"""Scheduler admission is keyed by ``(graph_id, doc_id)``: the same doc_id in
two graphs is two admissions, and the child workflow id stays graph-scoped."""
from __future__ import annotations

from src.workflow.contracts import IngestParams
from src.workflow.ingest_scheduler import IngestSchedulerWorkflow, admission_key


def test_same_doc_id_in_two_graphs_is_two_admissions():
    a = IngestParams(doc_id="d1", path="p", graph_id="acme")
    b = IngestParams(doc_id="d1", path="p")
    assert admission_key(a) != admission_key(b)
    assert admission_key(b) == "default:d1"
    assert admission_key(a) == "acme:d1"


def test_submit_dedupes_per_graph_not_per_doc_id():
    wf = IngestSchedulerWorkflow()
    wf.submit(IngestParams(doc_id="d1", path="p"))
    wf.submit(IngestParams(doc_id="d1", path="p", graph_id="acme"))
    wf.submit(IngestParams(doc_id="d1", path="p2"))  # same graph+doc → dedupe
    assert set(wf._params) == {"default:d1", "acme:d1"}
    assert list(wf._state.pending).count("default:d1") == 1
    assert "acme:d1" in wf._state.pending
    assert wf._params["default:d1"].path == "p2"


def test_carry_forward_keeps_ingest_params_shape():
    wf = IngestSchedulerWorkflow()
    wf.submit(IngestParams(doc_id="d1", path="p"))
    wf.submit(IngestParams(doc_id="d1", path="p", graph_id="acme"))
    carried = wf._carry_forward()
    assert all(isinstance(p, IngestParams) for p in carried)
    assert {(p.graph_id, p.doc_id) for p in carried} == {
        ("default", "d1"), ("acme", "d1"),
    }
