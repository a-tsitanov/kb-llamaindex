from src.lens.keys import normalize_id
from src.utils.names import norm_name, translit_key


def test_norm_name_is_the_board_key_normalization():
    for raw in ["  ГК «Росатом» ", "Алексей  Лихачёв", "РОСАТОМ", "O'Neil"]:
        assert norm_name(raw) == normalize_id(raw)
    assert norm_name("Алексей Лихачёв") == "алексей лихачев"


def test_translit_key_joins_scripts_and_spellings():
    assert translit_key("Алексей Лихачёв") == translit_key("Alexey Likhachev") == \
        translit_key("Aleksei Lihachev") == "aleksei lihacev"
    assert translit_key("Росатом") == translit_key("Rosatom") == "rosatom"
    assert translit_key("Роснано") == translit_key("RUSNANO".replace("U", "O")) == "rosnano"
    assert translit_key("Щукин") == translit_key("Shchukin") == "shukin"
    assert translit_key("Росатом") != translit_key("Роснано")


def test_stem_ru_strips_one_case_ending():
    from src.utils.names import stem_ru
    assert stem_ru("росатома") == stem_ru("росатомом") == "росатом"
    assert stem_ru("путина") == "путин" and stem_ru("лихачевым") == "лихачев"
    assert stem_ru("алексея лихачева") == "алексе лихачев"
    assert stem_ru("роснано") == "роснано" and stem_ru("rosatom") == "rosatom"
    assert stem_ru("мира") == "мира"  # stems shorter than 4 are not cut


def test_inflects_requires_the_name_plus_an_ending():
    from src.utils.names import inflects
    assert inflects("росатомом", "Rosatom") and inflects("Росатома", "Росатом")
    assert inflects("Алексея Лихачёва", "Алексей Лихачёв") and inflects("путина", "Путин")
    assert not inflects("ростатом", "Росстат")  # a typo, not «Росстат» + ending
    assert not inflects("росатом", "Роснано") and not inflects("лихачев", "Алексей Лихачёв")
