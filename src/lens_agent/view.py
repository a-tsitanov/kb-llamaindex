"""What the model sees of a source result: numbered rows, a coverage header, the resolution.

A character cut of the raw JSON (the old view) drops rows mid-way and hides how much was left
out, so a small model presents the first 15 of 188 neighbours as "all". When a result has
entity rows (see ``rows``), the model instead gets:

    call_id=c3
    ⚠ «Росатом» в базе называется «Rosatom» (совпадение: translit) — используй это имя
    meta: {"centre_found": true, "best_relevance": 0.93}
    сущности 0–14 из 188, связи 12 из 240 — ещё: more(call_id="c3", offset=15)
    [0] Rosatom (Organization) — госкорпорация … | 0.93 strong
    [1] Алексей Лихачёв (Person) — глава Росатома | 0.88 strong
    связи:
    Алексей Лихачёв —HEADS→ Rosatom

Row numbers are ``Row.index`` of ``rows.entity_rows`` — what ``board_add_objects`` accepts
as ``row``. Results without entity rows keep the plain character cut.
"""

from __future__ import annotations

import json
from typing import Any

from src.lens.keys import normalize_id
from src.lens_agent.rows import Row, entity_rows, relation_rows

DESC_CHARS = 100


def _resolution_line(res: Any) -> str:
    if not isinstance(res, dict):
        return ""
    q = str(res.get("query") or "")
    chosen = res.get("chosen") if isinstance(res.get("chosen"), dict) else {}
    alts = [str(a.get("name")) for a in res.get("alternatives") or [] if isinstance(a, dict)]
    status = res.get("status")
    if status == "not_found":
        tail = f"; похожие: {', '.join(alts[:5])}" if alts else ""
        return f"⚠ «{q}» в базе не найдено{tail} — не делай вывод «нет данных» по этому имени"
    if status == "ambiguous":
        names = [str(chosen.get("name")), *alts]
        return (f"⚠ «{q}» неоднозначно: {', '.join(n for n in names[:5] if n)} — "
                "повтори с точным именем одного из кандидатов")
    name = str(chosen.get("name") or "")
    if name and normalize_id(name) != normalize_id(q):
        via = ", ".join(chosen.get("matched_via") or [])
        return (f"⚠ «{q}» в базе называется «{name}» (совпадение: {via}) — "
                "используй это имя")
    return ""


def _order_line(payload: dict) -> str:
    if payload.get("rank_timeout"):
        return ("⚠ порядок строк НЕ по вопросу (ранжирование не успело) — первые строки не "
                "обязательно ответ; сузь запрос или проверь другим инструментом")
    if payload.get("relevance_note"):
        return ("⚠ ничего не подходит к вопросу (лучшая оценка "
                f"{payload.get('best_relevance')}) — не выдавай эти строки как ответ")
    return ""


def _meta(payload: dict) -> str:
    meta = {k: v for k, v in payload.items()
            if k != "resolution" and not isinstance(v, list | dict)}
    closest = payload.get("closest")
    if isinstance(closest, list) and closest:
        meta["closest"] = closest
    return f"meta: {json.dumps(meta, ensure_ascii=False)}" if meta else ""


def _entity_line(row: Row, extra: dict[str, Any]) -> str:
    head = f"[{row.index}] {row.label}" + (f" ({row.type})" if row.type else "")
    if row.id != row.label:
        head += f" id={row.id}"
    desc = " ".join(row.description.split())[:DESC_CHARS]
    if desc:
        head += f" — {desc}"
    rel = extra.get(row.id)
    if rel is not None:
        head += f" | {rel}"
    return head


def _scores(payload: Any) -> dict[str, str]:
    """entity id -> "0.93 strong" for ranked rows (kb-tools ``relevance`` / ``match``)."""
    out: dict[str, str] = {}
    ents = payload.get("entities") if isinstance(payload, dict) else None
    for e in ents if isinstance(ents, list) else []:
        if isinstance(e, dict) and "relevance" in e:
            rid = e.get("id") or e.get("entity_name") or e.get("name")
            out[str(rid)] = f"{e['relevance']} {e.get('match', '')}".strip()
    return out


def render(cid: str, payload: Any, budget: int, offset: int = 0) -> tuple[str, bool] | None:
    """→ (model text, truncated) or None when the payload has no entity rows."""
    rows = entity_rows(payload)
    if not rows:
        return None
    rels = relation_rows(payload)
    lines = [f"call_id={cid}"]
    if isinstance(payload, dict) and offset == 0:  # pages after the first: rows only
        lines += [x for x in (_resolution_line(payload.get("resolution")),
                              _order_line(payload), _meta(payload)) if x]
    scores = _scores(payload)
    head_len = sum(len(x) + 1 for x in lines) + 120
    body: list[str] = []
    used, shown = head_len, []
    ent_budget = int(budget * 0.7)
    for row in rows[offset:]:
        line = _entity_line(row, scores)
        if used + len(line) + 1 > ent_budget and shown:
            break
        body.append(line)
        used += len(line) + 1
        shown.append(row)
    names = {n for r in shown for n in r.names}
    rel_lines = []
    shown_rels = 0
    for r in rels:
        if normalize_id(r.src) not in names and normalize_id(r.tgt) not in names:
            continue
        line = f"{r.src} —{r.kind or 'связь'}→ {r.tgt}"
        if used + len(line) + 1 > budget:
            break
        rel_lines.append(line)
        used += len(line) + 1
        shown_rels += 1
    end = offset + len(shown)
    more = end < len(rows)
    cover = f"сущности {offset}–{end - 1} из {len(rows)}"
    if rels:
        cover += f", связи {shown_rels} из {len(rels)}"
    if more:
        cover += f" — ещё: more(call_id=\"{cid}\", offset={end})"
    else:
        cover += " — показано всё"
    lines.append(cover)
    lines += body
    if rel_lines:
        lines += ["связи:", *rel_lines]
    return "\n".join(lines), more or shown_rels < len(rels)
