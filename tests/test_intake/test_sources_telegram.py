"""TelegramOps на фейковом клиенте: какой TL-запрос и с чем построен."""

import asyncio

import pytest

pytest.importorskip("telethon")

from telethon import utils as tg_utils
from telethon.errors import FloodWaitError, UsernameNotOccupiedError
from telethon.tl import functions, types

from src.intake.sources.telegram import (
    Candidate,
    FloodWait,
    FolderNotFound,
    TelegramOps,
)


def _chan(cid, username, title="T", participants=10):
    return types.Channel(
        id=cid, title=title, photo=types.ChatPhotoEmpty(), date=None,
        username=username, broadcast=True, access_hash=cid * 7,
        participants_count=participants,
    )


def _inp(cid):
    return types.InputPeerChannel(cid, cid * 7)


def _folder(fid, title, include=(), pinned=()):
    return types.DialogFilter(
        id=fid, title=types.TextWithEntities(title, []),
        pinned_peers=[_inp(c) for c in pinned],
        include_peers=[_inp(c) for c in include], exclude_peers=[],
    )


class _FakeMsg:
    def __init__(self, id):
        self.id = id


class _Client:
    """Фиксирует запросы; ответы задаются по типу запроса."""

    def __init__(self, responses=None):
        self.requests = []
        self.responses = responses or {}
        self.calls = 0

    async def __call__(self, request):
        self.calls += 1
        self.requests.append(request)
        out = self.responses.get(type(request))
        if isinstance(out, Exception):
            raise out
        return out

    async def get_input_entity(self, peer_id):
        self.calls += 1
        return _inp(abs(peer_id) - 1000000000000)

    async def get_messages(self, entity, limit=None):
        self.calls += 1
        out = self.responses.get("messages")
        if isinstance(out, Exception):
            raise out
        return [_FakeMsg(i) for i in range(100, 100 - 1000, -1)][:limit]


def _ops(client=None):
    lock = asyncio.Lock()
    return TelegramOps(client or _Client(), lock), lock


def _pid(cid):
    return tg_utils.get_peer_id(_chan(cid, "x"))


def _search_result(*chats):
    return types.contacts.Found(my_results=[], results=[], chats=list(chats), users=[])


def _resolved(*chats):
    return types.contacts.ResolvedPeer(
        peer=types.PeerChannel(1), chats=list(chats), users=[]
    )


def _flood(seconds=17):
    return FloodWaitError(request=None, capture=seconds)


@pytest.mark.asyncio
async def test_search_only_public_channels_and_limit():
    client = _Client({functions.contacts.SearchRequest: _search_result(
        _chan(1, "a"), _chan(2, None), _chan(3, "c"), _chan(4, "d"),
    )})
    ops, _ = _ops(client)
    found = await ops.search("новости", 2)
    req = client.requests[0]
    assert req.q == "новости" and req.limit == 2
    assert [c.slug for c in found] == ["@a", "@c"]
    assert all(isinstance(c, Candidate) and c.public for c in found)
    assert found[0] == Candidate(_pid(1), "@a", "T", 10, True)


@pytest.mark.parametrize("raw", ["@foo", "foo", "https://t.me/foo", "t.me/foo/", "http://t.me/foo?x=1"])
@pytest.mark.asyncio
async def test_resolve_accepts_handle_forms(raw):
    client = _Client({functions.contacts.ResolveUsernameRequest: _resolved(_chan(5, "foo"))})
    ops, _ = _ops(client)
    cand = await ops.resolve(raw)
    assert client.requests[0].username == "foo"
    assert cand.peer_id == _pid(5) and cand.slug == "@foo"


@pytest.mark.asyncio
async def test_resolve_missing_is_none():
    client = _Client({functions.contacts.ResolveUsernameRequest: UsernameNotOccupiedError(None)})
    ops, _ = _ops(client)
    assert await ops.resolve("@nope") is None


@pytest.mark.asyncio
async def test_resolve_user_is_none():
    client = _Client({functions.contacts.ResolveUsernameRequest: _resolved()})
    ops, _ = _ops(client)
    assert await ops.resolve("someuser") is None


@pytest.mark.asyncio
async def test_join_and_leave_build_channel_requests():
    client = _Client()
    ops, _ = _ops(client)
    pid = _pid(5)
    await ops.join(pid)
    await ops.leave(pid)
    join, leave = client.requests
    assert isinstance(join, functions.channels.JoinChannelRequest)
    assert isinstance(leave, functions.channels.LeaveChannelRequest)
    assert join.channel == _inp(5) and leave.channel == _inp(5)


@pytest.mark.asyncio
async def test_add_to_folder_read_modify_write_keeps_others():
    news = _folder(2, "News", include=[10, 11], pinned=[12])
    other = _folder(3, "Other", include=[99])
    client = _Client({functions.messages.GetDialogFiltersRequest: [types.DialogFilterDefault(), news, other]})
    ops, _ = _ops(client)
    await ops.add_to_folder(_pid(5), "news")
    write = client.requests[-1]
    assert isinstance(write, functions.messages.UpdateDialogFilterRequest)
    assert write.id == 2
    ids = [tg_utils.get_peer_id(p) for p in write.filter.include_peers]
    assert ids == [_pid(10), _pid(11), _pid(5)]
    assert [tg_utils.get_peer_id(p) for p in write.filter.pinned_peers] == [_pid(12)]
    assert sum(isinstance(r, functions.messages.UpdateDialogFilterRequest) for r in client.requests) == 1


