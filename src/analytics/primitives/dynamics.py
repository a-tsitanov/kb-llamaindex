"""Family 4 — temporal dynamics (online, read-only)."""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict

from src.analytics.catalog import Primitive, PrimitiveResult, register
from src.analytics.ids import clamp_top_n
from src.graph.dynamics_graph_ops import build_dynamics_graph_ops


class _Params(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RelationshipTimelineParams(_Params):
    name: str
    rel_type: str | None = None


async def relationship_timeline(
    store: Any | None, *, name: str, rel_type: str | None = None
) -> PrimitiveResult:
    cypher = "dynamics_graph_ops.relationship_timeline"
    params = {"name": name, "rel_type": rel_type}
    if store is None:
        return PrimitiveResult(cypher=cypher, params=params, rows=[])
    rows = await asyncio.to_thread(
        build_dynamics_graph_ops(store).relationship_timeline, name, rel_type
    )
    return PrimitiveResult(cypher=cypher, params=params, rows=rows)


class WhatsChangedParams(_Params):
    date_from: str
    date_to: str
    entity: str | None = None
    top_n: int = 50


def _iso_to_epoch_days(iso: str, *, end: bool = False) -> int | None:
    """ISO bound (``YYYY`` / ``YYYY-MM`` / ``YYYY-MM-DD``) → days since
    1970-01-01. Partial dates snap to the window edge (``end=False`` →
    start of year/month, ``end=True`` → its last day). ``None`` when
    unparseable — callers disable the epoch branch, not the whole query."""
    from datetime import date, timedelta

    s = (iso or "").strip()
    try:
        if len(s) == 4:
            d = date(int(s), 12, 31) if end else date(int(s), 1, 1)
        elif len(s) == 7:
            y, m = int(s[:4]), int(s[5:7])
            d = (
                date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
                if end else date(y, m, 1)
            )
        else:
            d = date.fromisoformat(s)
    except ValueError:
        return None
    return (d - date(1970, 1, 1)).days


async def whats_changed(
    store: Any | None,
    *,
    date_from: str,
    date_to: str,
    entity: str | None = None,
    top_n: int = 50,
) -> PrimitiveResult:
    """Two change axes, one query:

    * ``valid_from``/``valid_to`` — extraction-claimed validity window
      (sparse and only as reliable as extraction) → ``appeared``/``ended``;
    * ``created_at`` (E1 first-seen epoch-days) fallback for relations
      carrying NO validity dates → ``first_seen`` («связь появилась в
      базе»).  Backfill-sentinel rels (created_at=0) never match a real
      window; ``LIKELY_LINK`` predictions are not world changes and are
      excluded outright."""
    top_n = clamp_top_n(top_n, default=50)
    from_epoch = _iso_to_epoch_days(date_from)
    to_epoch = _iso_to_epoch_days(date_to, end=True)
    cypher = "dynamics_graph_ops.whats_changed"
    params = {
        "from": date_from,
        "to": date_to,
        "from_epoch": from_epoch,
        "to_epoch": to_epoch,
        "entity": entity,
        "top_n": top_n,
    }
    if store is None:
        return PrimitiveResult(cypher=cypher, params=params, rows=[])
    rows = await asyncio.to_thread(
        build_dynamics_graph_ops(store).whats_changed,
        date_from, date_to, entity, from_epoch, to_epoch, top_n,
    )
    return PrimitiveResult(cypher=cypher, params=params, rows=rows)


class TopicTrendParams(_Params):
    topic: str
    granularity: str = "month"


TOPIC_TREND_UNSUPPORTED = (
    "topic_trend is not supported on the NebulaGraph backend: it counts "
    "(:Chunk)-[:MENTIONS]-> mentions by chunk date, and chunks are not graph "
    "vertices on NebulaGraph (no nGQL port yet)"
)


async def topic_trend(
    store: Any | None, *, topic: str, granularity: str = "month"
) -> PrimitiveResult:
    """Unsupported on NebulaGraph — raises without querying the store.

    The former Cypher (``MATCH (t:__Entity__ {name:$topic})<-[:MENTIONS]-
    (c:Chunk) ...``) was sent with a non-empty ``param_map``, which
    ``NebulaGraphStore.structured_query`` refuses with ``NotImplementedError``;
    ``run_rows`` re-raises that (it only fail-softs transient errors), so
    ``execute_step`` reported "not supported by the current graph backend".
    Raising the same exception type here keeps that result identical without
    sending Cypher.  No store → empty rows, as ``run_rows`` returned before.
    """
    params = {"topic": topic}
    if store is None:
        return PrimitiveResult(cypher="", params=params, rows=[])
    raise NotImplementedError(TOPIC_TREND_UNSUPPORTED)


class PolarityEvolutionParams(_Params):
    name: str | None = None
    rel_type: str | None = None


async def polarity_evolution(
    store: Any | None, *, name: str | None = None, rel_type: str | None = None
) -> PrimitiveResult:
    cypher = "dynamics_graph_ops.polarity_evolution"
    params = {"name": name, "rel_type": rel_type}
    if store is None:
        return PrimitiveResult(cypher=cypher, params=params, rows=[])
    rows = await asyncio.to_thread(
        build_dynamics_graph_ops(store).polarity_evolution, name, rel_type
    )
    return PrimitiveResult(cypher=cypher, params=params, rows=rows)


class EntityActivityParams(_Params):
    name: str
    granularity: str = "month"


async def entity_activity(
    store: Any | None, *, name: str, granularity: str = "month"
) -> PrimitiveResult:
    res = await topic_trend(store, topic=name, granularity=granularity)
    return PrimitiveResult(cypher=res.cypher, params=res.params, rows=res.rows)


register(
    Primitive(
        "relationship_timeline",
        relationship_timeline,
        RelationshipTimelineParams,
        "How an entity's relations changed over time (by edge valid_from).",
    )
)
register(
    Primitive(
        "whats_changed",
        whats_changed,
        WhatsChangedParams,
        "Relations that appeared or ended in a date window.",
    )
)
register(
    Primitive(
        "topic_trend",
        topic_trend,
        TopicTrendParams,
        "Mention frequency of a topic/entity over time (by chunk date).",
    )
)
register(
    Primitive(
        "polarity_evolution",
        polarity_evolution,
        PolarityEvolutionParams,
        "How affirmed/negated/uncertain shares shifted over time.",
    )
)
register(
    Primitive(
        "entity_activity",
        entity_activity,
        EntityActivityParams,
        "When an entity was active/discussed over time (mention bursts).",
    )
)
