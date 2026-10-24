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
from datetime import UTC, datetime, timedelta
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


class FolderMembers(set):
    """Явный состав папки (`peer_id`) и признак `by_category`: папка ещё включает
    каналы по категории («все каналы» / «все группы»), которых в наборе нет."""

    def __init__(self, ids=(), *, by_category: bool = False) -> None:
        super().__init__(ids)
        self.by_category = by_category


class Candidate(NamedTuple):
    peer_id: int
    slug: str
    title: str
    participants: int | None
    public: bool


class Discovered(NamedTuple):
    """Канал, найденный по тому, о чём он пишет (а не по названию)."""

    peer_id: int
    slug: str
    title: str
    participants: int | None
    hits: int
    active_days: int
    last_post: str
    verified: bool


class DiscoverResult(NamedTuple):
    candidates: list[Discovered]
    scanned: int
    partial: bool
    wait_seconds: int | None


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

    async def discover(
        self, topic: str, *, limit: int = 10, days: int = 30, scan: int = 300,
        min_hits: int = 2, min_participants: int = 500, enrich: bool = True,
    ) -> DiscoverResult:
        """Каналы, которые ПИШУТ о теме за последние `days` дней.

        Глобальный поиск по сообщениям (только каналы-вещание): сообщения
        группируются по каналу, ранжирование — по числу различных дней с
        упоминаниями (регулярность), затем по числу сообщений и аудитории.
        Окно соблюдается и здесь: сервер `min_date` может проигнорировать, а
        старые посты раздули бы счётчики и съели бюджет `scan`. Одно сообщение
        считается один раз, даже если страницы пересеклись.

        `SearchGlobal` отдаёт каналы «урезанными» (min) — без
        `participants_count`, поэтому порог аудитории по ним не работает.
        `enrich=True` после отбора `limit` каналов добирает аудиторию отдельным
        `GetFullChannelRequest` на каждый (не больше `limit` запросов), затем
        применяет `min_participants` — только к уже ИЗВЕСТНЫМ числам — и
        пересортировывает. Это запрос на кандидата, поэтому его можно отключить
        (`enrich=False`), если важна скорость или лимиты Telegram.

        `FloodWait` наружу не летит: поиск только читает, частичный ответ
        полезен — он отдаётся с `partial=True` и `wait_seconds` (в том числе
        если лимит пришёл при добирании аудитории).
        """
        tl = _tl()
        min_date = datetime.now(UTC) - timedelta(days=days)
        stats: dict[int, dict[str, Any]] = {}
        chats: dict[int, Any] = {}
        counted: set[tuple[int, int]] = set()
        seen = 0
        fetched = 0
        partial = False
        wait: int | None = None
        rate, peer, msg_id = 0, tl.types.InputPeerEmpty(), 0
        while seen < scan:
            request = tl.functions.messages.SearchGlobalRequest(
                q=topic, filter=tl.types.InputMessagesFilterEmpty(),
                min_date=min_date, max_date=None, offset_rate=rate,
                offset_peer=peer, offset_id=msg_id, limit=min(100, scan - seen),
                broadcasts_only=True,
            )
            try:
                async with self._guard():
                    res = await self._client(request)
            except FloodWait as exc:
                partial, wait = True, exc.seconds
                break
            msgs = [m for m in getattr(res, "messages", []) if getattr(m, "date", None)]
            if not msgs:
                break
            fetched += len(msgs)
            for c in getattr(res, "chats", []):
                chats[c.id] = c
            if max(m.date for m in msgs) < min_date:
                break  # вся страница старше окна, дальше только старее
            for m in msgs:
                if seen >= scan:
                    break
                cid = getattr(m.peer_id, "channel_id", None)
                if cid is None or m.date < min_date or (cid, m.id) in counted:
                    continue
                counted.add((cid, m.id))
                st = stats.setdefault(cid, {"hits": 0, "days": set(), "last": None})
                st["hits"] += 1
                day = m.date.astimezone(UTC)
                st["days"].add(day.date())
                if st["last"] is None or day > st["last"]:
                    st["last"] = day
                seen += 1
            tl_msgs = tl.types.messages.MessagesSlice
            if not isinstance(res, tl_msgs) or res.count <= fetched:
                break  # обычный `Messages` или всё выдано: следующей страницы нет
            last = msgs[-1]
            next_rate = getattr(res, "next_rate", None)
            last_cid = getattr(last.peer_id, "channel_id", None)
            holder = chats.get(last_cid)
            next_peer = (
                tl.types.InputPeerChannel(last_cid, holder.access_hash)
                if holder is not None and hasattr(holder, "access_hash")
                else tl.types.InputPeerEmpty()
            )
            nxt = (next_rate if next_rate is not None else rate, next_peer, last.id)
            if nxt[0] == rate and nxt[2] == msg_id and nxt[1] == peer:
                break  # смещения не сдвинулись: страница та же
            rate, peer, msg_id = nxt
        found: list[tuple[Discovered, Any]] = []
        for cid, st in stats.items():
            chat = chats.get(cid)
            if chat is None or not getattr(chat, "broadcast", False):
                continue
            if not getattr(chat, "username", None):
                continue
            if any(getattr(chat, f, False) for f in ("scam", "fake", "restricted")):
                continue
            if st["hits"] < min_hits:
                continue
            found.append((Discovered(
                peer_id=tl.tg_utils.get_peer_id(chat),
                slug=f"@{chat.username}",
                title=getattr(chat, "title", "") or "",
                participants=getattr(chat, "participants_count", None),
                hits=st["hits"],
                active_days=len(st["days"]),
                last_post=st["last"].date().isoformat() if st["last"] else "",
                verified=bool(getattr(chat, "verified", False)),
            ), chat))

        def rank(d: Discovered) -> tuple[int, int, int, int]:
            return (-d.active_days, -d.hits, -(d.participants or 0), d.peer_id)

        found.sort(key=lambda pair: rank(pair[0]))
        top = found[:limit]
        if enrich:
            enriched: list[Discovered] = []
            stop = False
            for d, chat in top:
                if not stop:
                    try:
                        count = await self._participants(chat)
                    except FloodWait as exc:
                        partial, wait, stop = True, exc.seconds, True
                        count = None
                    if count is not None:
                        d = d._replace(participants=count)
                enriched.append(d)
            result = enriched
        else:
            result = [d for d, _ in top]
        result = [
            d for d in result
            if d.participants is None or d.participants >= min_participants
        ]
        result.sort(key=rank)
        return DiscoverResult(result, seen, partial, wait)

    async def _participants(self, chat: Any) -> int | None:
        """Аудитория канала одним `GetFullChannelRequest`; `None` — не вышло
        (приватный, удалён, пустой ответ). `FloodWait` пробрасывается."""
        tl = _tl()
        try:
            async with self._guard():
                full = await self._client(tl.functions.channels.GetFullChannelRequest(
                    tl.types.InputChannel(chat.id, chat.access_hash),
                ))
        except FloodWait:
            raise
        except Exception:  # один сбойный канал не должен ронять весь поиск
            return None
        count = getattr(getattr(full, "full_chat", None), "participants_count", None)
        return count if isinstance(count, int) else None

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

    async def folders_with_members(self) -> dict[str, FolderMembers]:
        """Название папки -> `peer_id` её каналов; фильтры читаются ОДНИМ запросом.

        Папка, собранная по признаку «все каналы» / «все группы», явного
        состава не имеет: её `FolderMembers.by_category` истинно, и отсутствие
        канала в наборе значит «неизвестно», а не «нет».

        Для листинга: по запросу на каждую группу один FloodWait ронял бы весь
        список. Общий список (chatlist) читается как обычная папка.
        """
        async with self._guard():
            filters = await self._filters()
        return {
            t: FolderMembers(
                self._member_ids(f),
                by_category=bool(getattr(f, "broadcasts", False) or getattr(f, "groups", False)),
            )
            for f in filters
            if (t := filter_title(f).strip()) and hasattr(f, "include_peers")
        }

    async def folder_members(self, folder: str) -> set[int]:
        """`peer_id` каналов папки (включённые и закреплённые); только чтение.

        Общий список (chatlist) читается как обычная папка: править его
        нельзя, а видеть состав можно. Нет папки — `FolderNotFound`. Папка
        ищется тем же `_find_folder`, что и при правке: сравнение названий
        живёт в одном месте.
        """
        async with self._guard():
            return self._member_ids(await self._find_folder(folder, writable=False))

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

    async def _find_folder(self, name: str, *, writable: bool = True) -> Any:
        wanted = name.strip().casefold()
        for f in await self._filters():
            if filter_title(f).strip().casefold() == wanted and hasattr(f, "include_peers"):
                if writable and isinstance(f, _tl().types.DialogFilterChatlist):
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
