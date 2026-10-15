import json

from scripts.backfill_entity_names import plan_aliases, verdict_names
from scripts.setup_db import _ENTITY_RESOLUTION_DDL


def key(a, b):
    return json.dumps([[a, "Organization"], [b, "Organization"]], ensure_ascii=False)


def test_verdict_names_parses_er_keys():
    assert verdict_names(key("Rosatom", "Росатом")) == ("Rosatom", "Росатом")
    assert verdict_names("not json") is None and verdict_names(key("X", "X")) is None


ALIVE = {"Rosatom": 221, "Алексей Лихачёв": 47, "ФРС": 90, "Fomc": 5, "Роснано": 12}
DEAD = {"Росатом", "ГК «Росатом", "Лихачев", "Likhachev", "Бывший"}


def test_dead_names_get_their_live_partner_directly_or_through_a_chain():
    pairs = [("Rosatom", "Росатом"), ("Росатом", "ГК «Росатом"),  # chain via a dead name
             ("Likhachev", "Алексей Лихачёв"), ("Лихачев", "Likhachev"),
             ("Fomc", "ФРС")]  # noisy verdict between two living entities: ignored
    plan = {p["alias"]: (p["canonical"], p["hops"]) for p in plan_aliases(pairs, ALIVE, DEAD)}
    assert plan == {"Росатом": ("Rosatom", 1), "ГК «Росатом": ("Rosatom", 2),
                    "Likhachev": ("Алексей Лихачёв", 1), "Лихачев": ("Алексей Лихачёв", 2)}


def test_most_mentioned_partner_wins_and_case_variants_are_skipped():
    pairs = [("Бывший", "Роснано"), ("Бывший", "Rosatom")]
    (p,) = plan_aliases(pairs, ALIVE, {"Бывший"})
    assert p["canonical"] == "Rosatom"
    # a dead «РОСНАНО» already resolves by casefold to the live «Роснано»: no alias needed
    assert plan_aliases([("РОСНАНО", "Rosatom")], ALIVE, {"РОСНАНО"}) == []


def test_resolution_ddl_is_idempotent():
    assert "ADD COLUMN IF NOT EXISTS name_norm" in _ENTITY_RESOLUTION_DDL
    assert "CREATE TABLE IF NOT EXISTS entity_alias" in _ENTITY_RESOLUTION_DDL
    statements = [x for x in _ENTITY_RESOLUTION_DDL.split(";") if x.strip()]
    assert all("IF NOT EXISTS" in x for x in statements)
