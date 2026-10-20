"""Temporal-активности наблюдения: свип журналов и рост риска.

Одна дуга наблюдения, а не две (спека
`docs/superpowers/specs/2026-10-20-watch-contour-design.md` §2): подписки
живут в Postgres (`watch`), события — в `watch_event`, и доставка идёт от
них.  Прежняя дуга `:Alert` в Nebula — свой флаг подписки
(`Entity.watched`), свои детекторы и свой глобальный webhook — выведена
целиком: она порождала `new_connection` ВТОРОЙ раз, то есть критерий
«одно уведомление на событие» при ней был недостижим.

Из неё сохранён ровно один детектор — рост риска: предыдущее значение
лежит на узле графа (`risk_score_prev`), журнала у него нет, поэтому
графовое чтение осталось здесь, а решение «это событие» переехало в
чистый `detect_risk_rise` (`src/watch/sweep.py`).

Активность fail-soft по графу: ошибка одного графа логируется и попадает
в `error`, не останавливая остальные.
"""

from __future__ import annotations

import asyncio

from loguru import logger
from temporalio import activity

from src.analytics.contracts import WatchDeliverResult, WatchSweepResult
from src.config import settings
from src.graph.store import build_graph_store
from src.intake.repository import IntakeRepository
from src.tenancy import graph_repo
from src.tenancy.context import GraphContext, default_graph_context
from src.watch.delivery import deliver_due
from src.watch.repository import WatchRepository
from src.watch.sweep import detect_risk_rise, run_watch_sweep
from src.workflow.heartbeat import heartbeat_every

# Сколько наблюдаемых сущностей опрашивать за один FETCH PROP: защита от
# запроса длиной в тысячи vid'ов, а не настройка производительности.
_RISK_BATCH = 200


def _read_risk_scores(store: object, vids: list[str]) -> list[dict]:
    """Текущий и прежний риск у перечисленных сущностей.

    Чтение идёт ПО СПИСКУ подписок, а не по флагу `Entity.watched`:
    флаг — часть выведенной дуги, и опрос по нему возвращал бы сущности,
    на которые никто не подписан, молча расходясь с лентой.
    """
    from src.graph.nebula_store import _q

    rows: list[dict] = []
    for i in range(0, len(vids), _RISK_BATCH):
        chunk = vids[i : i + _RISK_BATCH]
        fetched = store.structured_query(  # type: ignore[attr-defined]
            f"FETCH PROP ON `Entity` {', '.join(_q(v) for v in chunk)} YIELD "
            "id(vertex) AS vid, `Entity`.name AS name, "
            "`Entity`.risk_score AS score, `Entity`.risk_score_prev AS prev"
        ) or []
        rows += [dict(r) for r in fetched]
    return rows


async def _risk_events(repo: WatchRepository, graph: GraphContext,
                       watched: dict[str, str]) -> int:
    """Записать события роста риска для подписок этого графа."""
    if not watched:
        return 0
    store = build_graph_store(graph)
    rows = await asyncio.to_thread(_read_risk_scores, store, list(watched))
    events = detect_risk_rise(rows, watched, delta=settings.monitor.risk_rise_delta)
    if events:
        await repo.insert_events(events)
    return len(events)


async def _watch_graphs() -> list[GraphContext]:
    """`default` + every ready graph; `default` alone if the registry is down."""
    try:
        graphs = await graph_repo.list_ready_contexts()
    except Exception as exc:
        logger.warning("sweep_watch: registry unavailable ({e}); default only", e=exc)
        graphs = []
    if not any(g.is_default for g in graphs):
        graphs.insert(0, default_graph_context())
    return graphs


@activity.defn
async def sweep_watch() -> WatchSweepResult:
    """Свип наблюдения по каждому готовому графу.

    Две части: журналы за своими курсорами (упоминания, связи,
    противоречия) и рост риска по узлам графа.  Обе пишут в ту же
    `watch_event` и дедупятся тем же ключом, поэтому подписчик видит один
    поток, а не два.

    Fail-soft на граф: ошибка одного не останавливает остальные.
    """
    by_kind: dict[str, int] = {}
    errors: list[str] = []
    async with heartbeat_every(30.0, {"stage": "watch"}):
        for graph in await _watch_graphs():
            repo = WatchRepository(graph=graph)
            try:
                # Провенанс спрашивается у реестра приёма — единственное,
                # что наблюдение знает о приёме (arch-тест правила 5).
                provenance = IntakeRepository(graph=graph).provenance_of
                for kind, n in (await run_watch_sweep(repo, provenance=provenance)).items():
                    by_kind[kind] = by_kind.get(kind, 0) + n
                risk = await _risk_events(repo, graph, await repo.watched())
                if risk:
                    by_kind["risk_rise"] = by_kind.get("risk_rise", 0) + risk
            except Exception as exc:
                logger.warning("sweep_watch failed  graph={g}: {e}", g=graph.id, e=exc)
                errors.append(f"{graph.id}: {exc}")
    return WatchSweepResult(events=sum(by_kind.values()), by_kind=by_kind,
                            error="; ".join(errors))


@activity.defn
async def deliver_watch() -> WatchDeliverResult:
    """Разослать события подписчикам — по каждому готовому графу.

    Отдельная активность, а не хвост свипа: доставка ходит в чужие
    адреса, и её таймаут, ретраи и отказы не должны смешиваться с
    обнаружением событий.  Свип без доставки осмыслен (лента работает),
    доставка без свипа безвредна (нечего отправлять).

    Fail-soft на граф, как и свип: чужой упавший webhook не повод
    остановить рассылку остальным.
    """
    tally: dict[str, int] = {}
    errors: list[str] = []
    async with heartbeat_every(30.0, {"stage": "deliver"}):
        for graph in await _watch_graphs():
            try:
                for key, n in (await deliver_due(
                    WatchRepository(graph=graph), graph,
                )).items():
                    tally[key] = tally.get(key, 0) + n
            except Exception as exc:
                logger.warning("deliver_watch failed  graph={g}: {e}", g=graph.id, e=exc)
                errors.append(f"{graph.id}: {exc}")
    return WatchDeliverResult(
        delivered=tally.get("delivered", 0),
        failed=tally.get("failed", 0),
        suppressed=tally.get("suppressed", 0),
        refused=tally.get("refused", 0),
        digests=tally.get("digests", 0),
        error="; ".join(errors),
    )


MONITOR_ACTIVITIES = [sweep_watch, deliver_watch]
