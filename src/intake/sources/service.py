"""Подключение источников по коду подтверждения.

`apply_proposal` открывает только то, что пользователь одобрил в
предложении: канал и ПАПКУ берутся из элемента предложения, а аргумент
`peer_ids` лишь сужает набор. Запись в реестр идёт после успеха на стороне
телеграма: строка о канале, в котором нас нет, заставила бы свип ждать
сообщений, которых не будет.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from loguru import logger

from src.intake.client import SENT, post_document
from src.intake.sources.messages import ingest_form, message_to_doc
from src.intake.sources.proposals import ProposalStore
from src.intake.sources.repository import SourceRepository
from src.intake.sources.telegram import FloodWait, FolderNotFound, TelegramOps


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
    а провал отмены оговаривается в причине. `FloodWait` на чтении истории
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
        try:
            await ops.join(peer_id)
            joined = True
            await ops.add_to_folder(peer_id, item.group_name)
            await repo.add(
                peer_id, item.slug, item.title, item.group_name, added_by=added_by,
            )
        except Exception as exc:  # сбой одного канала не должен ронять обход
            if isinstance(exc, FloodWait):
                flood = exc
            reason = await _rollback(ops, peer_id, joined, _reason(exc))
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
