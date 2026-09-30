"""Row matching of board writes against stored source results, on real recorded runs."""
import json
from pathlib import Path

from src.lens_agent.rows import entity_rows, match_entity, match_relation, nearest, relation_rows

FIX = Path(__file__).parents[1] / "fixtures" / "lens_eval"


def load(name):
    return json.loads((FIX / f"{name}.json").read_text())


def test_entity_rows_read_kb_entities_not_relations_or_chunks():
    p = load("likhachev_gemma")["calls"]["c1"]["payload"]
    rows = entity_rows(p)
    lik = next(r for r in rows if r.label == "Алексей Лихачёв")
    assert lik.id == "Алексей Лихачёв" and lik.type == "Person"
    assert "росатом" in lik.description.lower()
    assert len(rows) == len(p["entities"])  # relation rows are not entities
    assert entity_rows([{"chunk_id": "x", "text": "t"}]) == []


def test_match_by_id_or_label_normalized_and_by_row_number():
    rows = entity_rows(load("likhachev_gemma")["calls"]["c1"]["payload"])
    assert match_entity(rows, {"id": "алексей лихачев"}).id == "Алексей Лихачёв"
    assert match_entity(rows, {"id": "x", "label": "Алексей Лихачёв"}).id == "Алексей Лихачёв"
    assert match_entity(rows, {"row": 0}).id == rows[0].id
    assert match_entity(rows, {"row": 10_000}) is None


def test_recorded_garbage_writes_do_not_match():
    d = load("rosatom_people")
    rows = entity_rows(d["calls"]["c1"]["payload"])
    first, second = d["writes"][0]["args"]["objects"], d["writes"][2]["args"]["objects"]
    # ids "c1" / "entity_name" with real labels: the labels exist, so they match by label …
    assert match_entity(rows, first[0]).label == "Бизнесмены"
    # … but the glued label "Военный ТЦК/Одесский ТЦКшник" is no row
    glued = next(o for o in second if "/" in o["label"])
    assert match_entity(rows, glued) is None
    # the nearest rows are exactly the two entities the model glued together
    assert {r.label for r in nearest(rows, glued, 2)} == {"Военный ТЦК", "Одесский ТЦКшник"}


def test_invented_id_without_matching_label_is_rejected():
    rows = entity_rows(load("likhachev_gemma")["calls"]["c1"]["payload"])
    assert match_entity(rows, {"id": "likhachev", "label": "Глава Росатома Лихачёв"}) is None


def test_relation_rows_and_matching_either_direction():
    p = load("likhachev_gemma")["calls"]["c1"]["payload"]
    rels = relation_rows(p)
    assert rels and {"src", "tgt", "kind"} <= set(vars(rels[0]))
    r0 = rels[0]
    hit = match_relation(rels, {r0.tgt.casefold()}, {r0.src.casefold()})
    assert hit is not None and hit.src == r0.src
    assert match_relation(rels, {"никто"}, {"ничто"}) is None
