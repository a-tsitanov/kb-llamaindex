"""Фидер отступает на квотный отказ приёма (429, шаг 1.6).

Квота отвечает «сейчас нет места», а не «сломалось», и фидер обязан это
различать: 429 как ошибка означал бы, что окно канала стоит на месте,
пока очередь не рассосётся, а 429 как успех — что сообщение потеряно.
Поэтому `post_ingest` ждёт названный срок и пробует снова, а исчерпав
попытки, отдаёт ``FAILED`` — проход останавливается на этом сообщении и
курсор не двигается (``read_and_enqueue``).
"""

from __future__ import annotations

import pytest

from scripts import tg_ingest
from scripts.tg_ingest import FAILED, SENT, post_ingest


class _Resp:
    def __init__(self, status_code: int, retry_after: str | None = None) -> None:
        self.status_code = status_code
        self.headers = {} if retry_after is None else {"Retry-After": retry_after}


class _Client:
    """Отдаёт заготовленные ответы по порядку; последний повторяется."""

    def __init__(self, *responses: _Resp) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def post(self, *_a, **_k):
        self.calls += 1
        idx = min(self.calls - 1, len(self._responses) - 1)
        return self._responses[idx]


@pytest.fixture
def slept(monkeypatch) -> list[float]:
    waits: list[float] = []

    async def _sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(tg_ingest.asyncio, "sleep", _sleep)
    return waits


@pytest.mark.asyncio
async def test_waits_the_named_delay_then_succeeds(slept) -> None:
    http = _Client(_Resp(429, "7"), _Resp(202))

    outcome = await post_ingest(http, "http://api", "k", "f.txt", "t", "2026-10-20", None)

    assert outcome == SENT
    assert http.calls == 2
    assert slept == [7]


@pytest.mark.asyncio
async def test_persistent_refusal_ends_as_failed_with_bounded_attempts(slept) -> None:
    """Исчерпав попытки, фидер НЕ объявляет сообщение отправленным."""
    http = _Client(_Resp(429, "1"))

    outcome = await post_ingest(http, "http://api", "k", "f.txt", "t", "2026-10-20", None)

    assert outcome == FAILED
    assert http.calls == tg_ingest.QUOTA_ATTEMPTS
    # Между попытками — ожидание, после последней — нет: спать незачем,
    # следующий проход всё равно начнётся с этого же сообщения.
    assert len(slept) == tg_ingest.QUOTA_ATTEMPTS - 1


@pytest.mark.asyncio
async def test_missing_or_garbage_retry_after_falls_back_to_the_default(slept) -> None:
    for header in (None, "soon"):
        http = _Client(_Resp(429, header), _Resp(202))
        slept.clear()

        assert await post_ingest(
            http, "http://api", "k", "f.txt", "t", "2026-10-20", None,
        ) == SENT
        assert slept == [tg_ingest.QUOTA_DEFAULT_WAIT_S], header


@pytest.mark.asyncio
async def test_absurd_retry_after_is_clamped(slept) -> None:
    """Сервер может назвать час; фидер — не cron, ждать столько он не
    должен, и следующий проход всё равно повторит сообщение."""
    http = _Client(_Resp(429, "3600"), _Resp(202))

    assert await post_ingest(
        http, "http://api", "k", "f.txt", "t", "2026-10-20", None,
    ) == SENT
    assert slept == [tg_ingest.QUOTA_MAX_WAIT_S]


@pytest.mark.asyncio
async def test_other_errors_are_not_retried(slept) -> None:
    """Отступать — только на 429: 500 повтором не лечится, а 409 вообще
    не ошибка (его разбирает отдельная ветка)."""
    http = _Client(_Resp(500))

    assert await post_ingest(
        http, "http://api", "k", "f.txt", "t", "2026-10-20", None,
    ) == FAILED
    assert http.calls == 1
    assert slept == []
