"""Entity-watch e-mail digest: letter building, SMTP send, the activity."""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import ClassVar

import pytest

from src.workflow.monitor import activities as act
from src.workflow.monitor import watch_email as we

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


# ── activity ─────────────────────────────────────────────────────────


class _Repo:
    def __init__(self, rows):
        self.rows, self.marked, self.asked = rows, None, None

    async def pending_email(self, owner, *, max_age_hours, limit):
        self.asked = (owner, max_age_hours, limit)
        return self.rows

    async def mark_emailed(self, ids):
        self.marked = ids


@pytest.fixture
def mail(monkeypatch):
    m = act.settings.monitor
    for k, v in {"email_enabled": True, "email_smtp_host": "mailpit", "email_smtp_port": 1025,
                 "email_to": "ops@kb.local, sec@kb.local", "email_base_url": "http://kb:8000"}.items():
        monkeypatch.setattr(m, k, v)
    monkeypatch.setattr(act.settings.api, "document_url", "")
    sent = []
    monkeypatch.setattr(act, "send_email", lambda **kw: sent.append(kw))
    return sent


def _with_repo(monkeypatch, rows):
    repo = _Repo(rows)
    monkeypatch.setattr(act, "WatchRepository", lambda: repo)
    return repo


async def test_disabled_sends_nothing(monkeypatch):
    monkeypatch.setattr(act.settings.monitor, "email_enabled", False)
    assert await act.deliver_watch_email() == act.WatchEmailResult()


async def test_missing_server_or_recipient_is_reported(monkeypatch, mail):
    monkeypatch.setattr(act.settings.monitor, "email_to", " ")
    out = await act.deliver_watch_email()
    assert out.sent == 0 and "MONITOR_EMAIL_TO" in out.error


async def test_one_letter_per_sweep_then_events_are_marked(monkeypatch, mail):
    repo = _with_repo(monkeypatch, [_ev(1, "new_mention"), _ev(2, "new_event")])
    out = await act.deliver_watch_email()
    assert (out.sent, out.events, out.error) == (1, 2, "")
    assert len(mail) == 1
    assert mail[0]["recipients"] == ["ops@kb.local", "sec@kb.local"]
    assert mail[0]["host"] == "mailpit" and mail[0]["port"] == 1025
    assert f"http://kb:8000/api/v1/documents/{_DOC}" in mail[0]["html_body"]
    assert repo.marked == [1, 2]
    assert repo.asked[0] == "default"


async def test_nothing_pending_sends_nothing(monkeypatch, mail):
    _with_repo(monkeypatch, [])
    assert (await act.deliver_watch_email()).sent == 0
    assert mail == []


async def test_smtp_failure_leaves_events_for_the_next_sweep(monkeypatch, mail):
    repo = _with_repo(monkeypatch, [_ev(1, "new_mention")])

    def _down(**kw):
        raise ConnectionRefusedError("mailpit down")

    monkeypatch.setattr(act, "send_email", _down)
    out = await act.deliver_watch_email()
    assert out.sent == 0 and "mailpit down" in out.error
    assert repo.marked is None


async def test_document_title_links_the_original_file_when_configured(monkeypatch, mail):
    original = "http://10.10.113.12:8090/api/documents/{doc_id}?variant=original"
    monkeypatch.setattr(act.settings.api, "document_url", original)
    _with_repo(monkeypatch, [_ev(1, "new_mention")])
    assert (await act.deliver_watch_email()).sent == 1
    body = mail[0]["html_body"]
    assert f"http://10.10.113.12:8090/api/documents/{_DOC}?variant=original" in body
    assert "http://kb:8000" not in body  # absolute: no MONITOR_EMAIL_BASE_URL prefix


def test_email_link_falls_back_to_the_feed_link(monkeypatch):
    m = act.settings.monitor
    monkeypatch.setattr(act.settings.api, "document_url", "")
    monkeypatch.setattr(m, "email_base_url", "http://kb:8000")
    monkeypatch.setattr(m, "document_link", "/api/v1/documents/{doc_id}")
    assert act.watch_email_link() == "http://kb:8000/api/v1/documents/{doc_id}"
