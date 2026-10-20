"""Доставка событий наблюдения: отправка, права, потолок, сводка.

Транспорт — ``post_alert`` (один POST, fail-soft). Политика —
``deliver_due``: кому можно, сколько можно и что делать с остатком.

Четыре правила, каждое из которых существует из-за конкретного провала:

* **Адресат на подписке.** Один URL на установку (`MONITOR_WEBHOOK_URL`)
  не мог быть правильным для нескольких подписчиков — именно он делал
  доставку безадресной.
* **Право проверяется перед КАЖДОЙ отправкой.** Доставка идёт сама, не в
  ответ на запрос: ключа в руках нет, есть `owner` подписки. Права могли
  отозвать после подписки, и физическая изоляция таблиц от этого не
  спасает — утечка идёт наружу, через webhook.
* **Дедуп по (подписчик, событие).** Свип перезапускается; подписчик не
  должен получать одно и то же.
* **Потолок в сутки и сводка.** События пишутся ВСЕ (лента полная), но
  пушей не больше N; остаток — одним сообщением. Порог значимости не
  вводится: угадывать «важность» нечем, а потолок решает ту же задачу,
  ничего не теряя.
"""

from __future__ import annotations

from collections import Counter
from itertools import groupby
from typing import Any
from urllib.parse import urlparse

import httpx
from loguru import logger

from src.config import settings
from src.tenancy.api_keys import records_for_owner
from src.tenancy.authz import Action, authorize
from src.tenancy.context import GraphContext

# Сколько имён сущностей показывать в сводке: она должна читаться целиком,
# а не быть вторым потоком событий.
_DIGEST_NAMES = 10


async def post_alert(url: str, payload: dict, *, timeout_s: float = 5.0) -> bool:
    """POST one payload as JSON; True on 2xx, False on any error. Never raises."""
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.post(url, json=payload)
        return 200 <= resp.status_code < 300
    except Exception as exc:
        logger.warning("post_alert failed url={u}: {e}", u=url, e=exc)
        return False


