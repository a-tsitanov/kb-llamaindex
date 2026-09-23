from datetime import UTC, datetime

from src.lens.model import Op
from src.lens.state import fold, state_to_dict

_seq = 0


def op(kind, payload, input_id="i1"):
    global _seq
    _seq += 1
    return Op(workspace_id="w", seq=_seq, kind=kind, payload=payload,
              input_id=input_id, created_at=datetime.now(UTC))


def obj(key, label="L", attrs=None, call="c1"):
    return {"key": key, "type": "person", "label": label, "attrs": attrs or {},
            "refs": [{"call_id": call, "path": "$"}]}


def test_add_objects_merges_same_key():
    st = fold([
        op("add_objects", {"objects": [obj("kb:1", "Си", {"a": 1}, "c1")]}, "i1"),
        op("add_objects", {"objects": [obj("kb:1", "Xi", {"a": 9, "b": 2}, "c2")]}, "i2"),
    ])
    o = st.objects["kb:1"]
    assert o.label == "Си"
    assert o.attrs == {"a": 1, "b": 2}
    assert [r.call_id for r in o.refs] == ["c1", "c2"]
    assert st.object_inputs["kb:1"] == ["i1", "i2"]


def test_hide_show_and_pin():
    st = fold([
        op("add_objects", {"objects": [obj("kb:1")]}),
        op("hide", {"keys": ["kb:1"]}, "i2"),
        op("pin", {"key": "kb:1", "x": 10, "y": 20}, None),
    ])
    assert st.hidden == {"kb:1"}
    assert st.pins["kb:1"] == {"x": 10, "y": 20}
    st2 = fold([*[op("add_objects", {"objects": [obj("kb:1")]})],
                op("hide", {"keys": ["kb:1"]}), op("show", {"keys": ["kb:1"]})])
    assert st2.hidden == set()


def test_undo_removes_whole_input():
    st = fold([
        op("add_objects", {"objects": [obj("kb:1")]}, "i1"),
        op("add_objects", {"objects": [obj("kb:2")]}, "i2"),
        op("add_relations", {"relations": [
            {"from_key": "kb:1", "to_key": "kb:2", "kind": "k"}]}, "i2"),
        op("undo", {"input_id": "i2"}, "i3"),
    ])
    assert set(st.objects) == {"kb:1"}
    assert st.relations == {}
    assert st.inputs == ["i1"]


def test_merge_redirects_objects_relations_and_later_adds():
    st = fold([
        op("add_objects", {"objects": [obj("kb:1", "Росатом"), obj("fofa:x", "ROSATOM"),
                                       obj("kb:2", "Лихачёв")]}),
        op("add_relations", {"relations": [
            {"from_key": "kb:2", "to_key": "fofa:x", "kind": "глава"}]}),
        op("merge", {"keep": "kb:1", "drop": "fofa:x"}, "i2"),
        op("add_objects", {"objects": [obj("fofa:x", "ROSATOM", {"asn": 1}, "c9")]}, "i3"),
    ])
    assert "fofa:x" not in st.objects
    assert st.objects["kb:1"].attrs == {"asn": 1}
    assert list(st.relations) == ["kb:2|глава|kb:1"]
    assert st.canon("fofa:x") == "kb:1"


def test_views_notes_mode():
    st = fold([
        op("add_view", {"view": {"kind": "raw", "key": "raw:c1", "call_id": "c1",
                                 "reason": "x"}}),
        op("add_note", {"note": {"key": "note:i1", "text": "t", "cites": []}}),
        op("set_mode", {"mode": "table"}),
    ])
    assert st.views["raw:c1"]["kind"] == "raw"
    assert st.notes[0].text == "t"
    assert st.mode == "table"


def test_state_to_dict_is_json_ready():
    import json

    st = fold([op("add_objects", {"objects": [obj("kb:1")]}),
               op("hide", {"keys": ["kb:1"]})])
    d = state_to_dict(st)
    json.dumps(d)
    assert d["objects"][0]["hidden"] is True
    assert d["objects"][0]["inputs"] == ["i1"]
    assert d["last_seq"] == st.last_seq


def test_repeated_relation_merges_refs():
    rel = lambda c: {"from_key": "kb:1", "to_key": "kb:2", "kind": "k",  # noqa: E731
                     "refs": [{"call_id": c, "path": "$"}]}
    st = fold([op("add_relations", {"relations": [rel("c1")]}, "i1"),
               op("add_relations", {"relations": [rel("c2")]}, "i2")])
    assert [r.call_id for r in st.relations["kb:1|k|kb:2"].refs] == ["c1", "c2"]
