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


def _latin(raw: str) -> str:
    s = "".join(_CYR.get(ch, ch) for ch in norm_name(raw))
    for a, b in _FOLD:
        s = s.replace(a, b)
    return _SPACES.sub(" ", _NON_WORD.sub(" ", s)).strip()


def _romanized(raw: str) -> str:
    """Letter-for-letter romanization: no folds, doubled letters kept."""
    s = "".join(_CYR.get(ch, ch) for ch in norm_name(raw))
    return _SPACES.sub(" ", _NON_WORD.sub(" ", s)).strip()


def short_translit_ok(query: str, name: str) -> bool:
    """A translit-key hit for a short name (≤ 4 letters) must also match letter for letter:
    the folds that join spellings of long names collide on acronyms («США» "ssha" and
    «СЧА» "scha" both fold to "sha"), while «ФСБ» / "FSB" still match."""
    letters = norm_name(query).replace(" ", "")
    return len(letters) > 4 or _romanized(query) == _romanized(name)


def translit_key(raw: str) -> str:
    return _DOUBLE.sub(r"\1", _latin(raw))


def inflects(query: str, name: str) -> bool:
    """Is ``query`` ``name`` with case endings («Росатомом» / "Rosatom", «Алексея Лихачёва» /
    «Алексей Лихачёв»)? Word by word, the query word must start with the name word in a
    common romanization — doubled letters kept, so «ростатом» is not «Росстат» + ending."""
    q, n = _latin(query).split(), _latin(name).split()
    return len(q) == len(n) and all(a.startswith(b[:max(len(b) - 1, 3)]) and len(a) - len(b) <= 3
                                    for a, b in zip(q, n, strict=True))


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


# Russian case endings, longest first: «Росатома» / «Росатомом» → «росатом», «Путина» →
# «путин», «лихачевым» → «лихачев». A crude stemmer on purpose — the resolver re-checks every
# stem hit against the graph and ranks it below an exact hit.
_ENDINGS = ("ями", "ами", "его", "ого", "ему", "ому", "ыми", "ими", "ов", "ев", "ой", "ей",
            "ом", "ем", "ам", "ям", "ах", "ях", "ую", "юю", "ым", "им", "а", "я", "у", "ю",
            "е", "ы", "и")
_CYRILLIC = re.compile(r"[а-яё]")


def stem_ru(norm: str) -> str:
    """Strip one case ending from each Cyrillic word of a ``norm_name`` string (stem ≥ 4)."""
    out = []
    for w in norm.split():
        if _CYRILLIC.search(w) and len(w) > 4:
            for e in _ENDINGS:
                if w.endswith(e) and len(w) - len(e) >= 4:
                    w = w[: -len(e)]
                    break
        out.append(w)
    return " ".join(out)


__all__ = ["inflects", "norm_name", "short_translit_ok", "stem_ru", "strip_legal_form", "translit_key"]