@pytest.mark.asyncio
async def test_add_to_folder_already_member_does_not_write():
    client = _Client({functions.messages.GetDialogFiltersRequest: [_folder(2, "news", include=[5])]})
    ops, _ = _ops(client)
    await ops.add_to_folder(_pid(5), "news")
    assert not any(isinstance(r, functions.messages.UpdateDialogFilterRequest) for r in client.requests)


@pytest.mark.asyncio
async def test_add_to_folder_accepts_new_layer_wrapper():
    wrapper = types.messages.DialogFilters(filters=[_folder(2, "news")], tags_enabled=False)
    client = _Client({functions.messages.GetDialogFiltersRequest: wrapper})
    ops, _ = _ops(client)
    await ops.add_to_folder(_pid(5), "news")
    assert client.requests[-1].filter.include_peers == [_inp(5)]


@pytest.mark.asyncio
async def test_add_to_missing_folder_raises_and_never_creates():
    client = _Client({functions.messages.GetDialogFiltersRequest: [_folder(2, "news")]})
    ops, _ = _ops(client)
    with pytest.raises(FolderNotFound):
        await ops.add_to_folder(_pid(5), "digest")
    assert not any(isinstance(r, functions.messages.UpdateDialogFilterRequest) for r in client.requests)


@pytest.mark.asyncio
async def test_remove_from_folder_drops_only_this_peer():
    news = _folder(2, "news", include=[10, 5, 11], pinned=[5, 12])
    client = _Client({functions.messages.GetDialogFiltersRequest: [news]})
    ops, _ = _ops(client)
    await ops.remove_from_folder(_pid(5), "News")
    write = client.requests[-1]
    assert [tg_utils.get_peer_id(p) for p in write.filter.include_peers] == [_pid(10), _pid(11)]
    assert [tg_utils.get_peer_id(p) for p in write.filter.pinned_peers] == [_pid(12)]


@pytest.mark.asyncio
async def test_remove_from_missing_folder_raises():
    client = _Client({functions.messages.GetDialogFiltersRequest: []})
    ops, _ = _ops(client)
    with pytest.raises(FolderNotFound):
        await ops.remove_from_folder(_pid(5), "news")


@pytest.mark.asyncio
async def test_folders_lists_titles_skipping_default():
    client = _Client({functions.messages.GetDialogFiltersRequest: [
        types.DialogFilterDefault(), _folder(2, "news"), _folder(3, "digest")]})
    ops, _ = _ops(client)
    assert await ops.folders() == ["news", "digest"]


@pytest.mark.asyncio
async def test_history_respects_limit_newest_first():
    ops, _ = _ops()
    msgs = await ops.history(_pid(5), 3)
    assert [m.id for m in msgs] == [100, 99, 98]


_FLOOD_RESPONSES = {
    functions.contacts.SearchRequest: _flood(),
    functions.contacts.ResolveUsernameRequest: _flood(),
    functions.channels.JoinChannelRequest: _flood(),
    functions.channels.LeaveChannelRequest: _flood(),
    functions.messages.GetDialogFiltersRequest: _flood(),
    "messages": _flood(),
}

_METHODS = {
    "search": lambda o: o.search("q", 5),
    "resolve": lambda o: o.resolve("foo"),
    "join": lambda o: o.join(_pid(5)),
    "leave": lambda o: o.leave(_pid(5)),
    "folders": lambda o: o.folders(),
    "add_to_folder": lambda o: o.add_to_folder(_pid(5), "news"),
    "remove_from_folder": lambda o: o.remove_from_folder(_pid(5), "news"),
    "history": lambda o: o.history(_pid(5), 10),
}


@pytest.mark.parametrize("name", list(_METHODS))
@pytest.mark.asyncio
async def test_floodwait_surfaces_with_seconds(name):
    ops, _ = _ops(_Client(dict(_FLOOD_RESPONSES)))
    with pytest.raises(FloodWait) as ei:
        await _METHODS[name](ops)
    assert ei.value.seconds == 17


@pytest.mark.parametrize("name", list(_METHODS))
@pytest.mark.asyncio
async def test_every_method_waits_for_the_lock(name):
    client = _Client({
        functions.contacts.SearchRequest: _search_result(),
        functions.contacts.ResolveUsernameRequest: _resolved(),
        functions.messages.GetDialogFiltersRequest: [_folder(2, "news")],
    })
    ops, lock = _ops(client)
    await lock.acquire()
    task = asyncio.create_task(_METHODS[name](ops))
    await asyncio.sleep(0.01)
    assert client.calls == 0 and not task.done()
    lock.release()
    await task
    assert client.calls > 0
