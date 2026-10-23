"""Подключение источников по коду подтверждения.

`apply_proposal` открывает только то, что пользователь одобрил в
предложении: канал и ПАПКУ берутся из элемента предложения, а аргумент
`peer_ids` лишь сужает набор. Запись в реестр идёт после успеха на стороне
телеграма: строка о канале, в котором нас нет, заставила бы свип ждать
сообщений, которых не будет.
"""

from __future__ import annotations

import math
from typing import Any, NamedTuple

from loguru import logger

from src.intake.client import SENT, post_document
from src.intake.sources.messages import ingest_form, message_to_doc
from src.intake.sources.proposals import ProposalStore
from src.intake.sources.repository import SourceRepository, SourceRow
from src.intake.sources.telegram import FloodWait, FolderNotFound, TelegramOps
from src.retrieval.groups import GROUP_SET


class ApplyResult(NamedTuple):
    connected: list[int]
    skipped: list[tuple[int, str]]
    bootstrapped: int
    # подключены (есть в connected), но историю дочитал не весь обход
    partial: tuple[tuple[int, str], ...] | list[tuple[int, str]] = ()


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
    """
    proposal = store.take(proposal_id, code)
    by_peer = {it.peer_id: it for it in proposal.items}
    wanted = list(by_peer) if peer_ids is None else list(dict.fromkeys(peer_ids))

    connected: list[int] = []
    skipped: list[tuple[int, str]] = []
    partial: list[tuple[int, str]] = []
    bootstrapped = 0
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
            await ops.add_to_folder(peer_id, item.group_name)
            await repo.add(
                peer_id, item.slug, item.title, item.group_name, added_by=added_by,
            )
        except Exception as exc:  # сбой одного канала не должен ронять обход
            if isinstance(exc, FloodWait):
                flood = exc
            reason = _reason(exc)
            if joined and was_active:
                reason += "; канал уже был в реестре, из канала не выходим"
            else:
                reason = await _rollback(ops, peer_id, joined, reason)
            skipped.append((peer_id, reason))
            continue
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
        bootstrapped += await _bootstrap(
            messages, item.slug or str(peer_id), item.group_name,
            http=http, api_base=api_base, api_key=api_key, graph=graph,
        )
    return ApplyResult(connected, skipped, bootstrapped, partial)


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
    отказ `ValueError` ДО кода и телеграма (предложение не сгорает). Неверный
    код — `BadProposal` до единого обращения к аккаунту. Канал должен быть
    активным в реестре (`LookupError` иначе); текущая папка — `group_name`
    его строки.

    Порядок: сначала в новую папку, потом из старой, потом реестр — канал ни
    в какой момент не остаётся вовсе без папки. Сбой на любом шаге отменяет
    уже сделанное (best-effort) и поднимается наверх; реестр меняется
    последним. Если отмена тоже не удалась, канал лежит сразу в двух папках,
    а реестр называет старую. Документы и курсор диалога не трогаются.
    """
    if folder not in GROUP_SET:
        raise ValueError(f"папка {folder!r} вне допустимых групп: {sorted(GROUP_SET)}")
    store.take(proposal_id, code)
    row = await _active_row(repo, peer_id)
    old = row.group_name
    if old == folder:
        return
    await ops.add_to_folder(peer_id, folder)
    try:
        await ops.remove_from_folder(peer_id, old)
    except Exception:
        await _undo(ops.remove_from_folder, peer_id, folder)
        raise
    try:
        if not await repo.set_group(peer_id, folder):
            raise LookupError(f"источник {peer_id} пропал из реестра при переносе")
    except Exception:
        await _undo(ops.add_to_folder, peer_id, old)
        await _undo(ops.remove_from_folder, peer_id, folder)
        raise


