import httpx
from openai import APITimeoutError

from src.lens.model import ToolCallRecord
from src.lens.normalizer import Normalizer, is_empty_result
from src.lens.shape import shape_hash
from src.lens.spec import ViewSpec
from src.lens.store import MemoryLensStore
from tests.test_lens.fakes import FakeLLM

PAYLOAD = {"results": [{"qid": "Q1", "name": "Росатом"}, {"qid": "Q2", "name": "ТВЭЛ"}]}
GOOD = {"objects": [{"name": "org", "each": "$.results[*]", "id": "$.qid",
                     "label": "$.name", "type": "organization"}]}
BAD = {"objects": [{"name": "org", "each": "$.items[*]", "id": "$.qid",
                    "label": "$.name", "type": "organization"}]}


def call(payload=PAYLOAD, is_error=False, args=None):
    return ToolCallRecord(id="c1", input_id="i1", server="kb-tools", namespace="kb",
                          tool="find", args=args or {}, payload=payload,
                          shape_hash=shape_hash(payload), is_error=is_error,
                          error="boom" if is_error else None, latency_ms=1)


def norm(llm, store=None, model="m"):
    return Normalizer(llm, store or MemoryLensStore(), model=model,
                      vocabulary=["organization", "person"], aggregate_threshold=25,
                      sample_chars=4000)


async def test_llm_spec_validated_and_cached_under_namespace():
    store = MemoryLensStore()
    llm = FakeLLM(json_replies=[GOOD])
    n = norm(llm, store)
    r = await n.normalize(call(), "Find orgs")
    assert r.source == "llm"
    assert [o.key for o in r.materialized.objects] == ["kb:Q1", "kb:Q2"]
    assert await store.get_spec("kb-tools", "find", n.cache_key(call())) == \
        ViewSpec.model_validate(GOOD)
    prompt = llm.json_calls[0]["messages"][-1]["content"]
    assert "Росатом" in prompt and "organization" in prompt and "Find orgs" in prompt


async def test_cache_hit_skips_llm():
    store = MemoryLensStore()
    n = norm(FakeLLM(), store)
    await store.put_spec("kb-tools", "find", n.cache_key(call()),
                         ViewSpec.model_validate(GOOD), "m")
    other = {"results": [{"qid": "Q9", "name": "Другое"}]}
    r = await n.normalize(call(other), "")
    assert r.source == "cache" and r.materialized.objects[0].key == "kb:Q9"
    assert n.llm.json_calls == []


async def test_model_change_invalidates_cache():
    store = MemoryLensStore()
    await norm(FakeLLM(json_replies=[GOOD]), store, model="m1").normalize(call(), "")
    llm2 = FakeLLM(json_replies=[GOOD])
    r = await norm(llm2, store, model="m2").normalize(call(), "")
    assert r.source == "llm" and len(llm2.json_calls) == 1


async def test_bad_spec_repaired_once():
    llm = FakeLLM(json_replies=[BAD, GOOD])
    r = await norm(llm).normalize(call(), "")
    assert r.source == "repair"
    assert "$.items[*]" in llm.json_calls[1]["messages"][-1]["content"]


async def test_two_failures_fall_back_to_raw():
    llm = FakeLLM(json_replies=[BAD, ValueError("no JSON")])
    r = await norm(llm).normalize(call(), "")
    assert r.source == "raw" and r.raw.key == "raw:c1" and r.materialized is None


async def test_llm_timeout_degrades_to_raw():
    llm = FakeLLM(json_replies=[APITimeoutError(request=httpx.Request("POST", "http://x"))])
    r = await norm(llm).normalize(call(), "")
    assert r.source == "raw" and "unavailable" in r.raw.reason


async def test_empty_result_skips_llm():
    llm = FakeLLM()
    for payload in ({"results": [], "total": 0}, {"results": []}, [], None):
        r = await norm(llm).normalize(call(payload), "")
        assert r.source == "raw" and r.raw.reason == "empty result"
    assert llm.json_calls == []
    assert not is_empty_result({"text": "prose"})


async def test_empty_spec_cached_only_for_object_free_payload():
    store = MemoryLensStore()
    n = norm(FakeLLM(json_replies=[{"objects": []}, {"objects": []}]), store)
    prose = {"text": "just prose"}
    r = await n.normalize(call(prose), "")
    assert r.source == "raw" and r.raw.reason == "no objects in response"
    assert await store.get_spec("kb-tools", "find", n.cache_key(call(prose))) == ViewSpec()
    await n.normalize(call(PAYLOAD), "")  # model flaked on real records
    assert await store.get_spec("kb-tools", "find", n.cache_key(call(PAYLOAD))) is None


async def test_known_keys_attach_relations_and_reach_prompt():
    spec = {"objects": [{"name": "n", "each": "$.results[*]", "id": "$.qid",
                         "label": "$.name", "type": "organization"}],
            "relations": [{"each": "$.results[*]", "from_id": "$args.id", "to_id": "$.qid",
                           "kind": "связан"}]}
    llm = FakeLLM(json_replies=[spec])
    r = await norm(llm).normalize(call(args={"id": "Q0"}), "", known_keys={"kb:Q0"})
    assert {rel.key for rel in r.materialized.relations} == {
        "kb:Q0|связан|kb:Q1", "kb:Q0|связан|kb:Q2"}
    assert "kb:Q0" in llm.json_calls[0]["messages"][-1]["content"]


async def test_error_call_is_raw_without_llm():
    llm = FakeLLM()
    r = await norm(llm).normalize(call(is_error=True), "")
    assert r.source == "raw" and "boom" in r.raw.reason
    assert llm.json_calls == []
