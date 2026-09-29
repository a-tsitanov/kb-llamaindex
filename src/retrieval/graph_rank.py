"""Relevance ranking of graph tool results against a question.

The graph tools return subgraphs in whatever order the store yields them (a 1-hop
neighbourhood of a well-connected person is hundreds of entities), so a caller that reads
the first N — an agent with a truncated tool result — sees arbitrary neighbours. This ranks
entities by relevance to the question in two stages, both optional:

1. ``prefilter`` — cheap dense similarity (embeddings) over every entity, keeping
   ``prefilter_keep`` for the next stage;
2. ``rerank`` — a cross-encoder over what is left (bounded, since it is the slow part).

Scorers are ``async (query, texts) -> scores``. A failing scorer never breaks the tool:
the order it would have produced is simply not applied. Relations follow their best-ranked
endpoint.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from loguru import logger

Scorer = Callable[[str, list[str]], Awaitable[list[float]]]


def entity_text(e: dict) -> str:
    name = str(e.get("entity_name") or "")
    etype = str(e.get("entity_type") or "")
    desc = " ".join(str(e.get("description") or "").split())[:300]
    head = f"{name} ({etype})" if etype else name
    return f"{head}: {desc}" if desc else head


@dataclass
class GraphRanker:
    prefilter: Scorer | None = None
    rerank: Scorer | None = None
    prefilter_keep: int = 128
    rerank_keep: int = 32

    async def _scores(self, scorer: Scorer, query: str, texts: list[str]) -> list[float] | None:
        try:
            scores = await scorer(query, texts)
        except Exception as exc:  # ranking is best-effort, the tool result stays usable
            logger.warning("graph rank: scorer failed: {e}", e=repr(exc))
            return None
        return [float(s) for s in scores] if len(scores) == len(texts) else None

    async def rank(self, query: str, entities: list[dict],
                   relations: list[dict]) -> tuple[list[dict], list[dict]]:
        if not query.strip() or not entities:
            return entities, relations
        texts = [entity_text(e) for e in entities]
        order = list(range(len(entities)))
        head, tail = order, []
        if self.prefilter and len(order) > self.prefilter_keep:
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
        ranked = []
        for i in head + tail:
            e = entities[i]
            ranked.append({**e, "relevance": round(scored[i], 3)} if i in scored else e)
        pos = {e.get("entity_name"): n for n, e in enumerate(ranked)}
        far = len(ranked)

        def rel_key(r: dict) -> int:
            return min(pos.get(r.get("src_id"), far), pos.get(r.get("tgt_id"), far))

        return ranked, sorted(relations, key=rel_key)
