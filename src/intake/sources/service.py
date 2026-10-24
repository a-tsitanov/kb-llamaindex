"""Подключение источников по коду подтверждения.

`apply_proposal` открывает только то, что пользователь одобрил в
предложении: канал и ПАПКУ берутся из элемента предложения, а аргумент
`peer_ids` лишь сужает набор. Запись в реестр идёт после успеха на стороне
телеграма: строка о канале, в котором нас нет, заставила бы свип ждать
сообщений, которых не будет.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, NamedTuple

from loguru import logger

from src.intake.client import FAILED, SENT, post_document
from src.intake.sources.messages import ingest_form, message_to_doc
from src.intake.sources.proposals import (
    CONNECT,
    LEAVE,
    MOVE,
    BadProposal,
    Proposal,
    ProposalStore,
    SourceInputError,
    SourceNotFound,
)
from src.intake.sources.repository import SourceRepository, SourceRow
from src.intake.sources.telegram import (
    FloodWait,
    FolderNotEditable,
    FolderNotFound,
    TelegramOps,
)
from src.retrieval.groups import GROUP_SET


class AmbiguousMove(RuntimeError):
    """Перенос оборвался с неясным состоянием папок аккаунта.

    Текст читает человек; машинам — поля: `old`, `new` (папки) и `seconds` —
    сколько просит подождать телеграм, если причиной был `FloodWait`, иначе
    `None`.
    """

    def __init__(self, message: str, *, old: str, new: str, seconds: int | None = None) -> None:
        super().__init__(message)
        self.old = old
        self.new = new
        self.seconds = seconds


class ApplyResult(NamedTuple):
    connected: list[int]
    skipped: list[tuple[int, str]]
    bootstrapped: int
    # подключены (есть в connected), но историю дочитал не весь обход
    partial: tuple[tuple[int, str], ...] | list[tuple[int, str]] = ()
    # peer_id -> наибольший id сообщения, который подтянула история при
    # подключении. Курсор свипа должен стать не меньше: иначе первый же
    # раунд перечитал бы и перепостил те же сообщения (получив 409 на каждое
    # и ложное «канал репостит сам себя»). Канала, чья история ничего не
    # дала, здесь нет.
    cursors: Mapping[int, int] = MappingProxyType({})


async def apply_proposal(
    store: ProposalStore,
    ops: TelegramOps,
    repo: SourceRepository,
    proposal_id: str,
    code: str,
    peer_ids: list[int] | None,
    *,
    added_by: str,
    bootstrap: int,
    http: Any,
    api_base: str,
    api_key: str,
    graph: str | None = None,
    on_cursor: Callable[[int, int], None] | None = None,
) -> ApplyResult:
    """Вступить, положить в папку, записать в реестр и подтянуть историю.

    Неверный код, просрочка и повтор поднимают `BadProposal` до единого
    обращения к телеграму. `FloodWait` обход прекращает: остаток уходит в
    `skipped`, уже подключённые остаются в `connected` и в реестре.
    Любой сбой по каналу (папка, `RPCError`, реестр) кладёт его в `skipped` и
    не роняет вызов; если вступление уже состоялось, оно отменяется `leave`,
    а провал отмены оговаривается в причине. Канал, уже активный в реестре,
    не отменяется: там членство старше этого вызова. `FloodWait` на чтении истории
    оставляет канал в `connected` и отмечает его в `partial`.
    `bootstrapped` считает документы, принятые приёмом как новые
    (дубликат и сбой в счёт не идут).

    ``cursors`` в результате и ``on_cursor(peer_id, last_id)`` (вызывается
    сразу после истории канала, до перехода к следующему) называют, докуда
    дочитана история: фидер переносит это в курсор свипа. Курсор идёт до
    первого сбоя отправки (свип повторит его с этого сообщения) и включает
    пустые сообщения и дубликаты, как и курсор свипа.
    """
    proposal = store.take(proposal_id, code, CONNECT)
    by_peer = {it.peer_id: it for it in proposal.items}
    wanted = list(by_peer) if peer_ids is None else list(dict.fromkeys(peer_ids))

    connected: list[int] = []
    skipped: list[tuple[int, str]] = []
    partial: list[tuple[int, str]] = []
    bootstrapped = 0
    cursors: dict[int, int] = {}
    flood: FloodWait | None = None

    for peer_id in wanted:
        item = by_peer.get(peer_id)
        if item is None:
            skipped.append((peer_id, "канала нет в предложении"))
            continue
        if flood is not None:
            skipped.append((peer_id, _flood_reason(flood)))
            continue
        joined = False
        in_folder = False
        # Канал уже активен в реестре — значит в нём состоит не этот вызов, а
        # прошлое подключение. Откат тогда запрещён: выйдя, мы оставили бы
        # активную строку о канале, из которого нас нет, и свип ждал бы
        # сообщений, которых не будет.
        was_active = False
        try:
            known = await repo.get(peer_id)
            was_active = known is not None and known.state == "active"
            await ops.join(peer_id)
            joined = True
            logger.info("sources: вступили в {p} ({s})", p=peer_id, s=item.slug)
            await ops.add_to_folder(peer_id, item.group_name)
            in_folder = True
            await repo.add(
                peer_id, item.slug, item.title, item.group_name, added_by=added_by,
            )
        # BaseException, а не Exception: отмена вызова (клиент отвалился, пока
        # раунд свипа держал замок) приходит как CancelledError, и без отката
        # аккаунт остался бы в канале, о котором реестр не знает.
        except BaseException as exc:
            if isinstance(exc, FloodWait):
                flood = exc
            reason = _reason(exc)
            if joined and was_active:
                reason += "; канал уже был в реестре, из канала не выходим"
            else:
                reason = await _rollback(
                    ops, peer_id, joined, reason,
                    folder=item.group_name if in_folder else None,
                )
            if not isinstance(exc, Exception):
                # отмену не глотаем: след в логе и дальше наверх
                logger.warning(
                    "sources: вызов прерван ({e}) на канале {p}: {r}",
                    e=type(exc).__name__, p=peer_id, r=reason,
                )
                raise
            skipped.append((peer_id, reason))
            continue
        logger.info(
            "sources: канал {p} подключён (папка {g})", p=peer_id, g=item.group_name,
        )
        connected.append(peer_id)
        if bootstrap <= 0:
            continue
        try:
            messages = await ops.history(peer_id, bootstrap)
        except FloodWait as exc:
            # вступили и записали — канал подключён; историю дочитает свип
            flood = exc
            partial.append((peer_id, f"история не подтянута: {_flood_reason(exc)}"))
            continue
        sent, cursor = await _bootstrap(
            messages, item.slug or str(peer_id), item.group_name,
            http=http, api_base=api_base, api_key=api_key, graph=graph,
        )
        bootstrapped += sent
        if cursor is not None:
            cursors[peer_id] = cursor
            if on_cursor is not None:
                on_cursor(peer_id, cursor)
    return ApplyResult(connected, skipped, bootstrapped, partial, cursors)


async def move_source(
    store: ProposalStore,
    ops: TelegramOps,
    repo: SourceRepository,
    proposal_id: str,
    code: str,
    peer_id: int,
    folder: str,
) -> None:
    """Переложить канал в другую папку по коду подтверждения.

    Папки агент не создаёт: допустима только группа из `GROUP_SET`, иначе
    отказ `ValueError`. Канал должен быть активным в реестре (`LookupError`
    иначе); текущая папка — `group_name` его строки (если она назвает папку,
    где канала нет, снятие вернёт «не найден» и перенос всё равно завершится).

    Порядок проверок: папка, реестр, код, привязка кода к каналу, телеграм.
    Неверный код и код, выданный на другой канал (`BadProposal`), сжигают
    предложение; кривое имя папки и неизвестный или вышедший канал — нет.

    Код привязан к действию `move`: код на вступление или выход — отказ
    `BadProposal`, предложение гасится.

    Порядок правок: сначала в новую папку, потом из старой, потом реестр —
    канал ни в какой момент не остаётся вовсе без папки. Снятие из старой
    папки с `FolderNotFound` — канала там нет, идём дальше (при сбое реестра
    его туда и не возвращаем). `FolderNotEditable` (общий список) — канал
    по-прежнему в старой папке: ошибка, реестр не трогается. Любой другой
    сбой снятия НЕ отменяется: запрос мог дойти до сервера, отмена оставила бы
    канал вообще без папки; поднимается `AmbiguousMove`, канал может лежать в
    обеих папках, реестр называет старую, повтор переноса сходится (операции с
    папками идемпотентны). Сбой записи в реестр отменяется (вернуть старую,
    снять новую); если отмена не удалась, `AmbiguousMove` называет, какой шаг
    упал и где канал теперь. Документы и курсор диалога не трогаются.
    """
    if folder not in GROUP_SET:
        raise SourceInputError(f"папка {folder!r} вне допустимых групп: {sorted(GROUP_SET)}")
    row = await _active_row(repo, peer_id)
    _bind(store.take(proposal_id, code, MOVE), peer_id)
    old = row.group_name
    if old == folder:
        return
    await ops.add_to_folder(peer_id, folder)
    # Снятие само говорит, тронуло ли оно папку: канала там могло не быть, и
    # тогда отменять нечего — иначе отмена положила бы его в папку, где его
    # никогда не было.
    was_in_old = True
    try:
        was_in_old = await ops.remove_from_folder(peer_id, old)
    except FolderNotEditable as exc:
        # общий список не правится: канал по-прежнему в старой папке, а новая
        # уже приняла его; реестр не трогаем, чтобы он не расходился с аккаунтом
        raise FolderNotEditable(
            f"папка {old!r} — общий список (chatlist), её состав не правится, "
            f"канал {peer_id} по-прежнему в ней и уже добавлен в {folder!r}; "
            f"реестр по-прежнему называет {old!r}",
            folder=old,
        ) from exc
    except FolderNotFound:
        was_in_old = False  # канала там и не было — переносить из неё нечего
    except Exception as exc:
        raise AmbiguousMove(
            f"снятие {peer_id} из папки {old!r} оборвалось ({_reason(exc)}), отмена не "
            f"делалась: канал может лежать в обеих папках ({old!r} и {folder!r}), "
            f"реестр по-прежнему называет {old!r}; повтор переноса сходится",
            old=old, new=folder,
            seconds=exc.seconds if isinstance(exc, FloodWait) else None,
        ) from exc
    try:
        if not await repo.set_group(peer_id, folder):
            raise SourceNotFound(f"источник {peer_id} пропал из реестра при переносе")
    except Exception as exc:
        readd = await _undo(ops.add_to_folder, peer_id, old) if was_in_old else None
        unadd = await _undo(ops.remove_from_folder, peer_id, folder)
        if readd is None and unadd is None:
            raise
        raise AmbiguousMove(
            f"{exc}; {_undo_report(peer_id, old, folder, was_in_old, readd, unadd)}",
            old=old, new=folder,
            seconds=next(
                (e.seconds for e in (readd, unadd) if isinstance(e, FloodWait)), None,
            ),
        ) from exc


def _undo_report(
    peer_id: int, old: str, new: str, was_in_old: bool,
    readd: Exception | None, unadd: Exception | None,
) -> str:
    """Что не удалось отменить и где теперь канал; реестр называет `old`."""
    failed = []
    if readd is not None:
        failed.append(f"возврат в {old!r}: {_reason(readd)}")
    if unadd is not None:
        failed.append(f"снятие с {new!r}: {_reason(unadd)}")
    if readd is not None and unadd is None:
        where = f"ни в одной из папок ({old!r}, {new!r})"
    elif readd is None and unadd is not None:
        where = f"в обеих папках ({old!r} и {new!r})" if was_in_old else (
            f"только в новой ({new!r})"
        )
    else:
        where = f"только в новой ({new!r})"
    note = "" if was_in_old else (
        f"; в {old!r} канала не было, его туда не возвращали"
    )
    return (
        f"отмена переноса {peer_id} не удалась ({'; '.join(failed)}): "
        f"канал лежит {where}, реестр называет {old!r}{note}"
    )


async def leave_source(
    store: ProposalStore,
    ops: TelegramOps,
    repo: SourceRepository,
    proposal_id: str,
    code: str,
    peer_id: int,
) -> None:
    """Выйти из канала по коду подтверждения и пометить его `left`.

    Порядок проверок: реестр, код, привязка кода к каналу, телеграм. Неверный
    код и код, выданный на другой канал (`BadProposal`), сжигают предложение;
    неизвестный или уже вышедший канал (`LookupError`) — нет.

    Строка и уже принятые документы остаются, доверие тоже; приём не
    вызывается вовсе. Сбой выхода оставляет строку активной. Если выход
    удался, а реестр не записался, поднимается ошибка реестра: аккаунт уже
    вне канала, строка ещё `active`, повтор вызова потребует нового кода.
    """
    await _active_row(repo, peer_id)
    _bind(store.take(proposal_id, code, LEAVE), peer_id)
    await ops.leave(peer_id)
    if not await repo.mark_left(peer_id):
        raise SourceNotFound(f"источник {peer_id} пропал из реестра при выходе")


async def set_source_trust(
    repo: SourceRepository, peer_id: int, trust: float | None,
) -> SourceRow:
    """Личное доверие к каналу: `0..1` или `None` («как у группы»).

    Кода нет: телеграм-аккаунт не меняется, пишется только наша таблица.
    Число действует вперёд — записанные связи не перештамповываются, поэтому
    доверие ставится и каналу со строкой `left`. `bool` и не-числа отклоняются.
    """
    if trust is not None:
        if isinstance(trust, bool) or not isinstance(trust, (int, float)):
            raise SourceInputError(f"доверие должно быть числом или None, получено {trust!r}")
        if not (math.isfinite(trust) and 0.0 <= trust <= 1.0):
            raise SourceInputError(f"доверие должно быть в [0, 1] или None, получено {trust!r}")
    if await repo.get(peer_id) is None:
        raise SourceNotFound(f"источник {peer_id} не подключён")
    await repo.set_trust(peer_id, trust)
    row = await repo.get(peer_id)
    if row is None:
        raise SourceNotFound(f"источник {peer_id} пропал из реестра")
    return row


def _bind(proposal: Proposal, peer_id: int) -> None:
    """Код выдан на конкретные каналы: чужой peer_id — это злоупотребление."""
    if peer_id not in {it.peer_id for it in proposal.items}:
        raise BadProposal(
            f"канал {peer_id} не входит в предложение; предложение погашено"
        )


async def _active_row(repo: SourceRepository, peer_id: int) -> SourceRow:
    """Предложение разрешает лишь известное реестру: чужой peer_id — отказ."""
    row = await repo.get(peer_id)
    if row is None or row.state != "active":
        raise SourceNotFound(f"источник {peer_id} не подключён")
    return row


async def _undo(op: Any, peer_id: int, folder: str) -> Exception | None:
    """Отмена правки папки; сбой возвращается, чтобы попасть в ошибку."""
    try:
        await op(peer_id, folder)
    except Exception as exc:
        logger.warning(
            "отмена правки папки {f} для {p} не удалась: {e!r}", f=folder, p=peer_id, e=exc,
        )
        return exc
    return None


def _reason(exc: BaseException) -> str:
    if isinstance(exc, FloodWait):
        return _flood_reason(exc)
    if isinstance(exc, FolderNotFound):
        return f"папка не найдена: {exc}"
    return f"{type(exc).__name__}: {exc}"


async def _rollback(
    ops: TelegramOps, peer_id: int, joined: bool, reason: str,
    *, folder: str | None = None,
) -> str:
    """Выйти из канала, если вступили, а записать не удалось: членство без
    строки реестра никто не увидит. Сбой выхода — в причину, нужна ручная чистка.

    ``folder`` — папка, в которую канал уже успели положить: её запись тоже
    снимается, иначе в папке пользователя остался бы канал, которого нет ни в
    аккаунте, ни в реестре. Сбой снятия называет остаток в причине."""
    if not joined:
        return reason
    leftovers: list[str] = []
    try:
        await ops.leave(peer_id)
    except Exception as exc:
        logger.warning("откат вступления {p} не удался: {e!r}", p=peer_id, e=exc)
        leftovers.append(
            f"выйти из канала не удалось ({type(exc).__name__}: {exc}), "
            "аккаунт остался в канале"
        )
    if folder is not None:
        try:
            await ops.remove_from_folder(peer_id, folder)
        except FolderNotEditable as exc:
            leftovers.append(
                f"из папки {folder!r} убрать не удалось ({exc}), канал остался в папке"
            )
        except FolderNotFound:
            pass  # папки уже нет — убирать нечего
        except Exception as exc:
            logger.warning(
                "снятие {p} с папки {f} при откате не удалось: {e!r}",
                p=peer_id, f=folder, e=exc,
            )
            leftovers.append(
                f"из папки {folder!r} убрать не удалось "
                f"({type(exc).__name__}: {exc}), канал остался в папке"
            )
    if leftovers:
        return f"{reason}; {'; '.join(leftovers)} — нужна ручная чистка"
    return f"{reason}; вступление отменено"


def _flood_reason(exc: FloodWait) -> str:
    return f"FloodWait: телеграм просит подождать {exc.seconds} с"


async def _bootstrap(
    messages: list[Any], slug: str, group: str,
    *, http: Any, api_base: str, api_key: str, graph: str | None,
) -> tuple[int, int | None]:
    """Отправить сообщения так же, как свип (`scripts/tg_ingest.py::sync_round`):
    от старых к новым, имя и дата — `message_to_doc`, поля — `ingest_form`
    (`channel` без «@», `group` папки).

    Возвращает (принято приёмом новыми, курсор). Курсор — наибольший id среди
    сообщений до первого сбоя отправки; `None`, если не дошло ни до одного."""
    sent = 0
    cursor: int | None = None
    failed = False
    for msg in sorted(messages, key=lambda m: m.id):
        doc = message_to_doc(msg, slug)
        if doc is None:
            if not failed:
                cursor = msg.id
            continue
        filename, text, document_date = doc
        res = await post_document(
            http, api_base, api_key,
            filename=filename, content=text.encode("utf-8"),
            data=ingest_form(document_date, group=group, channel=slug.lstrip("@")),
            graph=graph,
        )
        if res.outcome == FAILED:
            failed = True  # свип повторит с этого сообщения
        elif not failed:
            cursor = msg.id
        if res.outcome == SENT:
            sent += 1
        else:
            logger.info("bootstrap {f}: {o}", f=filename, o=res.outcome)
    return sent, cursor
