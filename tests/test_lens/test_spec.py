import pytest
from pydantic import ValidationError

from src.lens.spec import ObjectRule, RelationRule, SpecError, ViewSpec, materialize

VOCAB = ["person", "event", "ip", "organization"]
PAYLOAD = {
    "events": [
        {"id": "E1", "title": "Визит в Пекин", "date": "2024-05-16",
         "participants": [{"qid": "Q1", "name": "Путин"}, {"qid": "Q2", "name": "Си"}]},
        {"id": "E2", "title": "ШОС", "participants": [{"qid": "Q1", "name": "Путин"}]},
        {"id": None, "title": "broken"},
    ]
}


def spec(**kw):
    return ViewSpec.model_validate(kw)


def run(s, payload=PAYLOAD, threshold=25, **kw):
    return materialize(s, payload, namespace="kb", call_id="c1", vocabulary=VOCAB,
                       aggregate_threshold=threshold, **kw)


def test_objects_and_relations_with_refs():
    s = spec(
        objects=[
            {"name": "ev", "each": "$.events[*]", "id": "$.id", "label": "$.title",
             "type": "event", "attrs": {"date": "$.date"}},
            {"name": "p", "each": "$.events[*].participants[*]", "id": "$.qid",
             "label": "$.name", "type": "person"},
        ],
        relations=[{"each": "$.events[*]", "from_id": "$.id", "to_each": "$.participants[*]",
                    "to_id": "$.qid", "kind": "участник"}],
    )
    m = run(s)
    keys = [o.key for o in m.objects]
    assert keys == ["kb:E1", "kb:E2", "kb:Q1", "kb:Q2"]
    e1 = m.objects[0]
    assert e1.attrs == {"date": "2024-05-16"}
    assert e1.refs[0].path == "$.events[0]"
    assert {r.key for r in m.relations} == {
        "kb:E1|участник|kb:Q1", "kb:E1|участник|kb:Q2", "kb:E2|участник|kb:Q1"}
    assert m.relations[0].refs[0].path == "$.events[0]"


def test_single_root_object():
    m = run(spec(objects=[{"name": "o", "id": "$.qid", "label": "$.name",
                           "type": "organization"}]),
            payload={"qid": "Q7", "name": "Росатом"})
    assert m.objects[0].key == "kb:Q7"
    assert m.objects[0].refs[0].path == "$"


def test_unknown_type_is_error():
    with pytest.raises(SpecError) as e:
        run(spec(objects=[{"name": "o", "each": "$.events[*]", "id": "$.id",
                           "label": "$.title", "type": "spaceship"}]))
    assert "spaceship" in str(e.value)


def test_each_matching_nothing_is_error():
    with pytest.raises(SpecError):
        run(spec(objects=[{"name": "o", "each": "$.nope[*]", "id": "$.id",
                           "label": "$.title", "type": "event"}]))


def test_id_resolving_nowhere_is_error():
    with pytest.raises(SpecError):
        run(spec(objects=[{"name": "o", "each": "$.events[*]", "id": "$.uuid",
                           "label": "$.title", "type": "event"}]))


def test_bad_path_syntax_is_error():
    with pytest.raises(SpecError):
        run(spec(objects=[{"name": "o", "each": "events", "id": "$.id",
                           "label": "$.title", "type": "event"}]))


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        ViewSpec.model_validate({"objects": [], "values": {"x": 1}})


def test_large_list_becomes_aggregate():
    hosts = {"hosts": [{"ip": f"10.0.0.{i}", "port": 22} for i in range(30)]}
    m = run(spec(objects=[{"name": "h", "each": "$.hosts[*]", "id": "$.ip", "label": "$.ip",
                           "type": "ip", "attrs": {"port": "$.port"}}]),
            payload=hosts, threshold=25)
    assert m.objects == []
    agg = m.aggregates[0]
    assert agg.key == "agg:c1:h" and agg.count == 30 and agg.label == "ip · 30"
    assert agg.rows_ref.path == "$.hosts[*]"
    assert [c.name for c in agg.columns] == ["id", "label", "port"]


