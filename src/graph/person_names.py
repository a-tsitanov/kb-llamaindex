"""Russian person-name forms for the deterministic ER rule.

Parses the forms one person takes across documents — "Поляков",
"Поляков С.Н.", "С.Н. Поляков", "Поляков Сергей Николаевич",
"Сергей Николаевич Поляков", the same in oblique cases — into comparable
parts, and decides whether two forms can be the same person.

Pure functions, no I/O. Measured on the gen-v1 ER pair set
(``deploy/offline/loadtest/er_d1``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_WORD = r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?"
_WORD_RE = re.compile(rf"^{_WORD}$")
_INITIALS_RE = re.compile(r"^([А-ЯЁ])\.(?:([А-ЯЁ])\.?)?$")
# "И. О." → "И.О." before splitting on whitespace.
_SPACED_INITIALS_RE = re.compile(r"([А-ЯЁ]\.)\s+(?=[А-ЯЁ]\.)")
# Patronymic stem + case ending: Николаевич/-а/-у/-ем, Николаевна/-ы/-е/-ой.
_PATRONYMIC_RE = re.compile(r"(ович|евич|ич|овн|евн|ичн|иничн)(а|у|ем|ом|ы|е|ой|ою)?$")
_NOMINATIVE_PATRONYMIC_RE = re.compile(r"(вич|ич|вна|чна)$")
# A word that looks like a surname (masculine / feminine, any case).
_SURNAME_SUFFIX_RE = re.compile(
    r"(ов|ев|ёв|ин|ын|ск|цк)(а|у|ым|ом|е|ой|ою|ую|ий|ая|ого|ому|им)?$"
)
_SURNAME_ENDINGS = ("ого", "ому", "ими", "ым", "им", "ой", "ою", "ую", "ом",
                    "ий", "ая", "а", "у", "е", "ы")
_NAME_ENDINGS = ("ого", "ому", "ем", "ей", "ой", "ою", "ым", "ом",
                 "а", "у", "е", "ы", "и", "я", "ю", "й", "ь")
# Unambiguous surname gender by ending (lowercase). -ова/-ева/-ина are both
# the feminine nominative and the masculine genitive, so they say nothing.
_MALE_SURNAME_RE = re.compile(r"(ов|ев|ёв|ин|ын|ский|цкий|ым|ого|ому)$")
_FEMALE_SURNAME_RE = re.compile(r"(овой|евой|ёвой|иной|ыной|ской|цкой|ская|цкая)$")

# "Свидетель Иванов", "Гражданка Петрова": a role, not a first name.
_ROLE_RE = re.compile(r"(тель|ный|ной|щий|мый|вый|ший|ник|ая|ец)$")
_ROLES = frozenset({
    "гражданин", "гражданка", "понятой", "господин", "госпожа", "капитан",
    "майор", "лейтенант", "сержант", "полковник", "инспектор", "директор",
})

_BIRTH_YEAR_RES = (
    re.compile(r"\b((?:19|20)\d\d)\s*г\.?\s*р\b"),
    re.compile(r"\b((?:19|20)\d\d)\s*(?:г\.|года?)?\s*рождения"),
    re.compile(r"\bро(?:жд|дил|дивш)\w*[^;\n]{0,30}?\b((?:19|20)\d\d)\b"),
    re.compile(r"\bр\.\s*(?:\d{1,2}\.\d{1,2}\.)?((?:19|20)\d\d)\b"),
)


def _lower(word: str) -> str:
    return word.lower().replace("ё", "е")


def _strip(word: str, endings: tuple[str, ...], keep: int) -> str:
    for end in endings:
        if word.endswith(end) and len(word) - len(end) >= keep:
            return word[: -len(end)]
    return word


@dataclass(frozen=True)
class PersonName:
    """One parsed name form. Stems are lowercase, `ё` folded to `е`."""

    surname: str                 # surface form, lowercase
    surname_stem: str            # case/gender-free: поляков, чайковск
    first: str | None = None     # full first name, lowercase
    first_initial: str | None = None
    patronymic_root: str | None = None   # николаевич / николаевна -> никола
    patronymic_initial: str | None = None
    sex: str | None = None       # "M" / "F" when the form says so
    nominative: bool = False     # full patronymic in the nominative

    @property
    def bare(self) -> bool:
        return self.first_initial is None

    @property
    def completeness(self) -> int:
        """0 surname only, 2 one initial or a first name, 4 full FIO."""
        score = 0
        if self.first_initial:
            score += 2 if self.first else 1
        if self.patronymic_initial:
            score += 2 if self.patronymic_root else 1
        return score


def _surname_sex(word: str) -> str | None:
    w = _lower(word)
    if _FEMALE_SURNAME_RE.search(w):
        return "F"
    if _MALE_SURNAME_RE.search(w):
        return "M"
    return None


def _is_patronymic(word: str) -> bool:
    return bool(_PATRONYMIC_RE.search(_lower(word)))


def _build(surname: str, first: str | None = None, first_initial: str | None = None,
           patronymic: str | None = None, patronymic_initial: str | None = None) -> PersonName:
    sex = _surname_sex(surname)
    root = None
    nominative = False
    if patronymic:
        p = _lower(patronymic)
        m = _PATRONYMIC_RE.search(p)
        if m:
            root = p[: m.start()]
            sex = "F" if "н" in m.group(1) else "M"
            nominative = bool(_NOMINATIVE_PATRONYMIC_RE.search(p))
        patronymic_initial = p[0]
    if first:
        first_initial = _lower(first)[0]
    return PersonName(
        surname=_lower(surname),
        surname_stem=_strip(_lower(surname), _SURNAME_ENDINGS, keep=3),
        first=_lower(first) if first else None,
        first_initial=_lower(first_initial) if first_initial else None,
        patronymic_root=root,
        patronymic_initial=_lower(patronymic_initial) if patronymic_initial else None,
        sex=sex,
        nominative=nominative,
    )


def parse_person_name(name: str) -> PersonName | None:
    """Parse a Cyrillic person name; None for anything that is not clearly
    a surname with optional first name / patronymic or initials."""
    text = _SPACED_INITIALS_RE.sub(r"\1", (name or "").strip())
    tokens = text.split()
    if not tokens or len(tokens) > 3:
        return None
    initials = [t for t in tokens if _INITIALS_RE.match(t)]
    words = [t for t in tokens if not _INITIALS_RE.match(t)]
    if any(not _WORD_RE.match(w) for w in words):
        return None
    if initials:
        # "Поляков С.Н." / "С.Н. Поляков"
        if len(initials) != 1 or len(words) != 1 or _is_patronymic(words[0]):
            return None
        m = _INITIALS_RE.match(initials[0])
        return _build(words[0], first_initial=m.group(1), patronymic_initial=m.group(2))
    if len(words) == 1:
        if _is_patronymic(words[0]):
            return None
        return _build(words[0])
    if len(words) == 3:
        if _is_patronymic(words[2]):      # Поляков Сергей Николаевич
            return _build(words[0], first=words[1], patronymic=words[2])
        if _is_patronymic(words[1]):      # Сергей Николаевич Поляков
            return _build(words[2], first=words[0], patronymic=words[1])
        return None
    # Two words: "Иван Иванов" or "Иванов Иван" — only when exactly one
    # of them looks like a surname. "Иван Петрович" (no surname) is out.
    if any(_is_patronymic(w) for w in words):
        return None
    looks = [bool(_SURNAME_SUFFIX_RE.search(_lower(w))) for w in words]
    if looks.count(True) != 1:
        return None
    surname, first = (words[0], words[1]) if looks[0] else (words[1], words[0])
    if _lower(first) in _ROLES or _ROLE_RE.search(_lower(first)):
        return None
    return _build(surname, first=first)


def _same_first_name(a: str, b: str) -> bool:
    """Case-tolerant: Иван/Ивана/Иваном, Сергей/Сергея, Яна/Яны."""
    if _strip(a, _NAME_ENDINGS, keep=2) == _strip(b, _NAME_ENDINGS, keep=2):
        return True
    prefix = 0
    while prefix < min(len(a), len(b)) and a[prefix] == b[prefix]:
        prefix += 1
    return prefix >= max(3, min(len(a), len(b)) - 1)


def birth_year(description: str) -> str | None:
    """Birth year stated in an entity description ("1976 г.р.",
    "дата рождения 20.08.1976", "13.08.2004 года рождения")."""
    text = (description or "").lower()
    for rx in _BIRTH_YEAR_RES:
        m = rx.search(text)
        if m:
            return m.group(1)
    return None


def same_person(a: PersonName, b: PersonName, *,
                year_a: str | None = None, year_b: str | None = None) -> bool:
    """True when nothing in the two forms tells the persons apart.

    A bare surname matches only the same surname surface ("Медведев" ↔
    "Медведев Е.В.", not "Медведева"): without initials the case ending is
    the only gender signal left. Whether a match is UNIQUE is the
    caller's business (`person_rule_pairs`).
    """
    if a.surname_stem != b.surname_stem:
        return False
    if (a.bare or b.bare) and a.surname != b.surname:
        return False
    if a.sex and b.sex and a.sex != b.sex:
        return False
    if year_a and year_b and year_a != year_b:
        return False
    for x, y in ((a.first_initial, b.first_initial),
                 (a.patronymic_initial, b.patronymic_initial),
                 (a.patronymic_root, b.patronymic_root)):
        if x and y and x != y:
            return False
    return not (a.first and b.first and not _same_first_name(a.first, b.first))


def different_persons(a: PersonName, b: PersonName, *,
                      year_a: str | None = None, year_b: str | None = None) -> bool:
    """True when the forms prove two different persons — a veto that keeps
    the pair away from cosine auto-merge and the LLM judge. Weaker than
    `not same_person`: a bare surname in another case or gender
    ("Медведева" vs "Медведев Е.В.") is undecided, not different."""
    if a.surname_stem != b.surname_stem:
        return True
    if a.bare or b.bare:
        return False
    return not same_person(a, b, year_a=year_a, year_b=year_b)


__all__ = [
    "PersonName", "birth_year", "different_persons", "parse_person_name", "same_person",
]
