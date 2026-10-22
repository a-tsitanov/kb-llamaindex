"""Фидер отступает на квотный отказ приёма — но политику исполняет клиент.

Само правило (сколько ждать, сколько попыток, что значит каждый код)
проверяется в ``tests/test_intake/test_client.py``. Здесь предмет один:
`post_ingest` ДЕЛЕГИРУЕТ клиенту и правильно отображает исход в счётчики
прохода — ``FAILED`` на исчерпанных попытках, потому что курсор канала
двигать нельзя, и ``SENT``, когда место нашлось.
"""

from __future__ import annotations

import pytest

from scripts.tg_ingest import FAILED, SENT, post_ingest
from src.intake import client as client_mod


class _Resp:
    def __init__(self, status_code: int, retry_after: str | None = None) -> None:
        self.status_code = status_code
        self.headers = {} if retry_after is None else {"Retry-After": retry_after}

    def json(self):
        raise ValueError("no body")


class _Client:
    def __init__(self, *responses: _Resp) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def post(self, *_a, **_k):
        self.calls += 1
        return self._responses[min(self.calls - 1, len(self._responses) - 1)]


@pytest.fixture
def slept(monkeypatch) -> list[float]:
    waits: list[float] = []

    async def _sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(client_mod.asyncio, "sleep", _sleep)
    return waits


@pytest.mark.asyncio
async def test_waits_then_succeeds(slept) -> None:
    http = _Client(_Resp(429, "7"), _Resp(202))

    outcome = await post_ingest(http, "http://api", "k", "f.txt", "t", "2026-10-22", None)

    assert outcome == SENT
    assert http.calls == 2 and slept == [7]


@pytest.mark.asyncio
async def test_persistent_refusal_does_not_claim_the_message_was_sent(slept) -> None:
    """Исход FAILED — он и останавливает проход без сдвига курсора."""
    http = _Client(_Resp(429, "1"))

    outcome = await post_ingest(http, "http://api", "k", "f.txt", "t", "2026-10-22", None)

    assert outcome == FAILED
    assert http.calls == client_mod.QUOTA_ATTEMPTS
