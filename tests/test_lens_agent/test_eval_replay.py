"""Offline eval: replay board writes recorded in real runs through the write gate.

Fixtures (``tests/fixtures/lens_eval``) hold the stored source payloads of a run and every board
write the model made. The gate must let through only objects / relations that are rows of those
payloads, copied from the row, and reject the garbage the models actually produced.
"""
import json
from pathlib import Path

import pytest

from src.lens.keys import normalize_id
from src.lens_agent.calls import CallInfo, RunCalls
from src.lens_agent.rows import entity_rows, relation_rows

FIX = Path(__file__).parents[1] / "fixtures" / "lens_eval"
RUNS = sorted(p.stem for p in FIX.glob("*.json"))


def replay_calls(run: dict) -> RunCalls:
    rc = RunCalls(run["run_id"], store=None, emitter=None)
    for cid, c in run["calls"].items():
        rc.registry[cid] = CallInfo(cid, c["server"], c["tool"], "kb")
        rc._payloads[cid] = c["payload"]
    return rc


async def no_board(name, args):  # the board is not consulted for keys written in this replay
    raise RuntimeError("offline")


async def replay(name: str):
    run = json.loads((FIX / f"{name}.json").read_text())
    rc = replay_calls(run)
    out = {"objects": [], "rejected": [], "relations": [], "rel_rejected": []}
    for w in run["writes"]:
        if w["tool"] == "add_objects":
            ok, bad = rc._attach_objects(w["args"].get("objects"))
            out["objects"] += ok
            out["rejected"] += bad
        elif w["tool"] == "add_relations":
            ok, bad = await rc._attach_relations(w["args"].get("relations"), no_board)
            out["relations"] += ok
            out["rel_rejected"] += bad
    return run, out


@pytest.mark.parametrize("name", RUNS)
async def test_every_accepted_object_is_a_source_row(name):
    run, out = await replay(name)
    for o in out["objects"]:
        payload = run["calls"][o["source"]["call_id"]]["payload"]
        row = next(r for r in entity_rows(payload) if r.id == o["id"])
        assert (o["label"], o["type"]) == (row.label, row.type)
        assert o["attrs"]["source_id"] == row.id
    for bad in out["rejected"]:
        assert bad["reason"]


@pytest.mark.parametrize("name", RUNS)
async def test_every_accepted_relation_is_a_source_relation(name):
    run, out = await replay(name)
    rels = {(normalize_id(r.src), normalize_id(r.tgt), r.kind)
            for c in run["calls"].values() for r in relation_rows(c["payload"])}
    for r in out["relations"]:
        ends = {normalize_id(r["from"].split(":", 1)[1]), normalize_id(r["to"].split(":", 1)[1])}
        assert any({a, b} == ends and k == r["kind"] for a, b, k in rels), r


async def test_glued_label_from_rosatom_people_is_rejected_with_its_parts_as_nearest():
    _, out = await replay("rosatom_people")
    glued = [b for b in out["rejected"] if "/" in str(b["item"].get("label", ""))]
    assert glued
    assert {n["label"] for n in glued[0]["nearest"][:2]} == {"Военный ТЦК", "Одесский ТЦКшник"}
    assert not any("/" in o["label"] for o in out["objects"])


async def test_replay_summary_is_stable():
    # baseline of the gate over the recorded runs: accepted / rejected objects and relations
    summary = {}
    for name in RUNS:
        _, out = await replay(name)
        summary[name] = tuple(len(out[k]) for k in
                              ("objects", "rejected", "relations", "rel_rejected"))
    print(summary)
    assert all(sum(v) > 0 for v in summary.values())


async def test_invented_relations_from_likhachev_gemma_are_rejected():
    # the model linked Лихачёв to Ушаков / «ТАСС / Москва» as «связан»: no such edge in c1
    _, out = await replay("likhachev_gemma")
    assert out["relations"] == [] and len(out["rel_rejected"]) == 6
