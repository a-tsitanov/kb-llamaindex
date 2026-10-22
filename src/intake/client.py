"""Клиент приёма: один POST и ОДНА политика ответов для всех фидеров.

Фидер — внешняя программа, которая сама приносит документы через
``POST /api/v1/ingest`` (``scripts/tg_ingest.py``, перезаливка корпуса,
загрузчик нагрузочного прогона).  Класса у роли нет и не нужно, но
политика разбора ответов у всех одна, и до этого модуля она была
скопирована трижды — с собственными константами в каждой копии.

Что здесь живёт:

* словарь исходов (``SENT``, ``DUPLICATE``, ``FAILED``) — он же ключи
  счётчиков у ``tg_ingest``;
* правило «какой код что значит»: 2xx принято, 409 тело уже известно
  (это УСПЕХ прохода, а не ошибка), 429 нет места, прочее — сбой;
* отступление на 429 по заголовку ``Retry-After`` с умолчанием и
  потолком.

Чего здесь НЕТ намеренно: курсоров, состояния, счётчиков раунда и
логирования содержимого.  Это дело фидера: он один знает, что считать
прогрессом и что писать в лог.  Загрузчик в ``deploy/offline/`` сюда не
ходит тоже намеренно — он сознательно standalone, его закидывают в
кластер одним файлом; там своя копия, и у неё есть ссылка на этот модуль.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from loguru import logger

SENT = "sent"
DUPLICATE = "duplicate"
FAILED = "failed"

# Отступление на квотный отказ приёма.  Квота отвечает «сейчас нет
# места», а не «сломалось», и различать это обязан клиент: 429 как ошибка
# остановил бы фидер до рассасывания очереди, 429 как успех потерял бы
# документ.
QUOTA_ATTEMPTS = 3
QUOTA_DEFAULT_WAIT_S = 30
# Сервер может назвать срок больше, чем фидеру осмысленно висеть: ждать
# час бессмысленно, следующий проход всё равно повторит документ.
QUOTA_MAX_WAIT_S = 60


@dataclass(frozen=True)
class Result:
    """Исход одной попытки доставить документ в приём.

    ``outcome`` — один из трёх словарных исходов; ``status_code`` 0
    означает, что ответа не было вовсе (сеть, таймаут).  ``detail`` —
    разобранное тело 409, когда приём его отдал: идентификаторы в нём
    раскрываются только ключу с правом чтения, поэтому поле может быть
    пустым и у честного дубля.
    """

    outcome: str
    status_code: int = 0
    detail: dict[str, Any] | None = None
    attempts: int = 1

    @property
    def duplicate_of(self) -> str | None:
        """``doc_id`` владельца тела из 409, если приём его раскрыл."""
        return (self.detail or {}).get("doc_id")


def quota_wait(response: Any) -> int:
    """Сколько ждать по ``Retry-After``, с умолчанием и потолком.

    Заголовок может отсутствовать или прийти HTTP-датой — в обоих случаях
    берётся умолчание: разбирать дату ради клиента, который всё равно
    повторит документ следующим проходом, не стоит.
    """
    raw = getattr(response, "headers", {}) or {}
    try:
        wait = int(raw.get("Retry-After", QUOTA_DEFAULT_WAIT_S))
    except (TypeError, ValueError):
        wait = QUOTA_DEFAULT_WAIT_S
    return max(1, min(wait, QUOTA_MAX_WAIT_S))


def classify(status_code: int) -> str:
    """Код ответа → исход прохода.

    409 — ``DUPLICATE``, и это успех: тело приём уже знает, повторять
    незачем.  429 отдаётся отдельно (``""``), потому что он единственный,
    на котором есть смысл подождать и попробовать снова.
    """
    if 200 <= status_code < 300:
        return SENT
    if status_code == 409:
        return DUPLICATE
    if status_code == 429:
        return ""
    return FAILED


def _detail(response: Any) -> dict[str, Any] | None:
    try:
        body = response.json()
    except Exception:
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    return detail if isinstance(detail, dict) else None


async def post_document(
    http: Any,
    api_base: str,
    api_key: str,
    *,
    filename: str,
    content: bytes,
    content_type: str = "text/plain",
    data: dict[str, str] | None = None,
    graph: str | None = None,
) -> Result:
    """Отдать один документ приёму, отступая на квотный отказ.

    ``http`` — любой асинхронный клиент с ``post(url, headers=, files=,
    data=)`` (httpx в фидерах, фейк в тестах).  Исключения наружу не
    летят: сетевой сбой — такой же исход прохода, как отказ сервера.

    Повторяется ТОЛЬКО 429: 5xx повтором не лечится в пределах одной
    попытки, а 409 вообще не ошибка.  Исчерпав попытки, отдаёт
    ``FAILED`` — решать, двигать ли курсор, будет фидер.
    """
    headers = {"X-API-Key": api_key}
    if graph:
        headers["X-Graph"] = graph
    for attempt in range(1, QUOTA_ATTEMPTS + 1):
        try:
            resp = await http.post(
                f"{api_base}/api/v1/ingest",
                headers=headers,
                files={"file": (filename, content, content_type)},
                data=data or {},
            )
        except Exception as exc:
            logger.warning("ingest post failed file={f}: {e}", f=filename, e=exc)
            return Result(FAILED, 0, None, attempt)
        outcome = classify(resp.status_code)
        if outcome:
            return Result(outcome, resp.status_code, _detail(resp), attempt)
        if attempt == QUOTA_ATTEMPTS:
            logger.warning(
                "ingest quota file={f}: квота графа исчерпана, попыток {n}",
                f=filename, n=QUOTA_ATTEMPTS,
            )
            return Result(FAILED, resp.status_code, _detail(resp), attempt)
        wait = quota_wait(resp)
        logger.info(
            "ingest quota file={f}: ждём {w}s (попытка {a}/{n})",
            f=filename, w=wait, a=attempt, n=QUOTA_ATTEMPTS,
        )
        await asyncio.sleep(wait)
    return Result(FAILED, 429, None, QUOTA_ATTEMPTS)


__all__ = [
    "DUPLICATE",
    "FAILED",
    "QUOTA_ATTEMPTS",
    "QUOTA_DEFAULT_WAIT_S",
    "QUOTA_MAX_WAIT_S",
    "SENT",
    "Result",
    "classify",
    "post_document",
    "quota_wait",
]