def destination_ok(url: str) -> bool:
    """Схема адресата — только http(s).

    URL приходит от подписчика и уходит в исходящий запрос С СЕРВЕРА.
    Проверка стоит и при записи подписки (MCP), и здесь: строку могли
    поправить прямо в SQL, а «прочитать `file://` и отправить» — не то
    полномочие, которое выдаётся подпиской.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


async def _may_read(owner: str, graph: GraphContext) -> bool:
    """Есть ли у владельца подписки живой ключ, которому можно читать граф.

    Зовётся ``authorize``, а НЕ ``guard``: ``AUTHZ_MODE`` на доставку не
    влияет намеренно.  Режим `log` существует ради окна наблюдения, когда
    отказ пишется в лог, но запрос пропускается; здесь «пропустить»
    означает отправить содержимое графа наружу — то есть совершить ровно
    то, от чего защищаемся.  Пустой список ключей (всё отозвано) —
    отдельный отказ, и он тоже не зависит от режима.
    """
    try:
        records = await records_for_owner(owner)
    except Exception as exc:
        # Не смогли проверить — не отправляем: неизвестное право не
        # считается разрешением.
        logger.warning("watch delivery: не удалось прочитать ключи owner={o}: {e}",
                       o=owner, e=exc)
        return False
    return any(
        authorize(rec, graph.id, graph.tenant_id, Action.READ).allowed
        for rec in records
    )


def _payload(row: dict[str, Any], graph: GraphContext) -> dict[str, Any]:
    doc_id = row.get("doc_id")
    link = settings.monitor.document_link
    return {
        "graph": graph.id,
        "event_id": int(row["id"]),
        "kind": row["kind"],
        "entity": {"vid": row["entity_vid"], "name": row["entity_name"]},
        "doc_id": str(doc_id) if doc_id else None,
        "doc_date": row["doc_date"].isoformat() if row.get("doc_date") else None,
        "why": row.get("why", ""),
        # Провенанс приёма приезжает внутри detail (шаг S3) — ради
        # подписчика он и собирался.
        "detail": row.get("detail") or {},
        "detected_at": (
            row["detected_at"].isoformat() if row.get("detected_at") else None
        ),
        "document_url": link.format(doc_id=doc_id) if doc_id and "{doc_id}" in link else None,
    }


def _digest_payload(
    rows: list[dict[str, Any]], graph: GraphContext, cap: int,
) -> dict[str, Any]:
    """Сводка остатка: чего и сколько не поместилось в потолок.

    Это не второй поток событий, а одно читаемое сообщение: количество по
    видам, несколько имён и окно времени.  Полный список всегда доступен
    в ленте — сводка на неё и указывает.
    """
    names: list[str] = []
    for r in rows:
        if r["entity_name"] not in names:
            names.append(r["entity_name"])
    stamps = sorted(r["detected_at"] for r in rows if r.get("detected_at"))
    return {
        "graph": graph.id,
        "digest": True,
        "suppressed": len(rows),
        "by_kind": dict(Counter(r["kind"] for r in rows)),
        "entities": names[:_DIGEST_NAMES],
        "entities_total": len(names),
        "from": stamps[0].isoformat() if stamps else None,
        "to": stamps[-1].isoformat() if stamps else None,
        "reason": f"daily push limit {cap} reached",
    }


async def deliver_due(
    repo: Any,
    graph: GraphContext,
    *,
    batch: int | None = None,
    max_attempts: int = 3,
    default_limit: int | None = None,
    timeout_s: float | None = None,
) -> dict[str, int]:
    """Отправить всё, что пора, по подпискам ОДНОГО графа.

    Возвращает счётчики: ``delivered``, ``failed``, ``suppressed``,
    ``refused`` (нет права или негодный адресат), ``digests``.

    Повторов внутри одного прохода нет: неудача помечается, и следующий
    проход свипа и есть расписание повтора (``due_deliveries`` вернёт её,
    пока не исчерпаны попытки).  Отдельная очередь ретраев добавила бы
    состояние, которое уже есть в строке.
    """
    batch = batch or settings.monitor.deliver_batch
    timeout_s = timeout_s if timeout_s is not None else settings.monitor.webhook_timeout_s
    if default_limit is None:
        default_limit = settings.monitor.daily_push_limit
    tally = Counter({"delivered": 0, "failed": 0, "suppressed": 0,
                     "refused": 0, "digests": 0})
    rows = await repo.due_deliveries(limit=batch, max_attempts=max_attempts)
    for owner, group in groupby(rows, key=lambda r: r["owner"]):
        items = list(group)
        if not await _may_read(owner, graph):
            # Строки НЕ помечаются: права могут вернуть, и тогда событие
            # уйдёт.  Пометка 'failed' израсходовала бы попытки на отказ,
            # к отправке не относящийся.
            logger.info(
                "watch delivery refused: нет ключа с правом read  owner={o} graph={g} events={n}",
                o=owner, g=graph.id, n=len(items),
            )
            tally["refused"] += len(items)
            continue
        sent_today = await repo.pushes_today(owner)
        row_limit = items[0].get("daily_push_limit")
        cap = int(row_limit) if row_limit is not None else int(default_limit)
        suppressed: list[dict[str, Any]] = []
        url = items[0]["webhook_url"]
        for row in items:
            if not destination_ok(row["webhook_url"]):
                logger.warning(
                    "watch delivery refused: негодный адресат owner={o} url={u}",
                    o=owner, u=row["webhook_url"],
                )
                tally["refused"] += 1
                continue
            if sent_today >= cap:
                suppressed.append(row)
                continue
            ok = await post_alert(row["webhook_url"], _payload(row, graph),
                                  timeout_s=timeout_s)
            if ok:
                sent_today += 1
                tally["delivered"] += 1
                await repo.mark_delivery(owner, row["id"], "delivered")
            else:
                tally["failed"] += 1
                await repo.mark_delivery(owner, row["id"], "failed",
                                         error="webhook refused")
        if suppressed:
            digest_id = await repo.open_digest(owner, len(suppressed))
            ok = await post_alert(url, _digest_payload(suppressed, graph, cap),
                                  timeout_s=timeout_s)
            await repo.close_digest(digest_id, "delivered" if ok else "failed",
                                    "" if ok else "webhook refused")
            # Состояние 'suppressed' ставится и при неудачной сводке:
            # иначе следующий проход отправил бы эти события по одному,
            # то есть потолок обходился бы падением сводки.
            for row in suppressed:
                await repo.mark_delivery(owner, row["id"], "suppressed",
                                         digest_of=digest_id)
            tally["suppressed"] += len(suppressed)
            if ok:
                tally["digests"] += 1
    return dict(tally)


__all__ = ["deliver_due", "destination_ok", "post_alert"]
