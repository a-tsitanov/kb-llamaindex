"""Russian person-name forms for the deterministic ER rule."""
from __future__ import annotations

import pytest

from src.graph.person_names import (
    birth_year,
    different_persons,
    parse_person_name,
    same_person,
)


def _same(a: str, b: str, ya: str | None = None, yb: str | None = None) -> bool:
    return same_person(parse_person_name(a), parse_person_name(b), year_a=ya, year_b=yb)


def _diff(a: str, b: str) -> bool:
    return different_persons(parse_person_name(a), parse_person_name(b))


@pytest.mark.parametrize("name,surname,fi,pi,sex", [
    ("Поляков", "поляков", None, None, "M"),
    ("Поляков С.Н.", "поляков", "с", "н", "M"),
    ("Поляков С. Н.", "поляков", "с", "н", "M"),
    ("С.Н. Поляков", "поляков", "с", "н", "M"),
    ("Поляков Сергей Николаевич", "поляков", "с", "н", "M"),
    ("Сергей Николаевич Поляков", "поляков", "с", "н", "M"),
    ("Полякова Анна Сергеевна", "полякова", "а", "с", "F"),
    ("Иван Иванов", "иванов", "и", None, "M"),
    ("Иванов Иван", "иванов", "и", None, "M"),
])
def test_parse_forms(name, surname, fi, pi, sex):
    p = parse_person_name(name)
    assert p is not None
    assert (p.surname, p.first_initial, p.patronymic_initial, p.sex) == (surname, fi, pi, sex)


@pytest.mark.parametrize("name", [
    "Свидетель Иванов",          # a role, not a first name
    "Гражданка Петрова",
    "Неустановленное лицо",
    "ООО «Каскад»",
    "Иван Петрович",             # first name + patronymic, no surname
    "Марина Иванова",            # both words look like surnames
    "Иванов И.И. и Петров П.П.",
    "",
])
def test_unparseable_forms_are_left_to_the_judge(name):
    assert parse_person_name(name) is None


@pytest.mark.parametrize("a,b", [
    ("Поляков С.Н.", "Поляков Сергей Николаевич"),
    ("С.Н. Поляков", "Сергей Николаевич Поляков"),
    ("Поляков", "Поляков С.Н."),
    ("Акимова И.Е.", "Акимов Иван Евгеньевич"),          # genitive of the short form
    ("Акимов Иван Евгеньевич", "Акимову Ивану Евгеньевичу"),
    ("Михеев Иван Иванович", "Михеевым Иваном Ивановичем"),
    ("Климовой Яны Викторовны", "Я.В. Климова"),
    ("Артемьев Геннадий Фёдорович", "Артемьева Геннадия Федоровича"),
    ("Чайковский П.И.", "Чайковского Петра Ильича"),
])
def test_forms_of_one_person_match(a, b):
    assert _same(a, b)
    assert not _diff(a, b)


@pytest.mark.parametrize("a,b", [
    ("Елисеев С.Н.", "Елисеев А.Л."),                      # initials
    ("Сазонов Сергей Николаевич", "Сазонов А.М."),
    ("Соколов Семён Степанович", "Соколов Сергей Сергеевич"),
    ("Горбунов Николай Павлович", "Горбунов Николай Петрович"),  # patronymic
    ("Пестов Никита Олегович", "Пестова Кристина Андреевна"),    # sex
    ("Зотова Ярослава Степановича", "Зотова Алина Петровна"),
    ("Русаков В.В.", "Русакова Светлана Петровна"),
    ("Иванов И.И.", "Петров И.И."),                         # surname
])
def test_different_persons_are_vetoed(a, b):
    assert not _same(a, b)
    assert _diff(a, b)


def test_bare_surname_in_another_form_is_undecided():
    """"Медведева" may be the genitive of Медведев or his wife — neither
    merged by the rule nor vetoed."""
    assert not _same("Медведева", "Медведев Е.В.")
    assert not _diff("Медведева", "Медведев Е.В.")


def test_birth_year_splits_namesakes():
    assert not _same("Соколов С.С.", "Соколов Сергей Сергеевич", "2004", "1976")
    assert _same("Соколов С.С.", "Соколов Сергей Сергеевич", "1976", "1976")


@pytest.mark.parametrize("desc,year", [
    ("2004 г.р.", "2004"),
    ("13.08.2004 года рождения", "2004"),
    ("дата рождения 20.08.1976", "1976"),
    ("родился 5 мая 1981 года в Подольске", "1981"),
    ("задержан 12.03.2024", None),
    ("", None),
])
def test_birth_year(desc, year):
    assert birth_year(desc) == year


def test_completeness_ranks_full_name_over_initials_over_surname():
    full = parse_person_name("Поляков Сергей Николаевич")
    short = parse_person_name("Поляков С.Н.")
    bare = parse_person_name("Поляков")
    assert full.completeness > short.completeness > bare.completeness
    assert full.nominative and not parse_person_name("Полякова Сергея Николаевича").nominative
