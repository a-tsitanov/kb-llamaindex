from src.lens_agent.view import render

ENTS = [{"entity_name": f"E{i}", "entity_type": "Person"} for i in range(3)]


def test_unranked_or_irrelevant_results_carry_a_warning():
    text, _ = render("c1", {"rank_timeout": True, "ranked": False, "entities": ENTS}, 2000)
    assert "⚠ порядок строк НЕ по вопросу" in text.splitlines()[1]
    text, _ = render("c1", {"relevance_note": "x", "best_relevance": 0.02, "entities": ENTS},
                     2000)
    assert "⚠ ничего не подходит к вопросу (лучшая оценка 0.02)" in text
    text, _ = render("c1", {"ranked": True, "best_relevance": 0.9, "entities": ENTS}, 2000)
    assert "⚠" not in text