async def leave_source(
    store: ProposalStore,
    ops: TelegramOps,
    repo: SourceRepository,
    proposal_id: str,
    code: str,
    peer_id: int,
) -> None:
    """Выйти из канала по коду подтверждения и пометить его `left`.

    Строка и уже принятые документы остаются, доверие тоже; приём не
    вызывается вовсе. Сбой выхода оставляет строку активной. Если выход
    удался, а реестр не записался, поднимается ошибка реестра: аккаунт уже
    вне канала, строка ещё `active`, повтор вызова потребует нового кода.
    """
    store.take(proposal_id, code)
    await _active_row(repo, peer_id)
    await ops.leave(peer_id)
    if not await repo.mark_left(peer_id):
        raise LookupError(f"источник {peer_id} пропал из реестра при выходе")


async def set_source_trust(
    repo: SourceRepository, peer_id: int, trust: float | None,
) -> SourceRow:
    """Личное доверие к каналу: `0..1` или `None` («как у группы»).

    Кода нет: телеграм-аккаунт не меняется, пишется только наша таблица.
    Число действует вперёд — записанные связи не перештамповываются.
    """
    if trust is not None and not (math.isfinite(trust) and 0.0 <= trust <= 1.0):
        raise ValueError(f"доверие должно быть в [0, 1] или None, получено {trust!r}")
    if await repo.get(peer_id) is None:
        raise LookupError(f"источник {peer_id} не подключён")
    await repo.set_trust(peer_id, trust)
    row = await repo.get(peer_id)
    if row is None:
        raise LookupError(f"источник {peer_id} пропал из реестра")
    return row


async def _active_row(repo: SourceRepository, peer_id: int) -> SourceRow:
    """Предложение разрешает лишь известное реестру: чужой peer_id — отказ."""
    row = await repo.get(peer_id)
    if row is None or row.state != "active":
        raise LookupError(f"источник {peer_id} не подключён")
    return row


async def _undo(op: Any, peer_id: int, folder: str) -> None:
    try:
        await op(peer_id, folder)
    except Exception as exc:
        logger.warning(
            "отмена правки папки {f} для {p} не удалась: {e!r}", f=folder, p=peer_id, e=exc,
        )


def _reason(exc: Exception) -> str:
    if isinstance(exc, FloodWait):
        return _flood_reason(exc)
    if isinstance(exc, FolderNotFound):
        return f"папка не найдена: {exc}"
    return f"{type(exc).__name__}: {exc}"


async def _rollback(ops: TelegramOps, peer_id: int, joined: bool, reason: str) -> str:
    """Выйти из канала, если вступили, а записать не удалось: членство без
    строки реестра никто не увидит. Сбой выхода — в причину, нужна ручная чистка."""
    if not joined:
        return reason
    try:
        await ops.leave(peer_id)
    except Exception as exc:
        logger.warning("откат вступления {p} не удался: {e!r}", p=peer_id, e=exc)
        return (
            f"{reason}; выйти из канала не удалось ({type(exc).__name__}: {exc}), "
            "аккаунт остался в канале — нужна ручная чистка"
        )
    return f"{reason}; вступление отменено"


def _flood_reason(exc: FloodWait) -> str:
    return f"FloodWait: телеграм просит подождать {exc.seconds} с"


async def _bootstrap(
    messages: list[Any], slug: str, group: str,
    *, http: Any, api_base: str, api_key: str, graph: str | None,
) -> int:
    """Отправить сообщения так же, как свип (`scripts/tg_ingest.py::sync_round`):
    от старых к новым, имя и дата — `message_to_doc`, поля — `ingest_form`
    (`channel` без «@», `group` папки)."""
    sent = 0
    for msg in sorted(messages, key=lambda m: m.id):
        doc = message_to_doc(msg, slug)
        if doc is None:
            continue
        filename, text, document_date = doc
        res = await post_document(
            http, api_base, api_key,
            filename=filename, content=text.encode("utf-8"),
            data=ingest_form(document_date, group=group, channel=slug.lstrip("@")),
            graph=graph,
        )
        if res.outcome == SENT:
            sent += 1
        else:
            logger.info("bootstrap {f}: {o}", f=filename, o=res.outcome)
    return sent
