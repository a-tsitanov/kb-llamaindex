import pytest

from src.lens.paths import PathError, iter_path, join, parse, resolve

DATA = {
    "results": [
        {"id": "Q1", "name": "Росатом", "tags": ["a", "b"]},
        {"id": "Q2", "name": "Си Цзиньпин"},
    ],
    "meta": {"total count": 2},
    "имя": "значение",
}


def test_parse_tokens():
    assert parse("$.results[0].name") == ["results", 0, "name"]
    assert parse('$["total count"]') == ["total count"]


def test_parse_rejects_missing_root():
    with pytest.raises(PathError):
        parse("results[0]")


def test_parse_rejects_garbage():
    with pytest.raises(PathError):
        parse("$.a[x]")


def test_star_expands_with_concrete_paths():
    got = iter_path(DATA, "$.results[*].id")
    assert got == [("$.results[0].id", "Q1"), ("$.results[1].id", "Q2")]


def test_missing_key_yields_empty():
    assert iter_path(DATA, "$.results[*].missing") == []
    assert iter_path(DATA, "$.results[9]") == []


def test_negative_index_is_normalized():
    assert iter_path(DATA, "$.results[-1].id") == [("$.results[1].id", "Q2")]


def test_unicode_and_quoted_keys():
    assert resolve(DATA, "$.имя") == "значение"
    assert resolve(DATA, "$.meta['total count']") == 2
    assert iter_path(DATA, '$.meta["total count"]')[0][0] == '$.meta["total count"]'


def test_star_over_dict_values():
    assert [v for _, v in iter_path({"a": 1, "b": 2}, "$[*]")] == [1, 2]


def test_resolve_requires_single_match():
    with pytest.raises(PathError):
        resolve(DATA, "$.results[*].id")
    with pytest.raises(PathError):
        resolve(DATA, "$.nope")


def test_join():
    assert join("$.results[0]", "$.name") == "$.results[0].name"
    assert join("$.results[0]", "$") == "$.results[0]"
