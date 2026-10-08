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
2. Команды доски («скрой», «покажи», «отмени») выполняй только инструментами доски \
(board_hide, board_show, board_undo), без поиска в источниках. Объединять объекты ты не \
можешь — это делает пользователь.
3. Ищи в источниках; соседей бери на 1 шаг; не повторяй одинаковые вызовы. Если у \
инструмента есть параметр query — передавай туда вопрос пользователя (результаты придут \
отсортированными по смыслу вопроса). Результат приходит нумерованными строками [N] с \
заголовком «сущности … из M»: если показано не всё — листай more(call_id, offset), это не \
новый поиск. Строка «⚠» — важное: имя в базе другое (используй его), не найдено или \
неоднозначно (выбери кандидата и повтори).
4. На доску клади только то, что отвечает на вопрос (обычно до 20 объектов). \
board_add_objects: для каждого объекта укажи call_id результата источника и номер строки \
row (или её id точно как в результате); название, тип и описание доска возьмёт из \
источника сама. Если сущности нет в результате — её нельзя добавить (в ответе будут \
ближайшие строки). board_add_relations: from и to — ключи объектов доски; связь пройдёт, \
только если она есть в источнике (проще всего: сначала find_neighbours объекта, связи — из \
его результата). Для объектов доски с пометкой «в источнике: X» \
используй X как имя сущности в инструментах источника.
5. Не добавляй фактов, которых нет в результатах инструментов.
6. Закончи коротким ответом (до 5 предложений) на языке пользователя; объекты с доски \
упоминай как [[ключ]]."""


def _words(s: str) -> list[str]:
    return [w for w in normalize_id(s).replace("«", " ").replace("»", " ").split() if len(w) >= 4]


def _coverage(a: list[str], b: list[str]) -> float:
    """Mean over the words of ``a`` of their best similarity to a word of ``b``."""
    if not a or not b:
        return 0.0
    return sum(max(SequenceMatcher(None, x, y).ratio() for y in b) for x in a) / len(a)


def _score(query: str, label: str) -> float:
    """Typo-tolerant similarity: the whole strings, or how well the words of one side are
    covered by the other (so one shared common word in a long request is not a match)."""
    q, lab = _words(query), _words(label)
    whole = SequenceMatcher(None, normalize_id(query), normalize_id(label)).ratio()
    return max(whole, _coverage(q, lab), _coverage(lab, q))


def similar_objects(query: str, objects: list[dict], *, limit: int = 5,
                    cutoff: float = 0.85) -> list[dict]:
    """Board objects whose label looks like the request (typos, ё/е, word order): the model
    otherwise "corrects" a typo to some other entity instead of the one on the board.
    ``cutoff`` keeps near-misses of a different entity out («ростатом» → «Росстат» is 0.8)."""
    if not query.strip():
        return []
    scored = [(s, o) for o in objects if (s := _score(query, str(o.get("label") or ""))) >= cutoff]
    scored.sort(key=lambda so: -so[0])
    return [o for _, o in scored[:limit]]


def _line(o: dict) -> str:
    sid = o.get("source_id") or (o.get("attrs") or {}).get("source_id")
    tail = f", в источнике: {sid}" if sid else ""
    return f"- {o['key']} — {o.get('label') or '?'} ({o.get('type') or '?'}){tail}"


def _lines(objs: list[dict]) -> str:
    return "\n".join(_line(o) for o in objs)


def _resolved_line(r: dict) -> str:
    kind = f"{r['label']}, " if r.get("label") else ""
    via = ", ".join(r.get("matched_via") or [])
    same = normalize_id(r["span"]) == normalize_id(r["name"])
    head = f"«{r['name']}»" if same else f"«{r['span']}» → «{r['name']}»"
    return f"- {head} ({kind}{r.get('source', '?')}; совпадение: {via})"


def user_prompt(text: str, mentions: list[dict], similar: list[dict] | None = None,
                resolved: list[dict] | None = None) -> str:
    """``mentions``: ``[{key, label, type}]`` resolved from the board (label may be None);
    ``similar``: board objects whose label resembles the request; ``resolved``: names of the
    request found in a source before the run (``[{span, name, label, matched_via, source}]``)."""
    out = text
    if mentions:
        out += "\n\nУпомянутые объекты доски:\n" + _lines(mentions)
    if similar:
        out += "\n\nПохожие объекты на доске (вероятно, речь о них):\n" + _lines(similar)
    if resolved:
        out += ("\n\nИмена из запроса, найденные в источниках (в инструментах используй имя "
                "справа):\n" + "\n".join(_resolved_line(r) for r in resolved))
    return out
