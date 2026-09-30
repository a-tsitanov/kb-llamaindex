"""Relevance ranking of graph tool results against a question.

The graph tools return subgraphs in whatever order the store yields them (a 1-hop
neighbourhood of a well-connected person is hundreds of entities), so a caller that reads
the first N — an agent with a truncated tool result — sees arbitrary neighbours. This ranks
entities by relevance to the question in two stages, both optional:

1. ``prefilter`` — cheap dense similarity (embeddings) over every entity, keeping
   ``prefilter_keep`` for the next stage;
2. ``rerank`` — a cross-encoder over what is left (bounded, since it is the slow part).

Scorers are ``async (query, texts) -> scores``. A failing (or too slow, see ``budget_s``)
scorer never breaks the tool: the order it would have produced is simply not applied.
Relations follow their best-ranked endpoint.

Cross-encoder scores are sigmoid probabilities (0..1). Every reranked entity gets a ``match``
bucket (strong ≥ 0.5, weak ≥ 0.1, none) and ``meta`` reports the best score, with a note when
nothing in the result is relevant to the question — a caller must not present an arbitrary
top-N as an answer.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

Scorer = Callable[[str, list[str]], Awaitable[list[float]]]

STRONG, WEAK = 0.5, 0.1
DESC_CHARS = 150  # the cross-encoder is the slow part; a short passage is enough to rank
NOTHING_RELEVANT = ("ничего релевантного вопросу: лучшая оценка {best:.3f} < {weak} — "
                    "порядок почти случайный, не выдавай эти сущности как ответ")


def entity_text(e: dict, context: str = "") -> str:
    name = str(e.get("entity_name") or "")
    etype = str(e.get("entity_type") or "")
    desc = " ".join(str(e.get("description") or "").split())[:DESC_CHARS]
    head = f"{name} ({etype})" if etype else name
    if context:
        head = f"{head} | {context}"
    return f"{head}: {desc}" if desc else head


def match_bucket(score: float) -> str:
    return "strong" if score >= STRONG else "weak" if score >= WEAK else "none"


@dataclass
class GraphRanker:
    prefilter: Scorer | None = None
    rerank: Scorer | None = None
    prefilter_keep: int = 128
    rerank_keep: int = 32
    budget_s: float | None = None  # whole-rank deadline; over it the store order stays

    async def _scores(self, scorer: Scorer, query: str, texts: list[str]) -> list[float] | None:
        try:
            scores = await scorer(query, texts)
        except Exception as exc:  # ranking is best-effort, the tool result stays usable
            logger.warning("graph rank: scorer failed: {e}", e=repr(exc))
            return None
        if len(scores) != len(texts):
            logger.warning("graph rank: scorer returned {n} scores for {m} texts",
                           n=len(scores), m=len(texts))
            return None
        return [float(s) for s in scores]

    async def rank(self, query: str, entities: list[dict], relations: list[dict],
                   texts: list[str] | None = None) -> tuple[list[dict], list[dict]]:
        ents, rels, _ = await self.rank_meta(query, entities, relations, texts)
        return ents, rels

    async def rank_meta(self, query: str, entities: list[dict], relations: list[dict],
                        texts: list[str] | None = None
                        ) -> tuple[list[dict], list[dict], dict[str, Any]]:
        """Like ``rank``, plus ``meta``: ``ranked`` (a scorer's order was applied),
        ``best_relevance`` and ``relevance_note`` (cross-encoder only)."""
        if not query.strip() or not entities:
            return entities, relations, {"ranked": False}
        texts = texts or [entity_text(e) for e in entities]
        order = self._order(query, texts)
        try:
            head, tail, scored = await (asyncio.wait_for(order, self.budget_s)
                                        if self.budget_s else order)
        except TimeoutError:
            logger.warning("graph rank: over the {b}s budget, store order kept", b=self.budget_s)
            return entities, relations, {"ranked": False, "rank_timeout": True}
        ranked = []
        for i in head + tail:
            e = entities[i]
            if i in scored:
                e = {**e, "relevance": round(scored[i], 3), "match": match_bucket(scored[i])}
            ranked.append(e)
        pos = {e.get("entity_name"): n for n, e in enumerate(ranked)}
        far = len(ranked)

        def rel_key(r: dict) -> int:
            return min(pos.get(r.get("src_id"), far), pos.get(r.get("tgt_id"), far))

        meta: dict[str, Any] = {"ranked": bool(scored)
                                or head + tail != list(range(len(entities)))}
        if scored:
            best = max(scored.values())
            meta["best_relevance"] = round(best, 3)
            if best < WEAK:
                meta["relevance_note"] = NOTHING_RELEVANT.format(best=best, weak=WEAK)
        return ranked, sorted(relations, key=rel_key), meta

    async def _order(self, query: str, texts: list[str]
                     ) -> tuple[list[int], list[int], dict[int, float]]:
        order = list(range(len(texts)))
        head, tail = order, []
        # the dense prefilter runs whenever the cross-encoder would not see everything:
        # otherwise it would read the store-order first ``rerank_keep``, not the best ones
        keep = min(self.prefilter_keep, self.rerank_keep) if self.rerank else self.prefilter_keep
        if self.prefilter and len(order) > keep:
            s = await self._scores(self.prefilter, query, texts)
            if s is not None:
                order = sorted(order, key=lambda i: -s[i])
                head, tail = order[:self.prefilter_keep], order[self.prefilter_keep:]
        scored: dict[int, float] = {}
        if self.rerank:
            cand = head[:self.rerank_keep]
            s = await self._scores(self.rerank, query, [texts[i] for i in cand])
            if s is not None:
                scored = dict(zip(cand, s, strict=True))
                cand = sorted(cand, key=lambda i: -scored[i])
                head = cand + head[self.rerank_keep:]
        return head, tail, scored
