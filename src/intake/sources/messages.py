"""Как сообщение Телеграма становится документом приёма.

Общий код свипа фидера (`scripts/tg_ingest.py`) и бутстрапа новой подписки
(`service.py`): одно и то же сообщение обязано получить одно и то же имя и
те же поля формы, иначе приём увидит его дважды под разными именами.
"""

from __future__ import annotations

from typing import Any


def message_to_doc(msg: Any, channel: str) -> tuple[str, str, str] | None:
    """Telethon-сообщение → (имя файла, текст, document_date) или None, если пусто."""
    text = (getattr(msg, "message", None) or "").strip()
    if not text:
        return None
    filename = f"tg_{channel.lstrip('@')}_{msg.id}.txt"
    document_date = msg.date.date().isoformat()
    return filename, text, document_date


def ingest_form(
    document_date: str,
    *,
    queue: str | None = None,
    group: str = "",
    priority: int | None = None,
    channel: str = "",
    on_duplicate: str = "",
) -> dict[str, str]:
    """Поля формы `POST /ingest`; необязательные уходят только когда заданы."""
    data: dict[str, str] = {"document_date": document_date}
    if queue:
        data["queue"] = queue
    if group:
        data["group"] = group
    if priority is not None:
        data["priority"] = str(priority)
    if channel:
        data["channel"] = channel
    if on_duplicate:
        data["on_duplicate"] = on_duplicate
    return data
