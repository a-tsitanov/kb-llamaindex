"""Телеграм-операции над источниками под общей блокировкой.

Свип фидера и инструменты MCP делят ОДИН `TelegramClient`, а одновременные
запросы к MTProto на одной сессии недопустимы, поэтому каждая операция берёт
`asyncio.Lock`, переданный конструктором. Личность канала — `peer_id`; слаг
(`@username`) — изменяемая подпись. Папки агент не создаёт: работает только
с уже существующими.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import cache
from types import SimpleNamespace
from typing import Any, NamedTuple

from src.intake.sources.folders import filter_title


@cache
def _tl() -> SimpleNamespace:
    """Telethon живёт в необязательном extra `tg`: импортируем лениво, чтобы
    модуль грузился и без него (как в `scripts/tg_ingest.py`)."""
    from telethon import utils as tg_utils
    from telethon.errors import (
        FloodWaitError,
        UsernameInvalidError,
        UsernameNotOccupiedError,
    )
    from telethon.tl import functions, types

    return SimpleNamespace(
        tg_utils=tg_utils,
        functions=functions,
        types=types,
        FloodWaitError=FloodWaitError,
        UsernameInvalidError=UsernameInvalidError,
        UsernameNotOccupiedError=UsernameNotOccupiedError,
    )


class Candidate(NamedTuple):
    peer_id: int
    slug: str
    title: str
    participants: int | None
    public: bool


class FloodWait(RuntimeError):
    """Телеграм просит подождать `seconds` секунд до следующего запроса."""

    def __init__(self, seconds: int) -> None:
        super().__init__(f"Telegram FloodWait: подождать {seconds} с")
        self.seconds = seconds


class FolderNotFound(LookupError):
    """Папки нет в аккаунте; агент папки не создаёт.

    Имя папки лежит в `folder`: вызывающий различает «не далась новая папка»
    и «не далась старая» по полю, а не разбором текста.
    """

    def __init__(self, message: str, *, folder: str = "") -> None:
        super().__init__(message)
        self.folder = folder


class FolderNotEditable(FolderNotFound):
    """Папка есть, но это общий список (chatlist): состав не правится."""


def _candidate(chat: Any) -> Candidate:
    username = getattr(chat, "username", None)
    return Candidate(
        peer_id=_tl().tg_utils.get_peer_id(chat),
        slug=f"@{username}" if username else "",
        title=getattr(chat, "title", "") or "",
        participants=getattr(chat, "participants_count", None),
        public=bool(username),
    )


_HANDLE_RE = re.compile(r"[A-Za-z0-9_]+")


def _is_public_channel(chat: Any) -> bool:
    return bool(getattr(chat, "username", None)) and hasattr(chat, "access_hash")


# Первые сегменты, которые слагом канала не являются: приглашение
# (`t.me/joinchat/xyz`, `t.me/+abc`) и служебные ссылки (`t.me/s/foo` —
# веб-предпросмотр, `t.me/c/123/4` — приватный канал по внутреннему id).
# Без этого отбора `resolve` спросил бы у телеграма «joinchat» или «s» и
# вернул бы совершенно другой канал как найденный.
_RESERVED_SEGMENTS = frozenset({"joinchat", "s", "c"})


def _normalize_handle(handle: str) -> str:
    """Слаг канала из любой записи: `foo`, `@foo`, `t.me/foo`, ссылка на
    сообщение `t.me/foo/123`.  Пустая строка — «это не слаг»."""
    h = handle.strip()
    for prefix in ("https://", "http://"):
        if h.startswith(prefix):
            h = h[len(prefix):]
    if h.startswith(("t.me/", "telegram.me/")):
        h = h.split("/", 1)[1]
    h = h.split("?", 1)[0].strip("/")
    # ссылка на сообщение (`foo/123`) ведёт на канал — берём первый сегмент
    first = h.split("/", 1)[0].lstrip("@")
    if first in _RESERVED_SEGMENTS or not _HANDLE_RE.fullmatch(first):
        return ""
    return first


class TelegramOps:
    def __init__(self, client: Any, lock: asyncio.Lock) -> None:
        self._client = client
        self._lock = lock

    @asynccontextmanager
    async def _guard(self) -> AsyncIterator[None]:
        async with self._lock:
            try:
                yield
            except _tl().FloodWaitError as exc:
                raise FloodWait(exc.seconds) from exc

    async def search(self, query: str, limit: int) -> list[Candidate]:
        async with self._guard():
            res = await self._client(_tl().functions.contacts.SearchRequest(q=query, limit=limit))
        found = [_candidate(c) for c in res.chats if _is_public_channel(c)]
        return found[:limit]

    async def resolve(self, handle: str) -> Candidate | None:
        username = _normalize_handle(handle)
        if not username:
            return None
        async with self._guard():
            try:
                res = await self._client(
                    _tl().functions.contacts.ResolveUsernameRequest(username=username)
                )
            except (_tl().UsernameNotOccupiedError, _tl().UsernameInvalidError):
                return None
        for chat in res.chats:
            if _is_public_channel(chat):
                return _candidate(chat)
        return None

    async def join(self, peer_id: int) -> None:
        async with self._guard():
            entity = await self._client.get_input_entity(peer_id)
            await self._client(_tl().functions.channels.JoinChannelRequest(entity))

    async def leave(self, peer_id: int) -> None:
        async with self._guard():
            entity = await self._client.get_input_entity(peer_id)
            await self._client(_tl().functions.channels.LeaveChannelRequest(entity))

    async def history(self, peer_id: int, limit: int) -> list:
        async with self._guard():
            entity = await self._client.get_input_entity(peer_id)
            return list(await self._client.get_messages(entity, limit=limit))

    async def folders(self) -> list[str]:
        async with self._guard():
            filters = await self._filters()
        return [t for f in filters if (t := filter_title(f).strip())]

    async def add_to_folder(self, peer_id: int, folder: str) -> bool:
        """True — состав папки изменён; False — канал в ней уже был."""
        async with self._guard():
            target = await self._find_folder(folder)
            if peer_id in self._member_ids(target):
                return False
            entity = await self._client.get_input_entity(peer_id)
            target.include_peers = [*target.include_peers, entity]
            await self._client(
                _tl().functions.messages.UpdateDialogFilterRequest(id=target.id, filter=target)
            )
            return True

    async def remove_from_folder(self, peer_id: int, folder: str) -> bool:
        """True — канал снят; False — его в папке и не было.

        Разница важна переносу: отменять снятие, которого не было, значит
        положить канал в папку, где он никогда не лежал.
        """
        async with self._guard():
            target = await self._find_folder(folder)
            if peer_id not in self._member_ids(target):
                return False

            def keep(p: Any) -> bool:
                return _tl().tg_utils.get_peer_id(p) != peer_id

            target.include_peers = [p for p in target.include_peers if keep(p)]
            target.pinned_peers = [p for p in target.pinned_peers if keep(p)]
            await self._client(
                _tl().functions.messages.UpdateDialogFilterRequest(id=target.id, filter=target)
            )
            return True

    # --- под блокировкой вызывающего ---

    async def _filters(self) -> list[Any]:
        res = await self._client(_tl().functions.messages.GetDialogFiltersRequest())
        # новые слои отдают обёртку `.filters`, старые — список
        return list(getattr(res, "filters", res))

    async def _find_folder(self, name: str) -> Any:
        wanted = name.strip().casefold()
        for f in await self._filters():
            if filter_title(f).strip().casefold() == wanted and hasattr(f, "include_peers"):
                if isinstance(f, _tl().types.DialogFilterChatlist):
                    raise FolderNotEditable(
                        f"папка {name!r} — общий список (chatlist), "
                        "его нельзя редактировать через UpdateDialogFilterRequest",
                        folder=name,
                    )
                return f
        raise FolderNotFound(
            f"папки {name!r} нет в аккаунте; агент папки не создаёт", folder=name,
        )

    @staticmethod
    def _member_ids(folder: Any) -> set[int]:
        return {
            _tl().tg_utils.get_peer_id(p)
            for p in [*folder.include_peers, *folder.pinned_peers]
        }
