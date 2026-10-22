"""Клиент приёма: одна политика ответов на всех фидеров.

До этого модуля правило «что значит 409, что значит 429 и сколько ждать»
было скопировано трижды, каждый раз со своими константами. Тесты держат
само правило, а не конкретного фидера.
"""

from __future__ import annotations

import pytest

from src.intake import client as mod
from src.intake.client import DUPLICATE, FAILED, SENT, classify, post_document, quota_wait


class _Resp:
    def __init__(self, status_code: int, retry_after: str | None = None,
                 body: object | None = None) -> None:
        self.status_code = status_code
        self.headers = {} if retry_after is None else {"Retry-After": retry_after}
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class _Client:
    """Отдаёт заготовленные ответы по порядку; последний повторяется."""

    def __init__(self, *responses: _Resp) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def post(self, url, headers=None, files=None, data=None):
        self.calls.append({"url": url, "headers": headers, "files": files, "data": data})
        idx = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[idx]


@pytest.fixture
def slept(monkeypatch) -> list[float]:
    waits: list[float] = []

    async def _sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(mod.asyncio, "sleep", _sleep)
    return waits


async def _post(http, **kw):
    return await post_document(
        http, "http://api", "k", filename="t.txt", content=b"body", **kw,
    )


# ── правило кодов ────────────────────────────────────────────────────


def test_classify_treats_409_as_success_of_the_pass() -> None:
    """409 — не ошибка: тело приём уже знает, повторять незачем."""
    assert classify(202) == SENT
    assert classify(200) == SENT
    assert classify(409) == DUPLICATE
    assert classify(500) == FAILED
    assert classify(403) == FAILED
    # 429 — единственный код, на котором есть смысл подождать, поэтому у
    # него нет исхода: решает цикл отступления.
    assert classify(429) == ""


def test_quota_wait_defaults_and_clamps() -> None:
    assert quota_wait(_Resp(429, "7")) == 7
    assert quota_wait(_Resp(429)) == mod.QUOTA_DEFAULT_WAIT_S
    # HTTP-дата вместо секунд: берём умолчание, а не падаем.
    assert quota_wait(_Resp(429, "Wed, 22 Oct 2026 18:00:00 GMT")) == mod.QUOTA_DEFAULT_WAIT_S
    assert quota_wait(_Resp(429, "3600")) == mod.QUOTA_MAX_WAIT_S
    assert quota_wait(_Resp(429, "0")) == 1


# ── отправка ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_accepted_document_reports_sent(slept) -> None:
    http = _Client(_Resp(202))

    out = await _post(http)

    assert out.outcome == SENT and out.status_code == 202 and out.attempts == 1
    assert slept == []
    call = http.calls[0]
    assert call["url"] == "http://api/api/v1/ingest"
    assert call["headers"]["X-API-Key"] == "k" and "X-Graph" not in call["headers"]
    assert call["files"]["file"][0] == "t.txt"


@pytest.mark.asyncio
async def test_graph_header_sent_only_when_asked(slept) -> None:
    """Без графа заголовка нет вовсе: ключ, сужённый до одного графа, сам
    задаёт цель, и подставлять `default` за него нельзя."""
    http = _Client(_Resp(202))

    await _post(http, graph="acme")

    assert http.calls[0]["headers"]["X-Graph"] == "acme"


@pytest.mark.asyncio
async def test_duplicate_carries_the_owner_when_disclosed(slept) -> None:
    http = _Client(_Resp(409, body={"detail": {"message": "duplicate",
                                               "doc_id": "d-1",
                                               "intake_status": "accepted"}}))

    out = await _post(http)

    assert out.outcome == DUPLICATE
    assert out.duplicate_of == "d-1"
    assert out.detail["intake_status"] == "accepted"


@pytest.mark.asyncio
async def test_duplicate_without_disclosure_is_still_a_duplicate(slept) -> None:
    """Ключ без права чтения идентификаторов в теле 409 не видит — исход
    от этого не меняется."""
    http = _Client(_Resp(409, body={"detail": "duplicate"}))

    out = await _post(http)

    assert out.outcome == DUPLICATE and out.duplicate_of is None


@pytest.mark.asyncio
async def test_quota_waits_the_named_delay_then_succeeds(slept) -> None:
    http = _Client(_Resp(429, "7"), _Resp(202))

    out = await _post(http)

    assert out.outcome == SENT and out.attempts == 2
    assert slept == [7]


@pytest.mark.asyncio
async def test_persistent_quota_ends_as_failed_with_bounded_attempts(slept) -> None:
    http = _Client(_Resp(429, "1"))

    out = await _post(http)

    assert out.outcome == FAILED and out.status_code == 429
    assert len(http.calls) == mod.QUOTA_ATTEMPTS
    # После последней попытки не спим: следующий проход всё равно начнётся
    # с этого же документа.
    assert len(slept) == mod.QUOTA_ATTEMPTS - 1


@pytest.mark.asyncio
async def test_server_error_is_not_retried(slept) -> None:
    http = _Client(_Resp(500))

    out = await _post(http)

    assert out.outcome == FAILED and len(http.calls) == 1 and slept == []


@pytest.mark.asyncio
async def test_network_failure_never_raises(slept) -> None:
    class _Broken:
        async def post(self, *a, **k):
            raise RuntimeError("connection refused")

    out = await _post(_Broken())

    assert out.outcome == FAILED and out.status_code == 0
