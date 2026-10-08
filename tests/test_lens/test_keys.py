from src.lens.keys import (
    make_key,
    match_labels,
    normalize_id,
    normalize_kind,
    normalize_type,
)


def test_normalize_id_case_yo_quotes_spaces():
    assert normalize_id("  Росатом  ") == "росатом"
    assert normalize_id("РОСАТОМ") == "росатом"
    assert normalize_id("Лихачёв") == normalize_id("Лихачев") == "лихачев"
    assert normalize_id("ГК «Росатом»") == "гк росатом"
    assert normalize_id("Росатом\n Квантовые   технологии") == "росатом квантовые технологии"
    assert normalize_id("„Росатом”") == normalize_id("“Росатом”") == "росатом"


def test_make_key():
    assert make_key("kb", " Росатом ") == "kb:росатом"


def test_normalize_type():
    assert normalize_type("Organization") == "organization"
    assert normalize_type("spaceship") == "other"
    assert normalize_type(None) == "other"


def test_normalize_kind_vocab_aliases_and_free_text():
    assert normalize_kind("участник") == ("участник", None)
    assert normalize_kind("PARTICIPATED_IN") == ("участник", None)
    assert normalize_kind("works at") == ("работает_в", None)
    assert normalize_kind("REGULATION") == ("related", "REGULATION")
    assert normalize_kind("") == ("related", None)
    assert normalize_kind(None) == ("related", None)


def test_match_labels_exact_stem_no_substring():
    labels = {"kb:1": "Си Цзиньпин", "kb:2": "Россия", "kb:3": "Путин В."}
    assert match_labels("си цзиньпин", labels) == ["kb:1"]
    assert match_labels("Си", labels) == ["kb:1"]
    assert match_labels("Путина", labels) == ["kb:3"]
    assert match_labels("Байден", labels) == []
    assert match_labels("  ", labels) == []


def test_source_types_map_to_the_board_vocabulary():
    from src.lens.keys import normalize_type
    assert normalize_type("EventOrAction") == "event" and normalize_type("Concept") == "topic"
    assert normalize_type("Person") == "person" and normalize_type("Country") == "location"
    assert normalize_type("Role") == "other" and normalize_type(None) == "other"
