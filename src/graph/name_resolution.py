"""KB name resolution: a name as a user or a model wrote it → the canonical graph entity.

The graph identifies an entity by its exact name (VID = blake2b(name)), and ER merges delete
every name but the canonical one («Росатом» → "Rosatom"). Every name-taking tool resolves
through here, and reports what it resolved to (``Resolution.to_dict``) instead of silently
walking from something else.

Cascade, cheap → expensive, stopping at the first step that yields a live entity:

    exact     the name itself is a vertex                      1.00
    casefold  name_norm = norm(q)                              0.97
    alias     entity_alias.alias_norm = norm(q) → canonical    ≤0.95 (confidence)
    translit  name_translit / alias_translit = translit(q)     0.90
    word      q is a word of the name (pg_trgm word_similarity) 0.80·ws
    prefix    name_norm LIKE q%                                0.70
    trigram   name_norm % q                                    0.70·sim

``strict`` stops after translit (exact-lookup tools). Every candidate is re-checked against the
graph (``fetch``: name → props, only for existing vertices), so a dead mirror row or a stale
alias never wins; when the graph cannot be asked, candidates are kept and marked unverified.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from loguru import logger

from src.utils.names import norm_name, translit_key

# name -> props ({label, description, mention_count}) for names that are vertices;
# None when the graph could not be asked
Fetch = Callable[[list[str]], Awaitable[dict[str, dict[str, Any]] | None]]

FLOOR = 0.5  # below: a guess, reported as ambiguous
EPS = 0.05  # top-2 this close (and not an exact-level hit): ambiguous
SURE = 0.9  # exact-level hits: ties are broken by mention count, not reported as ambiguous
DOMINANT = 5.0  # a top candidate this many times more mentioned than the next is not ambiguous


class Lexicon(Protocol):
    async def by_norm(self, norm: str, limit: int) -> list[dict[str, Any]]: ...
    async def by_alias(self, norm: str, limit: int) -> list[dict[str, Any]]: ...
    async def by_translit(self, key: str, limit: int) -> list[dict[str, Any]]: ...
    async def by_word(self, norm: str, limit: int) -> list[dict[str, Any]]: ...
    async def by_prefix(self, norm: str, limit: int) -> list[dict[str, Any]]: ...
    async def by_trigram(self, norm: str, limit: int) -> list[dict[str, Any]]: ...


@dataclass
class Candidate:
    name: str
    score: float
    matched_via: list[str]
    matched_text: str = ""
    label: str = ""
    description: str = ""
    mention_count: int = 0

    def brief(self) -> dict[str, Any]:
        return {"name": self.name, "label": self.label, "matched_via": self.matched_via,
                "matched_text": self.matched_text, "score": round(self.score, 3)}


@dataclass
class Resolution:
    query: str
    chosen: Candidate | None = None
    alternatives: list[Candidate] = field(default_factory=list)
    ambiguous: bool = False
    verified: bool = True  # every candidate was checked against the graph

    @property
    def status(self) -> str:
        if self.chosen is None:
            return "not_found"
        return "ambiguous" if self.ambiguous else "ok"

    @property
    def name(self) -> str | None:
        """The canonical name to act on, or None (not found / ambiguous)."""
        return self.chosen.name if self.chosen and not self.ambiguous else None

    def candidates(self) -> list[Candidate]:
        return ([self.chosen] if self.chosen else []) + self.alternatives

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"query": self.query, "status": self.status,
                               "chosen": self.chosen.brief() if self.chosen else None,
                               "alternatives": [c.brief() for c in self.alternatives],
                               "ambiguous": self.ambiguous}
        if not self.verified:
            out["verified"] = False
        return out


class NameResolver:
    def __init__(self, lexicon: Lexicon, fetch: Fetch):
        self.lexicon, self.fetch = lexicon, fetch

    async def resolve(self, name: str, *, label: str | None = None, k: int = 5,
                      strict: bool = False) -> Resolution:
        raw = " ".join(str(name or "").split())
        norm = norm_name(raw)
        res = Resolution(query=str(name or ""))
        if not norm:
            return res
        cands: dict[str, Candidate] = {}
        props: dict[str, dict[str, Any]] = {}
        dead: set[str] = set()
        verified = True
        pool = max(k * 4, 20)

        def add(rows: list[dict[str, Any]], via: str, score: Callable[[dict], float]) -> None:
            for r in rows:
                n = str(r.get("name") or "")
                if not n:
                    continue
                s = float(score(r))
                c = cands.get(n)
                if c is None:
                    cands[n] = Candidate(
                        n, s, [via], str(r.get("matched_text") or ""),
                        str(r.get("label") or ""), str(r.get("description") or ""),
                        int(r.get("mention_count") or 0))
                else:
                    if via not in c.matched_via:
                        c.matched_via.append(via)
                    if s > c.score:
                        c.score, c.matched_text = s, str(r.get("matched_text") or c.matched_text)

        async def live() -> bool:
            """Check new candidates against the graph; True when a live one exists."""
            nonlocal verified
            new = [n for n in cands if n not in props and n not in dead]
            if new:
                got = await self._fetch(new)
                if got is None:
                    verified = False
                    return bool(cands)
                props.update(got)
                dead.update(n for n in new if n not in got)
            return any(n in props for n in cands) or (not verified and bool(cands))

        got = await self._fetch([raw])
        if got is None:
            verified = False
        elif raw in got:
            props.update(got)
            add([{"name": raw, "matched_text": raw}], "exact", lambda r: 1.0)

        steps: list[tuple[str, Callable[[], Awaitable[list[dict]]], Callable[[dict], float]]] = [
            ("casefold", lambda: self.lexicon.by_norm(norm, pool), lambda r: 0.97),
            ("alias", lambda: self.lexicon.by_alias(norm, pool),
             lambda r: min(0.95, float(r.get("confidence") or 0.0))),
            ("translit", lambda: self.lexicon.by_translit(translit_key(raw), pool),
             lambda r: 0.90 * min(1.0, float(r.get("confidence") or 1.0))),
        ]
        found = bool(cands) and raw in props
        for via, run, score in steps:
            if found:
                break
            add(await self._step(via, run), via, score)
            found = await live()
        if not found and not strict:
            fuzzy = await asyncio.gather(
                self._step("word", lambda: self.lexicon.by_word(norm, pool)),
                self._step("prefix", lambda: self.lexicon.by_prefix(norm, pool)),
                self._step("trigram", lambda: self.lexicon.by_trigram(norm, pool)))
            add(fuzzy[0], "word", lambda r: 0.80 * float(r.get("sim") or 0.0))
            add(fuzzy[1], "prefix", lambda r: 0.70)
            add(fuzzy[2], "trigram", lambda r: 0.70 * float(r.get("sim") or 0.0))
            await live()

        ranked = []
        for n, c in cands.items():
            if verified and n not in props:
                continue  # not a vertex (dead mirror row / stale alias)
            p = props.get(n) or {}
            c.label = str(p.get("label") or c.label)
            c.description = str(p.get("description") or c.description)
            c.mention_count = int(p.get("mention_count") or c.mention_count or 0)
            if label and c.label.casefold() != label.casefold():
                continue
            ranked.append(c)
        ranked.sort(key=lambda c: (-c.score, -math.log1p(c.mention_count)))
        res.verified = verified
        if not ranked:
            return res
        res.chosen, res.alternatives = ranked[0], ranked[1:k]
        res.ambiguous = _ambiguous(ranked)
        return res

    async def _fetch(self, names: list[str]) -> dict[str, dict[str, Any]] | None:
        try:
            return await self.fetch(names)
        except Exception as exc:
            logger.warning("name resolution: graph fetch failed: {e}", e=repr(exc))
            return None

    @staticmethod
    async def _step(via: str, run: Callable[[], Awaitable[list[dict]]]) -> list[dict]:
        try:
            return list(await run())
        except Exception as exc:  # a failed step narrows the search, never breaks the tool
            logger.warning("name resolution: {v} step failed: {e}", v=via, e=repr(exc))
            return []


def _ambiguous(ranked: list[Candidate]) -> bool:
    top = ranked[0]
    if top.score < FLOOR:
        return True
    if len(ranked) < 2 or top.score >= SURE:
        return False
    second = ranked[1]
    if top.score - second.score > EPS:
        return False
    return top.mention_count < DOMINANT * max(second.mention_count, 1)


def nebula_fetch(store: Any) -> Fetch:
    """``Fetch`` over a NebulaGraphStore: FETCH PROP of the names' VIDs, in batches."""
    from src.graph.nebula_store import _q, entity_vid

    def run(names: list[str]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        uniq = list(dict.fromkeys(n for n in names if n))
        for i in range(0, len(uniq), 500):
            listed = ", ".join(_q(entity_vid(n)) for n in uniq[i:i + 500])
            rows = store.structured_query(
                f"FETCH PROP ON `Entity` {listed} YIELD `Entity`.name AS name, "
                "`Entity`.label AS label, `Entity`.description AS description, "
                "`Entity`.mention_count AS mention_count;")
            for r in rows or []:
                if r.get("name"):
                    out[r["name"]] = r
        return out

    async def fetch(names: list[str]) -> dict[str, dict[str, Any]]:
        return await asyncio.to_thread(run, names)

    return fetch


__all__ = ["Candidate", "NameResolver", "Resolution", "nebula_fetch"]
