"""Pure contradiction detection over extracted claims (no I/O).

A ``Claim`` is one atomic assertion about a subject's attribute, attributed to a
source. Claims about the same ``(subject, attribute)`` are compared: if sources
disagree on the value (or on whether it holds), that's a contradiction. The
"consensus" is the value backed by the heaviest support, where a source's weight
is its trust (``trust`` callable, e.g. ``src/analytics/source_trust.trust_for``).
Without a ``trust`` callable every source weighs 1.0 and the weight collapses to
the distinct-source count — the original behaviour.  Every version is kept
either way, so the reader still sees the full disagreement.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass

ASSERTED = "asserted"
NEGATED = "negated"


@dataclass(frozen=True)
class Claim:
    subject: str
    attribute: str
    value: str
    polarity: str = ASSERTED
    doc_id: str = ""
    source: str = ""


TrustFn = Callable[[str], float]


@dataclass(frozen=True)
class Version:
    value: str
    sources: tuple[str, ...]  # distinct sources asserting this value
    count: int                # number of distinct sources
    weight: float = 0.0       # summed source trust; == count when untrusted


@dataclass(frozen=True)
class Contradiction:
    subject: str
    attribute: str
    versions: tuple[Version, ...]  # ranked by trust-weighted support desc
    consensus: str | None          # leading value, or None on a tie
    disputed: bool
    polarity_split: tuple[str, ...] = ()  # values both asserted AND negated


def _versions(claims: list[Claim], trust: TrustFn | None = None) -> list[Version]:
    """Group ASSERTED claims by value → distinct sources, ranked by support.

    Support is the summed trust of the DISTINCT sources backing the value, so
    one credible report outranks three copies of the same rumour.  With no
    ``trust`` callable each source weighs 1.0 and support == distinct count.
    """
    by_value: dict[str, set[str]] = defaultdict(set)
    for c in claims:
        if c.polarity == ASSERTED:
            by_value[c.value].add(c.source)
    weigh = trust or (lambda _src: 1.0)
    versions = [
        Version(
            value=v,
            sources=tuple(sorted(srcs)),
            count=len(srcs),
            weight=sum(weigh(s) for s in srcs),
        )
        for v, srcs in by_value.items()
    ]
    # Heaviest support first; distinct-source count then value as stable tiebreaks.
    versions.sort(key=lambda x: (-x.weight, -x.count, x.value))
    return versions


def _polarity_split(claims: list[Claim]) -> tuple[str, ...]:
    """Values that at least one source ASSERTS and another NEGATES."""
    asserted: dict[str, set[str]] = defaultdict(set)
    negated: dict[str, set[str]] = defaultdict(set)
    for c in claims:
        (asserted if c.polarity == ASSERTED else negated)[c.value].add(c.source)
    split = [v for v in asserted if negated.get(v)]
    return tuple(sorted(split))


def _consensus(versions: list[Version]) -> str | None:
    """Leading value if its support is strictly greater than the runner-up."""
    if not versions:
        return None
    if len(versions) == 1:
        return versions[0].value
    return versions[0].value if versions[0].weight > versions[1].weight else None


def _representative(claims: list[Claim], field: str) -> str:
    """Most common value of ``field`` across the group — a stable label when a
    cluster mixes phrasings ('количество погибших' vs 'число жертв')."""
    counts = Counter(getattr(c, field) for c in claims)
    return counts.most_common(1)[0][0] if counts else ""


def contradiction_for_group(
    group: list[Claim], trust: TrustFn | None = None,
) -> Contradiction | None:
    """Emit a Contradiction for ONE already-grouped set of claims (same fact
    slot), or None if the sources agree. Works for both exact-key groups and
    semantic clusters — the subject/attribute label is the group's most common."""
    versions = _versions(group, trust)
    polarity_split = _polarity_split(group)
    if len(versions) < 2 and not polarity_split:
        return None  # sources agree (one value, no asserted/negated split)
    return Contradiction(
        subject=_representative(group, "subject"),
        attribute=_representative(group, "attribute"),
        versions=tuple(versions),
        consensus=_consensus(versions),
        disputed=True,
        polarity_split=polarity_split,
    )


def detect_contradictions(
    claims: list[Claim], trust: TrustFn | None = None,
) -> list[Contradiction]:
    """Structural pass: group by EXACT ``(subject, attribute)`` and flag groups
    where sources disagree. (Semantic alignment across phrasings is
    ``detect_contradictions_clustered``.)"""
    groups: dict[tuple[str, str], list[Claim]] = defaultdict(list)
    for c in claims:
        groups[(c.subject, c.attribute)].append(c)
    return [c for group in groups.values() if (c := contradiction_for_group(group, trust))]
