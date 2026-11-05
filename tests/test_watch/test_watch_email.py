"""Entity-watch e-mail digest: letter building, SMTP send, the activity."""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import ClassVar

import pytest

from src.watch import activities as act
from src.watch import watch_email as we

_DOC = "d0c5e6a0-0000-0000-0000-000000000001"
_LINK = "http://kb:8000/api/v1/documents/{doc_id}"


def _ev(i, kind, *, vid="v1", name="Блинов Андрей Степанович", doc=_DOC, detail=None, why="x"):
    return {
        "id": i, "entity_vid": vid, "entity_name": name, "kind": kind,
        "doc_id": doc, "doc_date": date(2024, 3, 12), "detail": detail or {}, "why": why,
        "detected_at": datetime(2026, 10, 15, 12, i, tzinfo=UTC),
        "doc_path": "s3://kb/uploads/protocol-12.docx" if doc else None,
    }


# ── building ─────────────────────────────────────────────────────────


def test_events_of_one_document_share_a_block_under_their_entity():
    rows = [
        _ev(1, "new_mention"),
        _ev(2, "new_identifier", detail={"other": "+79035551234", "rel": "PHONE"}),
        _ev(3, "new_mention", vid="v2", name="Кравцов О.И."),
    ]
    groups = we.group_events(rows, link=_LINK)
    assert [g["name"] for g in groups] == ["Блинов Андрей Степанович", "Кравцов О.И."]
    block = groups[0]["docs"][0]
    assert block["title"] == "protocol-12.docx"
    assert block["link"] == f"http://kb:8000/api/v1/documents/{_DOC}"
    assert [e["title"] for e in block["events"]] == ["Новое упоминание", "Новый идентификатор"]
    assert block["events"][1]["detail"] == "+79035551234 (PHONE)"


def test_events_without_a_document_get_a_block_each():
    rows = [_ev(1, "contradiction", doc=None, detail={"src": "А", "rel": "OWNS", "tgt": "Б"}),
            _ev(2, "contradiction", doc=None, detail={"src": "А", "rel": "OWNS", "tgt": "В"})]
    docs = we.group_events(rows, link=_LINK)[0]["docs"]
    assert len(docs) == 2
    assert docs[0]["link"] is None
    assert docs[0]["events"][0]["detail"] == "А OWNS Б"


@pytest.mark.parametrize(("n", "word"), [(1, "событие"), (3, "события"), (5, "событий"),
                                         (11, "событий"), (21, "событие"), (22, "события")])
def test_subject_counts_events_in_russian(n, word):
    subject, _, _ = we.build_email([_ev(i, "new_mention") for i in range(n)], link=_LINK)
    assert subject == f"KB: {n} {word} — Блинов Андрей Степанович"


def test_subject_names_at_most_three_entities():
    rows = [_ev(i, "new_mention", vid=f"v{i}", name=f"Лицо {i}") for i in range(5)]
    subject, _, _ = we.build_email(rows, link=_LINK)
    assert subject.endswith("— Лицо 0, Лицо 1, Лицо 2 (+2)")


def test_html_is_escaped_and_carries_the_link():
    rows = [_ev(1, "new_connection", name="ООО <Ромашка>", detail={"other": "A&B", "rel": "WORKS_AT"})]
    _, text, body = we.build_email(rows, link=_LINK)
    assert "ООО &lt;Ромашка&gt;" in body and "A&amp;B (WORKS_AT)" in body
    assert f'href="http://kb:8000/api/v1/documents/{_DOC}"' in body
    assert "Новая связь: A&B (WORKS_AT) — x" in text


# ── SMTP ─────────────────────────────────────────────────────────────


class _SMTP:
    instances: ClassVar[list[_SMTP]] = []

    def __init__(self, host, port, timeout):
        self.host, self.port, self.timeout = host, port, timeout
        self.sent, self.tls, self.login_as = [], False, None
        _SMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, password):
        self.login_as = user

    def send_message(self, msg):
        self.sent.append(msg)


def test_send_email_builds_a_multipart_letter(monkeypatch):
    _SMTP.instances.clear()
    monkeypatch.setattr(we.smtplib, "SMTP", _SMTP)
    we.send_email(host="mail", port=1025, sender="kb@x", recipients=["a@x", "b@x"],
                  subject="S", text="t", html_body="<p>h</p>")
    smtp = _SMTP.instances[0]
    assert (smtp.host, smtp.port, smtp.tls, smtp.login_as) == ("mail", 1025, False, None)
    msg = smtp.sent[0]
    assert msg["To"] == "a@x, b@x" and msg["Subject"] == "S"
    assert [p.get_content_type() for p in msg.iter_parts()] == ["text/plain", "text/html"]


def test_send_email_uses_starttls_and_login_when_configured(monkeypatch):
    _SMTP.instances.clear()
    monkeypatch.setattr(we.smtplib, "SMTP", _SMTP)
    we.send_email(host="mail", port=587, sender="kb@x", recipients=["a@x"], subject="S",
                  text="t", html_body="h", user="u", password="p", starttls=True)
    assert _SMTP.instances[0].tls and _SMTP.instances[0].login_as == "u"




@pytest.mark.asyncio
async def test_digest_retries_after_smtp_failure_without_repeating_success(monkeypatch):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from src.config import settings
    from src.tenancy.context import default_graph_context

    for name, value in {"email_enabled": True, "email_owner": "owner",
                        "email_smtp_host": "mail", "email_to": "test@example.com"}.items():
        monkeypatch.setattr(settings.monitor, name, value)
    monkeypatch.setattr(act, "_may_read", AsyncMock(return_value=True))
    attempts = []

    def send(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise OSError("SMTP down")

    monkeypatch.setattr(act, "send_email", send)

    class Repo:
        def __init__(self):
            self.pending = [_ev(1, "new_mention")]

        @asynccontextmanager
        async def pending_email(self, principal, **kwargs):
            rows = self.pending[:]
            yield rows
            self.pending = []

    repo = Repo()
    graph = default_graph_context()
    with pytest.raises(OSError):
        await act._deliver_email(repo, graph)
    assert len(repo.pending) == 1
    assert await act._deliver_email(repo, graph) == 1
    assert await act._deliver_email(repo, graph) == 0
    assert len(attempts) == 2


@pytest.mark.asyncio
async def test_digest_requires_authorized_owner_and_default_graph(monkeypatch):
    from unittest.mock import AsyncMock

    from src.config import settings
    from src.tenancy.context import default_graph_context, new_graph_context

    for name, value in {"email_enabled": True, "email_owner": "owner",
                        "email_smtp_host": "mail", "email_to": "a@x"}.items():
        monkeypatch.setattr(settings.monitor, name, value)
    monkeypatch.setattr(act, "_may_read", AsyncMock(return_value=False))
    with pytest.raises(PermissionError):
        await act._deliver_email(object(), default_graph_context())
    assert await act._deliver_email(object(), new_graph_context("alpha")) == 0


def test_partial_smtp_refusal_is_failure(monkeypatch):
    class RefusingSMTP(_SMTP):
        def send_message(self, msg):
            return {"bad@example.com": (550, b"refused")}

    monkeypatch.setattr(we.smtplib, "SMTP", RefusingSMTP)
    with pytest.raises(RuntimeError, match="refused"):
        we.send_email(host="mail", port=25, sender="a@x", recipients=["bad@example.com"],
                      subject="s", text="text", html_body="<p>text</p>")
