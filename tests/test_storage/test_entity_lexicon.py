from src.storage import entity_lexicon as lx


def test_queries_filter_dead_rows_and_escape_prefix():
    sql, params = lx.q_prefix("50%_off", 5)
    assert "name_norm LIKE %s" in sql and "alive IS NOT FALSE" in sql
    assert params == ["50\\%\\_off%", 5]
    sql, params = lx.q_word("лихачев", 20)
    assert "%s <%% name_norm" in sql and params == ["лихачев", "лихачев", 20]
    sql, params = lx.q_trigram("росатом", 20)
    assert "name_norm %% %s" in sql and params == ["росатом", "росатом", 20]


def test_alias_and_translit_read_the_alias_table():
    sql, params = lx.q_alias("гк росатом", 5)
    assert "FROM entity_alias WHERE alias_norm = %s" in sql and params == ["гк росатом", 5]
    sql, params = lx.q_translit("rosatom", 5)
    assert "name_translit = %s" in sql and "alias_translit = %s" in sql
    assert params == ["rosatom", 5, "rosatom", 5]
    assert lx.q_norm("росатом", 3)[1] == ["росатом", 3]
