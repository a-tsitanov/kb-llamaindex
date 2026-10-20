"""Повторный прогон медицинского корпуса (`scripts.ingest_medical`).

Шаг документирован как повторяемый (docs/DEPLOYMENT.md §8b), а тело
получается байт-в-байт тем же, поэтому ВТОРОЙ прогон упирается в дедуп
приёма и получает 409.  Тесты держат ровно это: 409 — это «корпус уже
принят», а не падение прогона, и поллится документ, названный в теле.

Ответы — настоящие ``httpx.Response``: ``raise_for_status`` на них бросает
по-честному, поэтому тест упал бы, если бы скрипт снова звал его на 409.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from scripts.ingest_medical import enqueue

_ARGS = SimpleNamespace(api_key="dev-local-key", department="medical")


def _resp(status: int, payload: dict) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        request=httpx.Request("POST", "http://test/api/v1/ingest"),
    )


class _Client:
    """Клиент на один ответ; запоминает поля формы отправленного POST'а."""

    def __init__(self, resp: httpx.Response):
        self.resp = resp
        self.posted: list[dict[str, str]] = []

    def post(self, _url: str, *, headers=None, files=None, data=None) -> httpx.Response:
        self.posted.append(dict(data or {}))
        return self.resp


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    target = tmp_path / "medical_corpus.txt"
    target.write_text("contents", encoding="utf-8")
    return target


def test_first_run_returns_the_new_job_id(corpus: Path) -> None:
    job_id = uuid.uuid4()
    client = _Client(_resp(202, {"job_id": str(job_id)}))

    assert enqueue(client, _ARGS, corpus) == str(job_id)
    # Политику повтора скрипт не шлёт — вторая копия бенчмарк-корпуса
    # удвоила бы чанки под каждым вопросом eval'а.
    assert client.posted == [{"department": "medical"}]


def test_repeat_run_polls_the_already_ingested_document(corpus: Path) -> None:
    """409 по дедупу — «уже принято», а не ошибка: поллим названный документ."""
    first_id = uuid.uuid4()
    client = _Client(
        _resp(409, {"detail": {
            "message": "duplicate",
            "doc_id": str(first_id),
            "intake_status": "accepted",
        }}),
    )

    assert enqueue(client, _ARGS, corpus) == str(first_id)


def test_409_without_doc_id_gives_up(corpus: Path) -> None:
    """Ключ без scope ``read`` не получает идентификаторов в теле 409.

    Поллить такой ключ всё равно не смог бы (``GET /api/v1/ingest/{job_id}``
    требует того же ``read``), поэтому прогон честно заканчивается ненулевым
    кодом, а не трассировкой.
    """
    client = _Client(_resp(409, {"detail": {"message": "duplicate"}}))

    assert enqueue(client, _ARGS, corpus) is None


def test_quota_refusal_is_reported_as_quota_not_as_a_crash(corpus: Path) -> None:
    """429 — «в графе нет места», и прогон обязан сказать это словами.

    Без этой ветки `raise_for_status` отдал бы оператору трассировку
    httpx, из которой не видно ни квоты, ни того, что повторить прогон
    можно просто позже (шаг 1.6).
    """
    client = _Client(_resp(429, {"detail": "graph backlog is full: 500, cap 500"}))

    with pytest.raises(SystemExit) as exc:
        enqueue(client, _ARGS, corpus)
    assert "quota" in str(exc.value).lower() or "backlog" in str(exc.value).lower()
