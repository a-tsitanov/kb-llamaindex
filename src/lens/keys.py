"""Board keys, vocabularies and label matching (shared by the board and the old router).

Keys are ``namespace:normalized_id``: the same entity written slightly differently
(«Росатом» / « РОСАТОМ » / "ГК «Росатом»" stays different — only case, ё/е, spaces and
quotes are normalized) lands on one object.
"""

from __future__ import annotations

import re

from src.utils.names import norm_name

TYPES = (
    "person", "organization", "event", "location", "document", "topic",
    "ip", "domain", "certificate", "service", "asn", "other",
)

RELATION_KINDS = (
    "участник", "связан", "владеет", "входит_в", "работает_в", "место", "упоминает",
    "related",
)

# Free-text / source-specific kinds → the vocabulary. Keys are normalized (see _kind_key).
_KIND_ALIASES = {
    "participant": "участник", "participated_in": "участник", "participates": "участник",
    "участвовал": "участник", "участвует": "участник",
    "related_to": "связан", "связь": "связан", "linked": "связан",
    "owns": "владеет", "owner": "владеет", "владелец": "владеет",
    "part_of": "входит_в", "member_of": "входит_в", "affiliation": "входит_в",
    "subsidiary": "входит_в", "входит": "входит_в",
    "works_at": "работает_в", "employed_by": "работает_в", "работает": "работает_в",
    "located_in": "место", "location": "место", "place": "место",
    "mentions": "упоминает", "mentioned_in": "упоминает",
}

_SPACES = re.compile(r"\s+")
_WORD = re.compile(r"\w+", re.U)


def normalize_id(raw: str) -> str:
    """casefold, ё→е, quotes dropped, whitespace collapsed and stripped — the KB resolver's
    ``norm_name``, so board keys and name lookups agree."""
    return norm_name(raw)


def make_key(namespace: str, raw_id: str) -> str:
    return f"{namespace}:{normalize_id(raw_id)}"


# Source types → the board vocabulary (KB labels: EventOrAction, Concept, Issue …).
_TYPE_ALIASES = {
    "eventoraction": "event", "event_or_action": "event",
    "concept": "topic", "issue": "topic",
    "company": "organization", "organisation": "organization",
    "country": "location", "city": "location", "geopoliticalentity": "location",
}


def normalize_type(raw: str | None) -> str:
    t = (raw or "").strip().lower()
    t = _TYPE_ALIASES.get(t, t)
    return t if t in TYPES else "other"


def _kind_key(raw: str) -> str:
    return _SPACES.sub("_", str(raw).strip().casefold().replace("ё", "е"))


def normalize_kind(raw: str | None) -> tuple[str, str | None]:
    """→ (vocabulary kind, original text when it was mapped to ``related``)."""
    k = _kind_key(raw or "")
    if k in RELATION_KINDS:
        return k, None
    if k in _KIND_ALIASES:
        return _KIND_ALIASES[k], None
    return "related", ((str(raw).strip() if raw is not None else "") or None)


def stem(word: str) -> str:
    w = word.lower().replace("ё", "е")
    if len(w) > 5:
        return w[:-2]
    if len(w) > 4:
        return w[:-1]
    return w


def words(text: str) -> list[str]:
    return [stem(w) for w in _WORD.findall(text)]


def match_labels(target: str, labels: dict[str, str]) -> list[str]:
    """Keys whose label matches ``target``: exact (case-insensitive) label wins; otherwise
    every target word must match a label word by stem or as a ≥4-char prefix. Never a raw
    substring ("Си" must not hit "Россия")."""
    t = target.strip().lower()
    if not t:
        return []
    exact = [k for k, label in labels.items() if label.lower() == t]
    if exact:
        return exact[:1]
    want = words(t)
    found = []
    for k, label in labels.items():
        have = words(label)
        if want and all(any(h == w or (len(w) >= 4 and h.startswith(w)) for h in have)
                        for w in want):
            found.append(k)
    return found
