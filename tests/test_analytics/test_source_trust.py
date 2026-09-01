"""Source-trust lookup + trust-weighted claim consensus."""

import pytest

from src.analytics.contradictions import Claim, detect_contradictions
from src.analytics.source_trust import trust_for
from src.config import settings


@pytest.fixture
def trust_table(monkeypatch):
    monkeypatch.setattr(settings.signals, "source_trust", {"analytics": 0.9, "news": 0.2})
    monkeypatch.setattr(settings.signals, "source_trust_default", 0.5)


def test_known_group_is_looked_up_case_insensitively(trust_table):
    assert trust_for("Analytics") == pytest.approx(0.9)
    assert trust_for(" news ") == pytest.approx(0.2)


def test_unknown_or_empty_group_gets_the_default(trust_table):
    assert trust_for("telegram") == pytest.approx(0.5)
    assert trust_for("") == pytest.approx(0.5)


def test_out_of_range_trust_is_clamped(monkeypatch):
    monkeypatch.setattr(settings.signals, "source_trust", {"x": 7.0, "y": -1.0})
    assert trust_for("x") == 1.0
    assert trust_for("y") == 0.0


# ── claim consensus ─────────────────────────────────────────────────────────

_CLAIMS = [
    Claim("бюджет", "сумма", "10 млн", source="rumour-a"),
    Claim("бюджет", "сумма", "10 млн", source="rumour-b"),
    Claim("бюджет", "сумма", "12 млн", source="official"),
]


def test_without_trust_the_loudest_value_wins():
    [c] = detect_contradictions(_CLAIMS)
    assert c.consensus == "10 млн"  # two sources beat one


def test_trust_makes_the_credible_source_win():
    trust = {"official": 0.9, "rumour-a": 0.2, "rumour-b": 0.2}.get

    [c] = detect_contradictions(_CLAIMS, lambda s: trust(s, 0.5))

    assert c.consensus == "12 млн"
    assert c.versions[0].value == "12 млн"
    assert c.versions[0].weight == pytest.approx(0.9)
    assert c.versions[1].count == 2, "the disputed version is still reported"
