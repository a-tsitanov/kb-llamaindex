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
