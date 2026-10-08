from src.lens_agent.prompt import similar_objects, user_prompt

OBJECTS = [
    {"key": "kb:1", "label": "Росатом", "type": "organization"},
    {"key": "kb:2", "label": "Госкорпорация «Росатом»", "type": "organization"},
    {"key": "kb:3", "label": "Росстат", "type": "organization"},
    {"key": "kb:4", "label": "Лихачёв Алексей", "type": "person"},
]


def test_similar_objects_tolerates_typos_and_word_order():
    keys = [o["key"] for o in similar_objects("ростатом", OBJECTS)]
    assert keys[:2] == ["kb:1", "kb:2"] and "kb:3" not in keys and "kb:4" not in keys
    assert [o["key"] for o in similar_objects("лихачев", OBJECTS)] == ["kb:4"]
    assert similar_objects("Байден", OBJECTS) == []
    assert similar_objects("  ", OBJECTS) == []


def test_user_prompt_lists_similar_objects():
    p = user_prompt("ростатом", [], similar=OBJECTS[:1])
    assert p.startswith("ростатом") and "Похожие объекты на доске" in p
    assert "- kb:1 — Росатом (organization)" in p
    assert user_prompt("x", []) == "x"


def test_a_shared_common_word_is_not_a_match():
    docs = [{"key": "kb:d", "label": "Договор поставки №445 между ООО Ромашка и АО Восток",
             "type": "document"}]
    assert similar_objects("покажи договор с Ивановым", docs) == []
    assert similar_objects("кто руководит Росатомом", OBJECTS)[0]["key"] == "kb:1"
