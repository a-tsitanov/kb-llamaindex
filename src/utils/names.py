"""Entity-name normalization shared by the KB name resolver and the Lens board keys.

``norm_name`` is THE normalization: board keys (``kb:<norm_name(entity_name)>``) and the
resolver's ``name_norm`` / ``alias_norm`` columns use the same function, so a board object and
a KB lookup agree on what "the same name" is. Changing it changes every board key.

``translit_key`` is a coarse cross-script key: Cyrillic is romanized and both scripts are
folded to one skeleton (kh→h, ch→c, y→i, x→ks, doubled letters …), so «Алексей Лихачёв» and
"Alexey Likhachev" share ``aleksei lihacev``. It is a lookup key, never shown.
"""

from __future__ import annotations

import re

_QUOTES = re.compile(r"[«»\"'“”„`]")
_SPACES = re.compile(r"\s+")


def norm_name(raw: str) -> str:
    """casefold, ё→е, quotes dropped, whitespace collapsed and stripped."""
    s = _QUOTES.sub("", str(raw)).casefold().replace("ё", "е")
    return _SPACES.sub(" ", s).strip()


_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "і": "i", "ї": "i", "є": "e", "ґ": "g",
}
# order matters: longest first
_FOLD = (("shch", "sh"), ("sch", "sh"), ("kh", "h"), ("zh", "z"), ("tch", "c"),
         ("ts", "c"), ("tz", "c"), ("ch", "c"), ("ph", "f"), ("x", "ks"), ("w", "v"),
         ("j", "i"), ("y", "i"), ("q", "k"))
_NON_WORD = re.compile(r"[^a-z0-9 ]+")
_DOUBLE = re.compile(r"([a-z])\1+")


def translit_key(raw: str) -> str:
    s = "".join(_CYR.get(ch, ch) for ch in norm_name(raw))
    for a, b in _FOLD:
        s = s.replace(a, b)
    s = _NON_WORD.sub(" ", s)
    s = _DOUBLE.sub(r"\1", s)
    return _SPACES.sub(" ", s).strip()


# Legal-form / generic corporate words around an organization name («ГК «Росатом»», "ПАО
# Газпром", "Rosatom Corp"): the graph usually stores the bare name.
_LEGAL_PHRASES = ("государственная корпорация", "группа компаний")
_LEGAL_WORDS = frozenset({
    "гк", "госкорпорация", "ао", "пао", "оао", "зао", "ооо", "нао", "фгуп", "гуп", "муп",
    "ано", "нко", "компания", "корпорация", "llc", "ltd", "inc", "plc", "corp", "corporation",
    "company", "jsc", "pjsc", "ojsc", "gmbh", "ag",
})


def strip_legal_form(norm: str) -> str:
    """``norm_name`` output without leading / trailing legal-form words; unchanged if nothing
    else would be left."""
    s = norm
    for ph in _LEGAL_PHRASES:
        s = s.replace(ph, " ")
    words = s.split()
    while words and words[0] in _LEGAL_WORDS:
        words = words[1:]
    while words and words[-1] in _LEGAL_WORDS:
        words = words[:-1]
    return " ".join(words) or norm


__all__ = ["norm_name", "strip_legal_form", "translit_key"]
