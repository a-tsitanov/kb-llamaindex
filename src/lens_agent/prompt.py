"""Agent instructions and the per-run user prompt."""

from __future__ import annotations

from difflib import SequenceMatcher

from src.lens.keys import normalize_id

INSTRUCTIONS = """\
Ты — исследователь на доске объектов. Пользователь задаёт вопрос; ты находишь ответ в \
источниках и выкладываешь на доску только то, что на него отвечает.

Порядок работы:
1. Сначала вызови board_get_board — посмотри, что уже на доске. Упомянутые пользователем \
объекты даны в запросе (ключ и название). Если в запросе перечислены похожие объекты \
доски — запрос про них (опечатка или другое написание), не толкуй его иначе. Повторно \
доску не запрашивай, пока ничего на неё не добавил.
2. Команды доски («скрой», «покажи», «отмени», «это одно и то же») выполняй только \
инструментами доски (board_hide, board_show, board_undo, board_merge), без поиска в источниках.
3. Ищи в источниках; соседей бери на 1 шаг; не повторяй одинаковые вызовы.
4. На доску клади только то, что отвечает на вопрос (обычно до 20 объектов): \
board_add_objects с id, type, label, call_id (из строки «call_id=…» результата источника), \
затем board_add_relations между ключами из ответа board_add_objects.
5. Не добавляй фактов, которых нет в результатах инструментов.
6. Закончи коротким ответом (до 5 предложений) на языке пользователя; объекты с доски \
упоминай как [[ключ]]."""


def _score(query: str, label: str) -> float:
    """Typo-tolerant similarity: whole label, or the best word pair (words of ≥4 chars)."""
    q, lab = normalize_id(query), normalize_id(label)
    best = SequenceMatcher(None, q, lab).ratio()
    for qw in (w for w in q.split() if len(w) >= 4):
        for lw in (w for w in lab.split() if len(w) >= 4):
            best = max(best, SequenceMatcher(None, qw, lw).ratio())
    return best


def similar_objects(query: str, objects: list[dict], *, limit: int = 5,
                    cutoff: float = 0.8) -> list[dict]:
    """Board objects whose label looks like the request (typos, ё/е, word order): the model
    otherwise "corrects" a typo to some other entity instead of the one on the board."""
    if not query.strip():
        return []
    scored = [(s, o) for o in objects if (s := _score(query, str(o.get("label") or ""))) >= cutoff]
    scored.sort(key=lambda so: -so[0])
    return [o for _, o in scored[:limit]]


def _lines(objs: list[dict]) -> str:
    return "\n".join(f"- {o['key']} — {o.get('label') or '?'} ({o.get('type') or '?'})"
                     for o in objs)


def user_prompt(text: str, mentions: list[dict], similar: list[dict] | None = None) -> str:
    """``mentions``: ``[{key, label, type}]`` resolved from the board (label may be None);
    ``similar``: board objects whose label resembles the request."""
    out = text
    if mentions:
        out += "\n\nУпомянутые объекты доски:\n" + _lines(mentions)
    if similar:
        out += "\n\nПохожие объекты на доске (вероятно, речь о них):\n" + _lines(similar)
    return out