def test_aggregate_drops_root_and_args_scoped_attr_columns():
    hosts = {"center": "HQ", "hosts": [{"ip": f"10.0.0.{i}", "port": 22} for i in range(30)]}
    m = run(spec(objects=[{
        "name": "h", "each": "$.hosts[*]", "id": "$.ip", "label": "$.ip", "type": "ip",
        "attrs": {"port": "$.port", "center": "$root.center", "arg": "$args.x"},
    }]), payload=hosts, threshold=25, args={"x": "ignored"})
    agg = m.aggregates[0]
    assert [c.name for c in agg.columns] == ["id", "label", "port"]


def test_aggregate_rejects_root_scoped_label():
    hosts = {"center": "HQ", "hosts": [{"ip": f"10.0.0.{i}"} for i in range(30)]}
    with pytest.raises(SpecError) as e:
        run(spec(objects=[{"name": "h", "each": "$.hosts[*]", "id": "$.ip",
                           "label": "$root.center", "type": "ip"}]),
            payload=hosts, threshold=25)
    assert "item-relative id/label" in str(e.value)


def test_aggregate_rejects_args_scoped_label():
    hosts = {"hosts": [{"ip": f"10.0.0.{i}"} for i in range(30)]}
    with pytest.raises(SpecError) as e:
        run(spec(objects=[{"name": "h", "each": "$.hosts[*]", "id": "$.ip",
                           "label": "$args.x", "type": "ip"}]),
            payload=hosts, threshold=25, args={"x": "same-for-all"})
    assert "item-relative id/label" in str(e.value)


def test_empty_spec_is_empty():
    assert run(spec()).is_empty()


def test_rules_are_models():
    assert ObjectRule(name="a", id="$.x", label="$.y", type="ip").each is None
    assert RelationRule(each="$[*]", from_id="$.a", to_id="$.b", kind="k").to_each is None


def test_duplicates_do_not_trigger_aggregate():
    # 10 meetings x the same 3 participants = 30 rows but 3 unique persons
    payload = {"events": [{"id": f"E{i}", "title": "t", "participants": [
        {"qid": "P1", "name": "Путин"}, {"qid": "P2", "name": "Си"}, {"qid": "P3", "name": "Ван"},
    ]} for i in range(10)]}
    m = run(spec(
        objects=[{"name": "p", "each": "$.events[*].participants[*]", "id": "$.qid",
                  "label": "$.name", "type": "person"}]), payload=payload, threshold=25)
    assert m.aggregates == []
    assert sorted(o.key for o in m.objects) == ["kb:P1", "kb:P2", "kb:P3"]
    assert len(m.objects[0].refs) == 10


def test_relation_to_known_canvas_object_via_root_path():
    # neighbours response: the centre is outside the items, and is already on canvas
    payload = {"center": "Q1", "neighbours": [{"id": "Q2", "name": "B"}]}
    s = spec(
        objects=[{"name": "n", "each": "$.neighbours[*]", "id": "$.id", "label": "$.name",
                  "type": "person"}],
        relations=[{"each": "$.neighbours[*]", "from_id": "$root.center", "to_id": "$.id",
                    "kind": "связан"}])
    assert run(s, payload=payload).relations == []  # Q1 unknown: dropped, not an error
    m = run(s, payload=payload, known_keys={"kb:Q1"})
    assert [r.key for r in m.relations] == ["kb:Q1|связан|kb:Q2"]


def test_args_scope():
    payload = {"neighbours": [{"id": "Q2", "name": "B"}]}
    s = spec(
        objects=[{"name": "n", "each": "$.neighbours[*]", "id": "$.id", "label": "$.name",
                  "type": "person"}],
        relations=[{"each": "$.neighbours[*]", "from_id": "$args.entity_id", "to_id": "$.id",
                    "kind": "связан"}])
    m = run(s, payload=payload, args={"entity_id": "Q1"}, known_keys={"kb:Q1"})
    assert [r.key for r in m.relations] == ["kb:Q1|связан|kb:Q2"]


