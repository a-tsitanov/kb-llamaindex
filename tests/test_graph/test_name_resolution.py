"""Name resolution cascade over a fake mirror + graph built from live facts (2026-09-30):
«Росатом» / «Лихачев» are dead mirror rows (ER merged them away), the vertices are "Rosatom"
and «Алексей Лихачёв»."""
import difflib

import pytest

from src.graph.name_resolution import NameResolver
from src.utils.names import norm_name, translit_key

GRAPH = {  # live vertices
    "Rosatom": {"label": "Organization", "description": "госкорпорация", "mention_count": 221},
    "Алексей Лихачёв": {"label": "Person", "description": "глава Росатома", "mention_count": 47},
    "Лихачев Виктор": {"label": "Person", "description": "", "mention_count": 2},
    "Российский суд": {"label": "Organization", "description": "", "mention_count": 30},
    "Роснано": {"label": "Organization", "description": "", "mention_count": 12},
    "АО «Роснано": {"label": "Organization", "description": "", "mention_count": 3},
}
MIRROR = [*GRAPH, "Росатом", "Лихачев"]  # + dead rows
ALIASES = []  # (alias, canonical, confidence)


def row(n):
    return {"name": n, "matched_text": n, **{k: v for k, v in GRAPH.get(n, {}).items()}}


class FakeLexicon:
    def __init__(self, fail=()):
        self.fail, self.calls = set(fail), []

    def _log(self, step):
        self.calls.append(step)
        if step in self.fail:
            raise RuntimeError(f"{step} down")

    async def by_norm(self, norm, limit):
        self._log("casefold")
        return [row(n) for n in MIRROR if norm_name(n) == norm]

    async def by_alias(self, norm, limit):
        self._log("alias")
        return [{"name": c, "matched_text": a, "confidence": conf}
                for a, c, conf in ALIASES if norm_name(a) == norm]

    async def by_translit(self, key, limit):
        self._log("translit")
        return [row(n) for n in MIRROR if translit_key(n) == key]

    async def by_word(self, norm, limit):
        self._log("word")
        return [{**row(n), "sim": 1.0} for n in MIRROR
                if norm in norm_name(n).split() and norm != norm_name(n)]

    async def by_prefix(self, norm, limit):
        self._log("prefix")
        return [row(n) for n in MIRROR if norm_name(n).startswith(norm)]

    async def by_trigram(self, norm, limit):
        self._log("trigram")
        out = []
        for n in MIRROR:
            sim = difflib.SequenceMatcher(None, norm, norm_name(n)).ratio()
            if sim > 0.5:
                out.append({**row(n), "sim": sim})
        return out


def fetch_from(graph, fail=False):
    calls = []

    async def fetch(names):
        calls.append(list(names))
        if fail:
            raise RuntimeError("nebula down")
        return {n: {"name": n, **graph[n]} for n in names if n in graph}
    fetch.calls = calls
    return fetch


def resolver(**kw):
    return NameResolver(FakeLexicon(kw.pop("fail", ())), fetch_from(GRAPH, kw.pop("down", False)))


@pytest.fixture(autouse=True)
def _no_aliases():
    ALIASES.clear()


@pytest.mark.asyncio
async def test_exact_vertex_wins_without_touching_the_mirror():
    r = resolver()
    res = await r.resolve("Алексей Лихачёв")
    assert res.status == "ok" and res.name == "Алексей Лихачёв"
    assert res.chosen.matched_via == ["exact"] and r.lexicon.calls == []


@pytest.mark.asyncio
async def test_merged_away_name_resolves_by_translit_not_to_its_dead_row():
    res = await resolver().resolve("Росатом")
    assert res.name == "Rosatom" and res.chosen.matched_via == ["translit"]
    assert res.chosen.label == "Organization" and res.chosen.mention_count == 221


@pytest.mark.asyncio
async def test_alias_beats_translit_and_is_reported():
    ALIASES.append(("ГК «Росатом»", "Rosatom", 0.85))
    r = resolver()
    res = await r.resolve("ГК «Росатом»")
    assert res.name == "Rosatom" and res.chosen.matched_via == ["alias"]
    assert res.chosen.score == 0.85 and res.chosen.matched_text == "ГК «Росатом»"
    assert "translit" not in r.lexicon.calls


@pytest.mark.asyncio
async def test_casefold_and_other_script_spellings():
    assert (await resolver().resolve("РОСАТОМ")).name == "Rosatom"
    assert (await resolver().resolve("Alexey Likhachev")).name == "Алексей Лихачёв"
    assert (await resolver().resolve("алексей лихачев")).name == "Алексей Лихачёв"


@pytest.mark.asyncio
async def test_surname_resolves_to_the_dominant_person_with_alternatives():
    res = await resolver().resolve("Лихачев")
    assert res.status == "ok" and res.name == "Алексей Лихачёв"
    assert res.chosen.matched_via[0] == "word"
    assert [c.name for c in res.alternatives] == ["Лихачев Виктор"]
    assert "Лихачев" not in [c.name for c in res.candidates()]  # the dead row never shows


@pytest.mark.asyncio
async def test_close_candidates_without_a_dominant_one_are_ambiguous():
    GRAPH["Лихачев Виктор"]["mention_count"] = 40
    try:
        res = await resolver().resolve("Лихачев")
    finally:
        GRAPH["Лихачев Виктор"]["mention_count"] = 2
    assert res.status == "ambiguous" and res.name is None
    assert {c.name for c in res.candidates()} == {"Алексей Лихачёв", "Лихачев Виктор"}


@pytest.mark.asyncio
async def test_unknown_name_is_not_found_and_strict_stops_before_fuzzy_steps():
    r = resolver()
    assert (await r.resolve("Газпромнефть")).status == "not_found"
    r = resolver()
    res = await r.resolve("Лихачев", strict=True)
    assert res.status == "not_found" and "word" not in r.lexicon.calls


@pytest.mark.asyncio
async def test_label_filter_and_quote_prefix_names():
    res = await resolver().resolve("Роснано", label="organization")
    assert res.name == "Роснано" and res.chosen.matched_via == ["exact"]
    res = await resolver().resolve("АО «Роснано")
    assert res.name == "АО «Роснано"
    assert (await resolver().resolve("Роснано", label="Person")).status == "not_found"


@pytest.mark.asyncio
async def test_failed_steps_and_a_down_graph_degrade_not_break():
    res = await resolver(fail={"casefold", "alias"}).resolve("Росатом")
    assert res.name == "Rosatom"
    res = await resolver(down=True).resolve("Rosatom")
    assert res.verified is False and res.to_dict()["verified"] is False
    assert res.chosen is not None  # kept, but marked unverified


@pytest.mark.asyncio
async def test_to_dict_shape():
    d = (await resolver().resolve("Росатом")).to_dict()
    assert d["status"] == "ok" and d["chosen"]["name"] == "Rosatom"
    assert d["chosen"]["matched_via"] == ["translit"] and d["query"] == "Росатом"
    assert (await resolver().resolve("  ")).to_dict()["status"] == "not_found"
