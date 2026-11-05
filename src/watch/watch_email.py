"""Entity-watch e-mail digest: pending watch_event rows -> one letter per sweep.

Pure builder (rows in, subject / text / html out) + a blocking SMTP sender
the activity runs in a thread. Recipients, server and links come from
``settings.monitor`` (``MONITOR_EMAIL_*``). Design:
``docs/superpowers/specs/2026-10-15-entity-watch-design.md``.
"""

from __future__ import annotations

import html
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

KIND_TITLES: dict[str, str] = {
    "new_mention": "Новое упоминание",
    "new_connection": "Новая связь",
    "new_identifier": "Новый идентификатор",
    "new_event": "Новое событие",
    "contradiction": "Противоречие",
}

_SUBJECT_NAMES = 3


def _plural_events(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "событие"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "события"
    return "событий"


def _detail_line(kind: str, detail: dict[str, Any]) -> str:
    if kind == "contradiction":
        return " ".join(str(detail.get(k) or "") for k in ("src", "rel", "tgt")).strip()
    if kind in ("new_connection", "new_identifier", "new_event"):
        other = detail.get("other") or ""
        rel = detail.get("rel") or ""
        return f"{other} ({rel})" if rel else str(other)
    return ""


def group_events(rows: list[dict[str, Any]], *, link: str) -> list[dict[str, Any]]:
    """Entities in order of first appearance; under each, one block per
    document (events without a document get a block each)."""
    entities: dict[str, dict[str, Any]] = {}
    for r in rows:
        ent = entities.setdefault(r["entity_vid"], {"name": r["entity_name"], "docs": {}})
        doc = str(r["doc_id"]) if r.get("doc_id") else None
        key = doc or f"event:{r['id']}"
        block = ent["docs"].get(key)
        if block is None:
            path = r.get("doc_path") or ""
            block = ent["docs"][key] = {
                "title": path.rsplit("/", 1)[-1] if path else None,
                "doc_date": r.get("doc_date"),
                "link": link.format(doc_id=doc) if doc else None,
                "events": [],
            }
        block["events"].append({
            "kind": r["kind"],
            "title": KIND_TITLES.get(r["kind"], r["kind"]),
            "detail": _detail_line(r["kind"], r.get("detail") or {}),
            "why": r.get("why") or "",
        })
    return [{"name": e["name"], "docs": list(e["docs"].values())} for e in entities.values()]


def build_email(rows: list[dict[str, Any]], *, link: str) -> tuple[str, str, str]:
    """(subject, plain text, html) for one digest of pending events."""
    groups = group_events(rows, link=link)
    names = [g["name"] for g in groups]
    shown = ", ".join(names[:_SUBJECT_NAMES])
    more = f" (+{len(names) - _SUBJECT_NAMES})" if len(names) > _SUBJECT_NAMES else ""
    subject = f"KB: {len(rows)} {_plural_events(len(rows))} — {shown}{more}"

    text: list[str] = []
    parts: list[str] = [
        "<div style=\"font-family:Arial,sans-serif;font-size:14px;color:#1a1a1a\">",
    ]
    for g in groups:
        text.append(f"== {g['name']} ==")
        parts.append(f"<h2 style=\"font-size:18px;margin:16px 0 8px\">{html.escape(g['name'])}</h2>")
        for d in g["docs"]:
            head = d["title"] or "без документа"
            if d["doc_date"]:
                head += f" · {d['doc_date']}"
            text.append(f"  {head}" + (f"  {d['link']}" if d["link"] else ""))
            title = html.escape(head)
            if d["link"]:
                title = f"<a href=\"{html.escape(d['link'], quote=True)}\">{title}</a>"
            parts.append(f"<p style=\"margin:8px 0 4px\"><b>{title}</b></p><ul style=\"margin:0 0 8px\">")
            for ev in d["events"]:
                line = ev["title"] + (f": {ev['detail']}" if ev["detail"] else "")
                text.append(f"    - {line}" + (f" — {ev['why']}" if ev["why"] else ""))
                why = f" <span style=\"color:#5d6470\">— {html.escape(ev['why'])}</span>" if ev["why"] else ""
                parts.append(f"<li>{html.escape(line)}{why}</li>")
            parts.append("</ul>")
        text.append("")
    parts.append("</div>")
    return subject, "\n".join(text).rstrip() + "\n", "".join(parts)


def send_email(
    *, host: str, port: int, sender: str, recipients: list[str], subject: str,
    text: str, html_body: str, user: str = "", password: str = "",
    starttls: bool = False, timeout_s: float = 10.0,
) -> None:
    """Blocking SMTP send; raises on failure (the activity runs it in a thread)."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(text)
    msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP(host, port, timeout=timeout_s) as smtp:
        if starttls:
            smtp.starttls(context=ssl.create_default_context())
        if user:
            smtp.login(user, password)
        refused = smtp.send_message(msg)
        if refused:
            raise RuntimeError("SMTP refused one or more recipients")


__all__ = ["KIND_TITLES", "build_email", "group_events", "send_email"]
