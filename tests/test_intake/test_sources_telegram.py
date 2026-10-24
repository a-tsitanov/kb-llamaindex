"""TelegramOps на фейковом клиенте: какой TL-запрос и с чем построен."""

import asyncio
from types import SimpleNamespace

import pytest
from telethon import utils as tg_utils
from telethon.errors import FloodWaitError, UsernameNotOccupiedError
from telethon.tl import functions, types

from src.intake.sources.telegram import (
    Candidate,
    FloodWait,
    FolderNotEditable,
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


@pytest.mark.parametrize("raw", ["@foo", "foo", "https://t.me/foo", "t.me/foo/", "http://t.me/foo?x=1", "https://t.me/foo/123"])
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
@pytest.mark.parametrize(
    "raw",
    [
        "https://t.me/joinchat/AAAAAEHbEkejzxUjAUCfYg",
        "t.me/+AbCdEf",
        "t.me/s/foo",
        "t.me/c/1234567890/42",
    ],
)
async def test_resolve_refuses_links_that_are_not_a_handle(raw):
    """Приглашение и служебная ссылка слагом не являются: спросить про них
    телеграм нельзя — ответом был бы чужой канал («joinchat», «s», «c»)."""
    client = _Client({functions.contacts.ResolveUsernameRequest: _resolved(_chan(5, "foo"))})
    ops, _ = _ops(client)
    assert await ops.resolve(raw) is None
    assert client.requests == []


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


@pytest.mark.asyncio
async def test_folder_edits_report_whether_they_changed_anything():
    """Правка папки говорит, тронула ли она состав. Переносу это нужно:
    отменять снятие, которого не было, значит положить канал в папку, где он
    никогда не лежал."""
    client = _Client(
        {functions.messages.GetDialogFiltersRequest: [_folder(1, "news", include=[7])]},
    )
    ops, _ = _ops(client)
    assert await ops.remove_from_folder(_pid(7), "news") is True
    assert await ops.remove_from_folder(_pid(9), "news") is False
    assert await ops.add_to_folder(_pid(9), "news") is True


@pytest.mark.asyncio
async def test_folder_errors_name_the_folder():
    """Имя папки — поле ошибки, а не только текст: вызывающий различает
    «не далась новая» и «не далась старая» без разбора сообщения."""
    client = _Client(
        {functions.messages.GetDialogFiltersRequest: [_folder(1, "news", include=[7])]},
    )
    ops, _ = _ops(client)
    with pytest.raises(FolderNotFound) as missing:
        await ops.add_to_folder(_pid(7), "digest")
    assert missing.value.folder == "digest"


@pytest.mark.asyncio
async def test_remove_from_folder_not_member_does_not_write():
    client = _Client({functions.messages.GetDialogFiltersRequest: [_folder(2, "news", include=[10], pinned=[12])]})
    ops, _ = _ops(client)
    await ops.remove_from_folder(_pid(5), "news")
    assert not any(isinstance(r, functions.messages.UpdateDialogFilterRequest) for r in client.requests)


@pytest.mark.parametrize("method", ["add_to_folder", "remove_from_folder"])
@pytest.mark.asyncio
async def test_shared_chatlist_cannot_be_edited(method):
    chatlist = types.DialogFilterChatlist(
        id=4, title=types.TextWithEntities("news", []),
        pinned_peers=[], include_peers=[_inp(5)],
    )
    client = _Client({functions.messages.GetDialogFiltersRequest: [chatlist]})
    ops, _ = _ops(client)
    with pytest.raises(FolderNotEditable, match="общий"):
        await getattr(ops, method)(_pid(5), "news")
    assert not any(isinstance(r, functions.messages.UpdateDialogFilterRequest) for r in client.requests)


def test_not_editable_is_a_folder_not_found_for_old_callers():
    assert issubclass(FolderNotEditable, FolderNotFound)


@pytest.mark.asyncio
async def test_missing_folder_is_plain_not_found_not_not_editable():
    ops, _ = _ops(_Client({functions.messages.GetDialogFiltersRequest: []}))
    with pytest.raises(FolderNotFound) as ei:
        await ops.remove_from_folder(_pid(5), "news")
    assert not isinstance(ei.value, FolderNotEditable)


@pytest.mark.asyncio
async def test_folder_members_reads_include_and_pinned_without_writing():
    news = _folder(2, "News", include=[10, 11], pinned=[12])
    client = _Client({functions.messages.GetDialogFiltersRequest: [news]})
    ops, _ = _ops(client)
    assert await ops.folder_members("news") == {_pid(10), _pid(11), _pid(12)}
    assert not any(isinstance(r, functions.messages.UpdateDialogFilterRequest) for r in client.requests)


@pytest.mark.asyncio
async def test_folder_members_missing_folder_names_it():
    client = _Client({functions.messages.GetDialogFiltersRequest: [_folder(2, "news")]})
    ops, _ = _ops(client)
    with pytest.raises(FolderNotFound) as ei:
        await ops.folder_members("digest")
    assert ei.value.folder == "digest"


@pytest.mark.asyncio
async def test_folders_with_members_reads_filters_once():
    client = _Client({functions.messages.GetDialogFiltersRequest: [
        types.DialogFilterDefault(), _folder(2, "news", include=[10], pinned=[12]),
        _folder(3, "digest", include=[11]),
    ]})
    ops, _ = _ops(client)
    out = await ops.folders_with_members()
    assert out == {"news": {_pid(10), _pid(12)}, "digest": {_pid(11)}}
    assert [type(r) for r in client.requests] == [functions.messages.GetDialogFiltersRequest]


@pytest.mark.asyncio
async def test_folders_with_members_flags_category_folders():
    flagged = _folder(2, "news", include=[10])
    flagged.broadcasts = True
    client = _Client({functions.messages.GetDialogFiltersRequest: [
        flagged, _folder(3, "digest", include=[11]),
    ]})
    ops, _ = _ops(client)
    out = await ops.folders_with_members()
    assert out["news"] == {_pid(10)} and out["news"].by_category is True
    assert out["digest"].by_category is False


@pytest.mark.asyncio
async def test_folders_with_members_floodwait_and_lock():
    ops, _ = _ops(_Client(dict(_FLOOD_RESPONSES)))
    with pytest.raises(FloodWait):
        await ops.folders_with_members()
    client = _Client({functions.messages.GetDialogFiltersRequest: [_folder(2, "news")]})
    ops, lock = _ops(client)
    await lock.acquire()
    task = asyncio.create_task(ops.folders_with_members())
    await asyncio.sleep(0.01)
    assert client.calls == 0 and not task.done()
    lock.release()
    await task


@pytest.mark.asyncio
async def test_folder_members_matches_the_title_the_same_way_as_edits(monkeypatch):
    client = _Client({functions.messages.GetDialogFiltersRequest: [
        _folder(2, "News", include=[10], pinned=[12]),
    ]})
    ops, _ = _ops(client)
    seen = []
    orig = TelegramOps._find_folder

    async def spy(self, name, **kw):
        seen.append(name)
        return await orig(self, name, **kw)

    monkeypatch.setattr(TelegramOps, "_find_folder", spy)
    assert await ops.folder_members(" news ") == {_pid(10), _pid(12)}
    assert seen == [" news "]
    with pytest.raises(FolderNotFound) as ei:
        await ops.folder_members("memes")
    assert ei.value.folder == "memes"


# ---------- discover: поиск каналов по тому, о чём они пишут ----------

from datetime import UTC, datetime, timedelta  # noqa: E402

NOW = datetime.now(UTC)


def _dchan(cid, username="u", participants=1000, **flags):
    ch = _chan(cid, username if username else None, participants=participants)
    for k, v in flags.items():
        setattr(ch, k, v)
    return ch


def _msg(mid, cid, day=0):
    return types.Message(
        id=mid, peer_id=types.PeerChannel(cid), date=NOW - timedelta(days=day),
        message="дроны",
    )


def _page(msgs, chats, next_rate=None):
    return types.messages.MessagesSlice(
        messages=msgs, chats=chats, users=[], count=999, next_rate=next_rate, topics=[],
    )


class _PagedClient(_Client):
    """Страницы глобального поиска отдаются по очереди; пустая страница — конец."""

    def __init__(self, pages):
        super().__init__()
        self.pages = list(pages)

    async def __call__(self, request):
        if isinstance(request, functions.messages.SearchGlobalRequest):
            self.calls += 1
            self.requests.append(request)
            out = self.pages.pop(0) if self.pages else _page([], [])
            if isinstance(out, Exception):
                raise out
            return out
        return await super().__call__(request)


@pytest.mark.asyncio
async def test_discover_builds_broadcast_only_windowed_request():
    client = _PagedClient([_page([_msg(10, 1), _msg(9, 1, 1)], [_dchan(1)])])
    ops, _ = _ops(client)
    res = await ops.discover("дроны", days=7, enrich=False)
    req = client.requests[0]
    assert req.q == "дроны" and req.broadcasts_only is True
    assert isinstance(req.filter, types.InputMessagesFilterEmpty)
    assert req.max_date is None and req.min_date.tzinfo is not None
    assert abs((NOW - timedelta(days=7)) - req.min_date) < timedelta(seconds=30)
    assert [d.slug for d in res.candidates] == ["@u"]
    assert res.candidates[0].hits == 2 and res.candidates[0].active_days == 2
    assert res.candidates[0].last_post == NOW.date().isoformat()
    assert res.scanned == 2 and not res.partial and res.wait_seconds is None


@pytest.mark.asyncio
async def test_discover_paginates_with_offsets_from_previous_response():
    chats = [_dchan(1), _dchan(2, "w")]
    client = _PagedClient([
        _page([_msg(10, 1), _msg(8, 2)], chats, next_rate=555),
        _page([_msg(7, 1)], chats),
    ])
    ops, _ = _ops(client)
    res = await ops.discover("x", enrich=False)
    assert len(client.requests) == 3  # третья — пустая страница, конец
    second = client.requests[1]
    assert second.offset_rate == 555 and second.offset_id == 8
    assert isinstance(second.offset_peer, types.InputPeerChannel)
    assert second.offset_peer.channel_id == 2 and second.offset_peer.access_hash == 14
    assert res.scanned == 3
    assert {d.slug: d.hits for d in res.candidates} == {"@u": 2}


@pytest.mark.asyncio
async def test_discover_scan_cap_stops_even_if_more_available():
    pages = [_page([_msg(1000 - p * 10 - i, 1) for i in range(5)], [_dchan(1)], next_rate=p + 1)
             for p in range(10)]
    client = _PagedClient(pages)
    ops, _ = _ops(client)
    res = await ops.discover("x", scan=7, enrich=False)
    assert res.scanned == 7
    assert len(client.requests) == 2
    assert res.candidates[0].hits == 7


@pytest.mark.asyncio
async def test_discover_drops_junk_and_keeps_unknown_audience():
    chats = [
        _dchan(1), _dchan(2, "s", scam=True), _dchan(3, None),
        _dchan(4, "one"), _dchan(5, "tiny", participants=50),
        _dchan(6, "unk", participants=None), _dchan(7, "fk", fake=True),
        _dchan(8, "rs", restricted=True),
    ]
    msgs = [_msg(i * 10 + k, i) for i in (1, 2, 3, 5, 6, 7, 8) for k in (1, 2)]
    msgs.append(_msg(99, 4))
    client = _PagedClient([_page(msgs, chats)])
    ops, _ = _ops(client)
    res = await ops.discover("x", enrich=False)
    assert sorted(d.slug for d in res.candidates) == ["@u", "@unk"]
    unk = next(d for d in res.candidates if d.slug == "@unk")
    assert unk.participants is None


@pytest.mark.asyncio
async def test_discover_ranks_by_active_days_before_hits():
    chats = [_dchan(1, "burst"), _dchan(2, "steady")]
    msgs = [_msg(i, 1) for i in range(20, 30)]
    msgs += [_msg(40 + d, 2, d) for d in range(5)]
    client = _PagedClient([_page(msgs, chats)])
    ops, _ = _ops(client)
    res = await ops.discover("x", limit=1, enrich=False)
    assert [d.slug for d in res.candidates] == ["@steady"]
    assert res.candidates[0].active_days == 5
    full = await _ops(_PagedClient([_page(msgs, chats)]))[0].discover("x", enrich=False)
    assert [d.slug for d in full.candidates] == ["@steady", "@burst"]


@pytest.mark.asyncio
async def test_discover_floodwait_returns_partial_result():
    chats = [_dchan(1)]
    client = _PagedClient([
        _page([_msg(10, 1), _msg(9, 1)], chats, next_rate=5), _flood(42),
    ])
    ops, lock = _ops(client)
    res = await ops.discover("x", enrich=False)
    assert res.partial is True and res.wait_seconds == 42
    assert [d.slug for d in res.candidates] == ["@u"]
    assert not lock.locked()


# ---------- discover: доработка (аудитория, окно, дубли, конец выдачи) ----------


def _full(count):
    return SimpleNamespace(full_chat=SimpleNamespace(participants_count=count))


class _EnrichClient(_PagedClient):
    """Как `_PagedClient`, плюс `GetFullChannelRequest`: ответ по id канала."""

    def __init__(self, pages, full):
        super().__init__(pages)
        self.full = full
        self.full_requests = []

    async def __call__(self, request):
        if isinstance(request, functions.channels.GetFullChannelRequest):
            self.calls += 1
            self.requests.append(request)
            self.full_requests.append(request.channel.channel_id)
            out = self.full[request.channel.channel_id]
            if isinstance(out, Exception):
                raise out
            return out
        return await super().__call__(request)


def _unknown_audience_page():
    chats = [_dchan(1, "big", participants=None), _dchan(2, "small", participants=None)]
    msgs = [_msg(10 + k, 1, k) for k in range(2)] + [_msg(20 + k, 2, k) for k in range(3)]
    return _page(msgs, chats)


@pytest.mark.asyncio
async def test_discover_enrichment_fills_audience_and_resorts():
    client = _EnrichClient([_unknown_audience_page()], {1: _full(9000), 2: _full(700)})
    ops, _ = _ops(client)
    res = await ops.discover("x")
    assert sorted(client.full_requests) == [1, 2]
    assert {d.slug: d.participants for d in res.candidates} == {"@big": 9000, "@small": 700}
    # у @small больше дней — выше; перестановка по аудитории проверяется ниже
    assert [d.slug for d in res.candidates] == ["@small", "@big"]


@pytest.mark.asyncio
async def test_discover_enrichment_resorts_on_audience_tiebreak():
    chats = [_dchan(1, "a", participants=None), _dchan(2, "b", participants=None)]
    msgs = [_msg(10, 1), _msg(11, 1), _msg(20, 2), _msg(21, 2)]
    client = _EnrichClient([_page(msgs, chats)], {1: _full(600), 2: _full(9000)})
    res = await _ops(client)[0].discover("x")
    assert [d.slug for d in res.candidates] == ["@b", "@a"]


@pytest.mark.asyncio
async def test_discover_enrichment_failure_of_one_keeps_the_rest():
    client = _EnrichClient(
        [_unknown_audience_page()], {1: RuntimeError("private"), 2: _full(700)},
    )
    res = await _ops(client)[0].discover("x")
    got = {d.slug: d.participants for d in res.candidates}
    assert got == {"@big": None, "@small": 700}
    assert res.partial is False


@pytest.mark.asyncio
async def test_discover_enrichment_floodwait_is_partial_and_keeps_candidates():
    client = _EnrichClient([_unknown_audience_page()], {1: _full(9000), 2: _flood(33)})
    ops, lock = _ops(client)
    # порядок запросов: сначала @small (больше дней), он и ловит FloodWait
    res = await ops.discover("x")
    assert res.partial is True and res.wait_seconds == 33
    assert sorted(d.slug for d in res.candidates) == ["@big", "@small"]
    assert client.full_requests == [2]  # на FloodWait остальных не опрашиваем
    assert all(d.participants is None for d in res.candidates)
    assert not lock.locked()


@pytest.mark.asyncio
async def test_discover_min_participants_applies_only_to_known_counts():
    chats = [_dchan(i, n, participants=None) for i, n in ((1, "a"), (2, "b"), (3, "c"))]
    msgs = [_msg(i * 10 + k, i) for i in (1, 2, 3) for k in (1, 2)]
    client = _EnrichClient(
        [_page(msgs, chats)], {1: _full(100), 2: RuntimeError("x"), 3: _full(5000)},
    )
    res = await _ops(client)[0].discover("x", min_participants=500)
    assert sorted(d.slug for d in res.candidates) == ["@b", "@c"]
    # без обогащения порог по неизвестному числу не режет ничего
    client2 = _EnrichClient([_page(msgs, chats)], {})
    res2 = await _ops(client2)[0].discover("x", min_participants=500, enrich=False)
    assert len(res2.candidates) == 3


@pytest.mark.asyncio
async def test_discover_enrich_false_makes_no_extra_request():
    client = _EnrichClient([_unknown_audience_page()], {})
    res = await _ops(client)[0].discover("x", enrich=False)
    assert client.full_requests == [] and len(res.candidates) == 2
    assert all(d.participants is None for d in res.candidates)


@pytest.mark.asyncio
async def test_discover_enriches_at_most_limit_candidates():
    chats = [_dchan(i, f"c{i}", participants=None) for i in range(1, 6)]
    msgs = [_msg(i * 10 + k, i) for i in range(1, 6) for k in (1, 2)]
    client = _EnrichClient([_page(msgs, chats)], {i: _full(1000) for i in range(1, 6)})
    res = await _ops(client)[0].discover("x", limit=2)
    assert len(res.candidates) == 2 and len(client.full_requests) == 2


@pytest.mark.asyncio
async def test_discover_skips_messages_older_than_window():
    chats = [_dchan(1, "fresh"), _dchan(2, "stale")]
    msgs = [_msg(10, 1, 1), _msg(11, 1, 2), _msg(20, 2, 40), _msg(21, 2, 41)]
    client = _PagedClient([_page(msgs, chats)])
    res = await _ops(client)[0].discover("x", days=30, enrich=False)
    assert [(d.slug, d.hits) for d in res.candidates] == [("@fresh", 2)]
    assert res.scanned == 2  # устаревшие бюджет скана не едят


@pytest.mark.asyncio
async def test_discover_stops_when_page_is_entirely_out_of_window():
    chats = [_dchan(1)]
    client = _PagedClient([
        _page([_msg(10, 1, 40), _msg(9, 1, 41)], chats, next_rate=5),
        _page([_msg(8, 1, 1), _msg(7, 1, 2)], chats),
    ])
    res = await _ops(client)[0].discover("x", days=30, enrich=False)
    assert len(client.requests) == 1 and res.candidates == []


@pytest.mark.asyncio
async def test_discover_does_not_count_a_message_twice():
    chats = [_dchan(1)]
    client = _PagedClient([
        _page([_msg(10, 1), _msg(9, 1)], chats, next_rate=5),
        _page([_msg(9, 1), _msg(8, 1)], chats),
    ])
    res = await _ops(client)[0].discover("x", enrich=False)
    assert res.candidates[0].hits == 3 and res.scanned == 3


@pytest.mark.asyncio
async def test_discover_stops_when_response_is_not_a_slice():
    chats = [_dchan(1)]
    plain = types.messages.Messages(
        messages=[_msg(10, 1), _msg(9, 1)], chats=chats, users=[], topics=[],
    )
    client = _PagedClient([plain])
    res = await _ops(client)[0].discover("x", enrich=False)
    assert len(client.requests) == 1 and res.candidates[0].hits == 2


@pytest.mark.asyncio
async def test_discover_stops_when_count_is_exhausted():
    chats = [_dchan(1)]
    page = types.messages.MessagesSlice(
        messages=[_msg(10, 1), _msg(9, 1)], chats=chats, users=[], count=2,
        next_rate=5, topics=[],
    )
    client = _PagedClient([page])
    await _ops(client)[0].discover("x", enrich=False)
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_discover_ties_break_on_peer_id():
    chats = [_dchan(2, "two"), _dchan(1, "one")]
    msgs = [_msg(10, 2), _msg(11, 2), _msg(20, 1), _msg(21, 1)]
    res = await _ops(_PagedClient([_page(msgs, chats)]))[0].discover("x", enrich=False)
    assert [d.peer_id for d in res.candidates] == sorted(d.peer_id for d in res.candidates)
