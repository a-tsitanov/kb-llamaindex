import json

from src.lens.shape import sample_json, shape_hash, skeleton


def test_shape_hash_ignores_values_and_length():
    a = {"hosts": [{"ip": "1.1.1.1", "port": 22}]}
    b = {"hosts": [{"ip": "2.2.2.2", "port": 443}, {"ip": "3.3.3.3", "port": 80}]}
    assert shape_hash(a) == shape_hash(b)


def test_shape_hash_sees_key_and_type_changes():
    base = {"hosts": [{"ip": "1.1.1.1", "port": 22}]}
    assert shape_hash(base) != shape_hash({"hosts": [{"ip": "1.1.1.1", "port": "22"}]})
    assert shape_hash(base) != shape_hash({"hosts": [{"ip": "1.1.1.1"}]})


def test_shape_hash_bool_is_not_number():
    assert shape_hash({"x": True}) != shape_hash({"x": 1})


def test_skeleton_truncates_lists_and_strings():
    sk = skeleton({"a": list(range(10)), "s": "x" * 50}, max_items=2, max_str=10)
    assert sk["a"] == [0, 1, "… 8 more"]
    assert sk["s"] == "x" * 10 + "…"


def test_sample_json_respects_budget():
    big = {"hosts": [{"ip": f"10.0.{i // 256}.{i % 256}", "banner": "b" * 500}
                     for i in range(10_000)]}
    out = sample_json(big, budget_chars=2000)
    assert len(out) <= 2020
    assert "10.0.0.0" in out


def test_sample_json_small_payload_is_valid_json():
    assert json.loads(sample_json({"a": [1, 2]})) == {"a": [1, 2]}


def test_sample_json_is_full_when_it_fits():
    payload = {"results": [{"id": f"Q{i}", "name": "x" * 200} for i in range(10)]}
    assert json.loads(sample_json(payload, budget_chars=6000)) == payload
