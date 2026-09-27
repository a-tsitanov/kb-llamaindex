import inspect
import typing

import pytest

from src.tenancy.context import DEFAULT_GRAPH_ID
from src.workflow import worker as w

# Zero-arg workflows started by Temporal schedules with a fixed id.  They are
# system-wide sweeps over the default graph: default-only in Plan A.
_DEFAULT_ONLY_IN_PLAN_A = {"MonitorSweepWorkflow", "WikiSweepWorkflow"}


def _workflow_classes():
    out = set()
    for group in w.WORKER_GROUPS:
        try:
            spec = w.workflows_for_group(group)
        except AttributeError:
            pytest.skip("expose workflows_for_group(group) from worker.py (see Step 3)")
        out.update(spec)
    return out


def _run_input_type(cls):
    run = cls.run
    hints = typing.get_type_hints(run)
    params = [p for p in inspect.signature(run).parameters if p != "self"]
    return hints[params[0]] if params else None


def test_every_workflow_input_carries_graph_id():
    classes = _workflow_classes()
    assert len(classes) == 13
    missing = []
    for cls in classes:
        t = _run_input_type(cls)
        if t is None:
            # default-only in Plan A
            assert cls.__name__ in _DEFAULT_ONLY_IN_PLAN_A, cls.__name__
            continue
        fields = getattr(t, "model_fields", {})
        if "graph_id" not in fields:
            missing.append(f"{cls.__name__}({t.__name__})")
    assert missing == []


def test_legacy_payload_without_graph_id_defaults():
    from src.workflow.contracts import Ctx, IngestParams
    p = IngestParams.model_validate({"doc_id": "d1", "path": "s3://b/k"})
    assert p.graph_id == DEFAULT_GRAPH_ID
    c = Ctx.model_validate({"doc_id": "d1", "local_path": "/x", "cleanup_dir": None, "workflow_run_id": "r"})
    assert c.graph_id == DEFAULT_GRAPH_ID


def test_every_storage_activity_input_carries_graph_id():
    from src.workflow.activity_inputs import STORAGE_ACTIVITY_INPUTS
    assert STORAGE_ACTIVITY_INPUTS
    missing = [t.__name__ for t in STORAGE_ACTIVITY_INPUTS if "graph_id" not in t.model_fields]
    assert missing == []


def test_activity_outputs_inherit_graph_id_from_nested_input():
    from src.workflow.contracts import Ctx, KGExtracted, Merged, Parsed, SkipIn

    ctx = Ctx(doc_id="d", local_path="/x", cleanup_dir=None,
              workflow_run_id="r", graph_id="acme")
    parsed = Parsed(ctx=ctx, nodes_uri="u", chunk_count=1)
    kg = KGExtracted(parsed=parsed, nodes_with_kg_uri="k")
    merged = Merged(kg=kg, merged_entities_uri="m")
    assert (parsed.graph_id, kg.graph_id, merged.graph_id) == ("acme",) * 3
    assert SkipIn(ctx=ctx).graph_id == "acme"
    # round-trip through JSON (Temporal payload) keeps it
    assert Merged.model_validate_json(merged.model_dump_json()).graph_id == "acme"


def test_community_summarize_specs_carry_graph_id():
    from src.workflow.contracts import DetectCommunitiesResult, DetectedCommunity
    from src.workflow.search.community_wf import build_summarize_specs

    detect = DetectCommunitiesResult(communities=[DetectedCommunity(community_id="c1")])
    assert build_summarize_specs(detect)[0].graph_id == DEFAULT_GRAPH_ID
    assert build_summarize_specs(detect, "acme")[0].graph_id == "acme"


# ── R-P3: wrapper graph_id must agree with its nested ctx/params ──────


def _ctx(gid=None):
    data = {"doc_id": "d", "local_path": "/x", "cleanup_dir": None, "workflow_run_id": "r"}
    if gid is not None:
        data["graph_id"] = gid
    return data


def _wrapper_payloads(ctx, **extra):
    """Minimal dict payloads for SkipIn / FinalizeIn / MarkFailedIn."""
    params = extra.pop("params", {"doc_id": "d", "path": "s3://b/k"})
    return {
        "SkipIn": {"ctx": ctx, **extra},
        "FinalizeIn": {"ctx": ctx, "indexed": {"node_ids": [], "count": 0},
                       "graph_status": "completed", **extra},
        "MarkFailedIn": {"ctx": ctx, "params": params, "error": "e", **extra},
    }


@pytest.mark.parametrize("name", ["SkipIn", "FinalizeIn", "MarkFailedIn"])
def test_wrapper_graph_id_mismatching_nested_ctx_is_rejected(name):
    from pydantic import ValidationError

    from src.workflow import contracts as c

    payload = _wrapper_payloads(_ctx("acme"), graph_id="other")[name]
    with pytest.raises(ValidationError, match="graph_id"):
        getattr(c, name).model_validate(payload)


def test_mark_failed_wrapper_mismatching_params_is_rejected():
    from pydantic import ValidationError

    from src.workflow.contracts import MarkFailedIn

    with pytest.raises(ValidationError, match="graph_id"):
        MarkFailedIn.model_validate({
            "ctx": None,
            "params": {"doc_id": "d", "path": "s3://b/k", "graph_id": "acme"},
            "error": "e",
            "graph_id": "other",
        })


@pytest.mark.parametrize("name", ["SkipIn", "FinalizeIn", "MarkFailedIn"])
def test_wrapper_graph_id_omitted_is_filled_from_nested(name):
    from src.workflow import contracts as c

    params = {"doc_id": "d", "path": "s3://b/k", "graph_id": "acme"}
    payload = _wrapper_payloads(_ctx("acme"), params=params)[name]
    assert getattr(c, name).model_validate(payload).graph_id == "acme"


def test_mark_failed_without_ctx_takes_graph_id_from_params():
    from src.workflow.contracts import MarkFailedIn

    m = MarkFailedIn.model_validate({
        "ctx": None,
        "params": {"doc_id": "d", "path": "s3://b/k", "graph_id": "acme"},
        "error": "e",
    })
    assert m.graph_id == "acme"


@pytest.mark.parametrize("name", ["SkipIn", "FinalizeIn", "MarkFailedIn"])
def test_wrapper_legacy_payload_without_any_graph_id_is_default(name):
    from src.workflow import contracts as c

    payload = _wrapper_payloads(_ctx())[name]
    m = getattr(c, name).model_validate(payload)
    assert m.graph_id == DEFAULT_GRAPH_ID
    assert m.ctx.graph_id == DEFAULT_GRAPH_ID