def test_repeated_relation_keeps_all_refs():
    payload = {"pairs": [{"a": "E1", "b": "P1"}, {"a": "E1", "b": "P1"}],
               "objs": [{"id": "E1"}, {"id": "P1"}]}
    s = spec(
        objects=[{"name": "o", "each": "$.objs[*]", "id": "$.id", "label": "$.id",
                  "type": "person"}],
        relations=[{"each": "$.pairs[*]", "from_id": "$.a", "to_id": "$.b", "kind": "k"}])
    (rel,) = run(s, payload=payload).relations
    assert [r.path for r in rel.refs] == ["$.pairs[0]", "$.pairs[1]"]


KB_ENTITIES = {"entities": [
    {"entity_name": "Росатом Квантовые технологии", "entity_type": "Organization",
     "description": "d1"},
    {"entity_name": "Аппаратные закладки", "entity_type": "Concept", "description": "d2"},
    {"entity_name": "Лихачёв", "entity_type": "Person", "description": "d3"},
    {"entity_name": "Постановление №719", "entity_type": "LegalAct", "description": "d4"},
]}
VOCAB_ALL = ["person", "organization", "event", "location", "document", "topic", "other"]


def run_kb(s, payload=KB_ENTITIES, threshold=25, preview=0):
    return materialize(s, payload, namespace="kb", call_id="c1", vocabulary=VOCAB_ALL,
                       aggregate_threshold=threshold, aggregate_preview=preview)


def test_each_pointing_at_the_list_itself_is_expanded():
    rule = {"name": "e", "each": "$.entities", "id": "$.entity_name",
            "label": "$.entity_name", "type": "other"}
    star = dict(rule, each="$.entities[*]")
    a, b = run_kb(spec(objects=[rule])), run_kb(spec(objects=[star]))
    assert [o.key for o in a.objects] == [o.key for o in b.objects]
    assert len(a.objects) == 4
    assert a.objects[0].refs[0].path == "$.entities[0]"


def test_type_path_maps_kb_types_to_vocabulary():
    m = run_kb(spec(objects=[{"name": "e", "each": "$.entities[*]", "id": "$.entity_name",
                              "label": "$.entity_name", "type": "other",
                              "type_path": "$.entity_type"}]))
    assert {o.label: o.type for o in m.objects} == {
        "Росатом Квантовые технологии": "organization", "Аппаратные закладки": "topic",
        "Лихачёв": "person", "Постановление №719": "other"}


def test_type_path_unknown_value_falls_back_to_rule_type():
    m = run_kb(spec(objects=[{"name": "e", "each": "$.entities[*]", "id": "$.entity_name",
                              "label": "$.entity_name", "type": "document",
                              "type_path": "$.entity_type"}]))
    assert {o.label: o.type for o in m.objects}["Постановление №719"] == "document"


def test_type_path_missing_on_item_uses_rule_type():
    payload = {"entities": [{"entity_name": "X"}]}
    m = run_kb(spec(objects=[{"name": "e", "each": "$.entities[*]", "id": "$.entity_name",
                              "label": "$.entity_name", "type": "person",
                              "type_path": "$.entity_type"}]), payload=payload)
    assert m.objects[0].type == "person"


def test_aggregate_preview_puts_first_items_on_canvas():
    payload = {"entities": [{"entity_name": f"E{i}", "entity_type": "Person"}
                            for i in range(30)]}
    m = run_kb(spec(objects=[{"name": "e", "each": "$.entities[*]", "id": "$.entity_name",
                              "label": "$.entity_name", "type": "other",
                              "type_path": "$.entity_type"}]),
               payload=payload, threshold=25, preview=5)
    assert [o.label for o in m.objects] == ["E0", "E1", "E2", "E3", "E4"]
    (agg,) = m.aggregates
    assert agg.count == 30 and agg.item_type == "person" and agg.label == "person · 30"


def test_relation_each_pointing_at_the_list_is_expanded():
    s = spec(objects=[{"name": "e", "each": "$.entities[*]", "id": "$.entity_name",
                       "label": "$.entity_name", "type": "other"}],
             relations=[{"each": "$.entities", "from_id": "$args.query",
                         "to_id": "$.entity_name", "kind": "связан"}])
    m = materialize(s, KB_ENTITIES, namespace="kb", call_id="c1", vocabulary=VOCAB_ALL,
                    aggregate_threshold=25, args={"query": "Росатом"},
                    known_keys={"kb:Росатом"})
    assert len(m.relations) == 4
