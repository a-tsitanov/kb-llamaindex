"""Телеграм-операции над источниками под общей блокировкой.

Свип фидера и инструменты MCP делят ОДИН `TelegramClient`, а одновременные
запросы к MTProto на одной сессии недопустимы, поэтому каждая операция берёт
`asyncio.Lock`, переданный конструктором. Личность канала — `peer_id`; слаг
(`@username`) — изменяемая подпись. Папки агент не создаёт: работает только
с уже существующими.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, NamedTuple

from telethon import utils as tg_utils
from telethon.errors import (
    FloodWaitError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.tl import functions

from src.intake.sources.folders import filter_title


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
    """Папки нет в аккаунте; агент папки не создаёт."""


def _candidate(chat: Any) -> Candidate:
    username = getattr(chat, "username", None)
    return Candidate(
        peer_id=tg_utils.get_peer_id(chat),
        slug=f"@{username}" if username else "",
        title=getattr(chat, "title", "") or "",
        participants=getattr(chat, "participants_count", None),
        public=bool(username),
    )


def _is_public_channel(chat: Any) -> bool:
    return bool(getattr(chat, "username", None)) and hasattr(chat, "access_hash")


def _normalize_handle(handle: str) -> str:
    h = handle.strip()
    for prefix in ("https://", "http://"):
        if h.startswith(prefix):
            h = h[len(prefix):]
    if h.startswith(("t.me/", "telegram.me/")):
        h = h.split("/", 1)[1]
    h = h.split("?", 1)[0].strip("/")
    return h.lstrip("@")


class TelegramOps:
    def __init__(self, client: Any, lock: asyncio.Lock) -> None:
        self._client = client
        self._lock = lock

    @asynccontextmanager
    async def _guard(self) -> AsyncIterator[None]:
        async with self._lock:
            try:
                yield
            except FloodWaitError as exc:
                raise FloodWait(exc.seconds) from exc

    async def search(self, query: str, limit: int) -> list[Candidate]:
        async with self._guard():
            res = await self._client(functions.contacts.SearchRequest(q=query, limit=limit))
        found = [_candidate(c) for c in res.chats if _is_public_channel(c)]
        return found[:limit]

    async def resolve(self, handle: str) -> Candidate | None:
        username = _normalize_handle(handle)
        if not username:
            return None
        async with self._guard():
            try:
                res = await self._client(
                    functions.contacts.ResolveUsernameRequest(username=username)
                )
            except (UsernameNotOccupiedError, UsernameInvalidError):
                return None
        for chat in res.chats:
            if _is_public_channel(chat):
                return _candidate(chat)
        return None

    async def join(self, peer_id: int) -> None:
        async with self._guard():
            entity = await self._client.get_input_entity(peer_id)
            await self._client(functions.channels.JoinChannelRequest(entity))

    async def leave(self, peer_id: int) -> None:
        async with self._guard():
            entity = await self._client.get_input_entity(peer_id)
            await self._client(functions.channels.LeaveChannelRequest(entity))

    async def history(self, peer_id: int, limit: int) -> list:
        async with self._guard():
            entity = await self._client.get_input_entity(peer_id)
            return list(await self._client.get_messages(entity, limit=limit))

    async def folders(self) -> list[str]:
        async with self._guard():
            filters = await self._filters()
        return [t for f in filters if (t := filter_title(f).strip())]

    async def add_to_folder(self, peer_id: int, folder: str) -> None:
        async with self._guard():
            target = await self._find_folder(folder)
            if peer_id in self._member_ids(target):
                return
            entity = await self._client.get_input_entity(peer_id)
            target.include_peers = [*target.include_peers, entity]
            await self._client(
                functions.messages.UpdateDialogFilterRequest(id=target.id, filter=target)
            )

    async def remove_from_folder(self, peer_id: int, folder: str) -> None:
        async with self._guard():
            target = await self._find_folder(folder)
            if peer_id not in self._member_ids(target):
                return
            keep = lambda p: tg_utils.get_peer_id(p) != peer_id  # noqa: E731
            target.include_peers = [p for p in target.include_peers if keep(p)]
            target.pinned_peers = [p for p in target.pinned_peers if keep(p)]
            await self._client(
                functions.messages.UpdateDialogFilterRequest(id=target.id, filter=target)
            )

    # --- под блокировкой вызывающего ---

    async def _filters(self) -> list[Any]:
        res = await self._client(functions.messages.GetDialogFiltersRequest())
        # новые слои отдают обёртку `.filters`, старые — список
        return list(getattr(res, "filters", res))

    async def _find_folder(self, name: str) -> Any:
        wanted = name.strip().casefold()
        for f in await self._filters():
            if filter_title(f).strip().casefold() == wanted and hasattr(f, "include_peers"):
                return f
        raise FolderNotFound(f"папки {name!r} нет в аккаунте; агент папки не создаёт")

    @staticmethod
    def _member_ids(folder: Any) -> set[int]:
        return {
            tg_utils.get_peer_id(p)
            for p in [*folder.include_peers, *folder.pinned_peers]
        }
