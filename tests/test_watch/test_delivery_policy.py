"""Политика доставки наблюдения (S4 плана P2).

Предмет — четыре правила, каждое из которых ломается молча:

1. **Право проверяется ПЕРЕД КАЖДОЙ отправкой.** Доставка идёт сама, не в
   ответ на запрос, и адресат назначен подписчиком, а тело несёт имена
   сущностей графа. Отозвали права — доставка молчит.
2. **Дедуп.** Одно событие одному подписчику уходит один раз, сколько бы
   раз свип ни перезапускался.
3. **Потолок в сутки и сводка.** События пишутся все (лента полная), но
   пушей не больше N; остаток — одним сообщением.
4. **Адресат валидируется.** URL приходит от подписчика и уходит в
   исходящий запрос с сервера.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from src.tenancy.api_keys import ApiKeyRecord
from src.tenancy.context import default_graph_context
from src.watch import delivery as mod

_OWNER = "analyst"
_URL = "http://hook.internal/watch"


def _event(event_id: int, *, owner: str = _OWNER, url: str = _URL,
           kind: str = "new_mention", limit: int | None = None,
           created_by: str | None = None) -> dict[str, Any]:
    return {
        "id": event_id, "entity_vid": "vid1", "entity_name": "Акме", "kind": kind,
        "doc_id": "11111111-1111-1111-1111-111111111111", "doc_date": None,
        "detail": {"provenance": {"source_kind": "tg:news"}}, "why": "упоминается",
        "detected_at": dt.datetime(2026, 10, 20, 12, 0, 0),
        "owner": owner, "webhook_url": url, "daily_push_limit": limit, "attempts": 0,
        # Принципал подписки — имя КЛЮЧА, которым подписались; `owner` для
        # этого не годится (он корзина ленты и сегодня константа).
        "created_by": owner if created_by is None else created_by,
    }


class _Repo:
    """Репозиторий наблюдения: отдаёт очередь и копит отметки."""

    def __init__(self, due: list[dict[str, Any]], sent_today: int = 0) -> None:
        self.due = due
        self.sent_today = sent_today
        self.marks: list[tuple[str, int, str, int | None]] = []
        self.digests: list[int] = []
        self.closed: list[tuple[int, str]] = []
        self._next_digest = 500

    async def due_deliveries(self, *, limit: int, max_attempts: int):
        return self.due

    async def pushes_today(self, owner: str) -> int:
        return self.sent_today

    async def mark_delivery(self, owner, event_id, state, *, error="", digest_of=None):
        self.marks.append((owner, event_id, state, digest_of))

    async def open_digest(self, owner: str, events: int) -> int:
        self._next_digest += 1
        self.digests.append(self._next_digest)
        return self._next_digest

    async def close_digest(self, digest_id: int, state: str, error: str = "") -> None:
        self.closed.append((digest_id, state))


class _Sender:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.sent: list[tuple[str, dict]] = []

    async def __call__(self, url: str, payload: dict, *, timeout_s: float = 5.0) -> bool:
        self.sent.append((url, payload))
        return self.ok


def _allow_all(_owner: str):
    async def _records(owner: str) -> list[ApiKeyRecord]:
        return [ApiKeyRecord.full(owner)]

    return _records


@pytest.fixture
def patched(monkeypatch):
    """Подменяет отправку и чтение ключей; возвращает установщик."""

    def _setup(*, sender: _Sender, records=None):
        monkeypatch.setattr(mod, "post_alert", sender)
        monkeypatch.setattr(
            mod, "records_for_owner", records or _allow_all(_OWNER),
        )
        return sender

    return _setup


async def _run(repo, graph=None, **kw):
    return await mod.deliver_due(repo, graph or default_graph_context(), **kw)


# ── право ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoking_every_key_stops_delivery(patched) -> None:
    """Ни одного живого ключа у владельца — не отправляем и не теряем.

    Строка остаётся неотправленной (а не 'failed'): права могут
    вернуть, и тогда событие уйдёт, а не исчезнет.
    """
    async def _none(owner: str) -> list[ApiKeyRecord]:
        return []

    sender = patched(sender=_Sender(), records=_none)
    repo = _Repo([_event(1)])
    out = await _run(repo)

    assert sender.sent == []
    assert repo.marks == []
    assert out["refused"] == 1


@pytest.mark.asyncio
async def test_key_without_read_does_not_receive_events(patched) -> None:
    """Подписка — чтение графа: ключ без `read` уведомлений не получает."""
    sender = _Sender()

    async def _write_only(owner: str) -> list[ApiKeyRecord]:
        return [ApiKeyRecord(owner=owner, tenant_id="default",
                             scopes=frozenset({"write"}), graph_ids=None)]

    patched(sender=sender, records=_write_only)
    repo = _Repo([_event(1)])
    out = await _run(repo)

    assert sender.sent == [] and out["refused"] == 1


@pytest.mark.asyncio
async def test_key_of_another_graph_does_not_receive_events(patched) -> None:
    sender = _Sender()

    async def _elsewhere(owner: str) -> list[ApiKeyRecord]:
        return [ApiKeyRecord(owner=owner, tenant_id="default",
                             scopes=frozenset({"read"}), graph_ids=("acme",))]

    patched(sender=sender, records=_elsewhere)
    repo = _Repo([_event(1)])
    out = await _run(repo)

    assert sender.sent == [] and out["refused"] == 1


# ── отправка и дедуп ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delivered_event_is_marked_and_carries_provenance(patched) -> None:
    sender = patched(sender=_Sender())
    repo = _Repo([_event(1)])

    out = await _run(repo)

    assert out["delivered"] == 1 and out["failed"] == 0
    url, payload = sender.sent[0]
    assert url == _URL
    assert payload["event_id"] == 1 and payload["kind"] == "new_mention"
    assert payload["entity"]["name"] == "Акме"
    assert payload["graph"] == "default"
    # Провенанс приёма доезжает до подписчика — ради него он и собирался.
    assert payload["detail"]["provenance"]["source_kind"] == "tg:news"
    assert repo.marks == [(_OWNER, 1, "delivered", None)]


@pytest.mark.asyncio
async def test_failed_send_is_recorded_for_a_later_retry(patched) -> None:
    patched(sender=_Sender(ok=False))
    repo = _Repo([_event(1)])

    out = await _run(repo)

    assert out["failed"] == 1 and out["delivered"] == 0
    assert repo.marks == [(_OWNER, 1, "failed", None)]


# ── потолок и сводка ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_over_the_cap_goes_into_one_digest(patched) -> None:
    """Сверх потолка — одно сообщение, а не поток и не тишина."""
    sender = patched(sender=_Sender())
    repo = _Repo([_event(i, limit=2) for i in (1, 2, 3, 4)])

    out = await _run(repo)

    assert out["delivered"] == 2 and out["suppressed"] == 2
    assert out["digests"] == 1
    # Три отправки: два события и одна сводка.
    assert len(sender.sent) == 3
    digest = sender.sent[-1][1]
    assert digest["digest"] is True
    assert digest["suppressed"] == 2
    assert digest["by_kind"] == {"new_mention": 2}
    assert "Акме" in digest["entities"]
    # Подавленные помечены и привязаны к сводке — по строке видно, где их
    # всё-таки показали.
    suppressed = [m for m in repo.marks if m[2] == "suppressed"]
    assert len(suppressed) == 2 and all(m[3] == repo.digests[0] for m in suppressed)


@pytest.mark.asyncio
async def test_todays_earlier_pushes_count_towards_the_cap(patched) -> None:
    sender = patched(sender=_Sender())
    repo = _Repo([_event(1, limit=2), _event(2, limit=2)], sent_today=2)

    out = await _run(repo)

    assert out["delivered"] == 0 and out["suppressed"] == 2
    # Одно сообщение — сводка.
    assert len(sender.sent) == 1 and sender.sent[0][1]["digest"] is True


@pytest.mark.asyncio
async def test_default_cap_comes_from_settings_when_the_row_is_null(patched) -> None:
    sender = patched(sender=_Sender())
    repo = _Repo([_event(i) for i in range(1, 4)])

    out = await _run(repo, default_limit=1)

    assert out["delivered"] == 1 and out["suppressed"] == 2
    assert sender.sent[-1][1]["digest"] is True


@pytest.mark.asyncio
async def test_failed_digest_leaves_the_events_suppressed_not_pending(patched) -> None:
    """Сводка не ушла — события всё равно подавлены.

    Иначе следующий проход отправил бы их по одному, то есть потолок
    обходился бы падением сводки.
    """
    patched(sender=_Sender(ok=False))
    repo = _Repo([_event(1, limit=0)])

    out = await _run(repo, default_limit=0)

    assert out["suppressed"] == 1
    assert [m[2] for m in repo.marks] == ["suppressed"]
    assert repo.closed and repo.closed[0][1] == "failed"


# ── адресат ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://host/x", "notaurl"])
async def test_non_http_destination_is_refused(patched, url: str) -> None:
    """URL приходит от подписчика и уходит в запрос с сервера: схема
    проверяется и на записи (MCP), и здесь — строку могли поправить в SQL."""
    sender = patched(sender=_Sender())
    repo = _Repo([_event(1, url=url)])

    out = await _run(repo)

    assert sender.sent == [] and out["refused"] == 1


@pytest.mark.asyncio
async def test_two_subscribers_are_independent(patched) -> None:
    """Потолок и права — на подписчика, а не на граф."""
    sender = _Sender()

    async def _records(owner: str) -> list[ApiKeyRecord]:
        return [] if owner == "muted" else [ApiKeyRecord.full(owner)]

    patched(sender=sender, records=_records)
    repo = _Repo([_event(1), _event(2, owner="muted")])

    out = await _run(repo)

    assert out["delivered"] == 1 and out["refused"] == 1
    assert [p["event_id"] for _u, p in sender.sent] == [1]


@pytest.mark.asyncio
async def test_subscription_without_a_principal_is_feed_only(patched) -> None:
    """Подписка без `created_by` push не получает.

    Так выглядят легаси-строки и подписки, созданные по stdio без токена:
    проверять право не по чему, а отправить «от имени никого» значило бы
    отдать содержимое графа наружу без проверки вообще. Найдено живой
    проверкой 2026-10-21: `watch.owner` — константа 'default', и ключа с
    таким именем в реестре нет.
    """
    sender = patched(sender=_Sender())
    repo = _Repo([_event(1, created_by="")])

    out = await _run(repo)

    assert sender.sent == [] and out["refused"] == 1
    assert repo.marks == []


@pytest.mark.asyncio
async def test_right_is_checked_against_the_principal_not_the_feed_owner(patched) -> None:
    sender = _Sender()
    asked: list[str] = []

    async def _records(owner: str):
        asked.append(owner)
        return [ApiKeyRecord.full(owner)]

    patched(sender=sender, records=_records)
    repo = _Repo([_event(1, owner="default", created_by="analyst-key")])

    out = await _run(repo)

    assert out["delivered"] == 1
    assert asked == ["analyst-key"]
    # Журнал доставки по-прежнему ключуется владельцем ленты.
    assert repo.marks == [("default", 1, "delivered", None)]
