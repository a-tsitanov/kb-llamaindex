"""MCP источников: управление подключёнными каналами из харнесса.

Сервер живёт ВНУТРИ процесса фидера (`scripts/tg_ingest.py`): один токен
телеграма — один поллер, второй `TelegramClient` на той же сессии
недопустим, поэтому инструменты берут тот же клиент и ту же блокировку
(`TelegramOps`). Каждый инструмент — тонкая обёртка над `service`,
`report`, `repository`.

Правила, общие для всех инструментов:

* ПЕРВЫМ делом зовётся `require_sources_access(feeder_graph_id)`: право
  `sources` на ровно один граф фидера, до телеграма и до базы. Контекст
  графа, который он вернул, строит репозиторий (`repo_factory`).
* Запись в телеграм-аккаунт — только по коду: `sources_propose` отдаёт
  элементы и одноразовый код, пользователь повторяет код, и лишь тогда
  `sources_apply` / `source_move` / `source_leave` что-то делают.
* Ошибки переводятся в `ToolError` по ТИПАМ и полям, текст исключений не
  разбирается.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from src.intake.sources.auth import require_sources_access
from src.intake.sources.proposals import (
    CONNECT,
    LEAVE,
    MOVE,
    BadProposal,
    ProposalItem,
    ProposalStore,
    SourceInputError,
    SourceNotFound,
)
from src.intake.sources.report import channel_report
from src.intake.sources.repository import SourceRepository, SourceRow
from src.intake.sources.service import (
    AmbiguousMove,
    apply_proposal,
    leave_source,
    move_source,
    set_source_trust,
)
from src.intake.sources.telegram import (
    Candidate,
    FloodWait,
    FolderNotEditable,
    FolderNotFound,
    TelegramOps,
)
from src.mcp._shared import assert_api_key_env_set, build_sse_auth, current_principal


@dataclass(frozen=True)
class IngestTarget:
    """Куда `sources_apply` отправляет историю нового канала (обычный `POST /ingest`)."""

    http: Any
    api_base: str
    api_key: str
    bootstrap: int = 100
    graph: str | None = None


def _translate(exc: Exception) -> ToolError | None:
    """Исключение сервиса -> понятный отказ; `None` — не наше, пусть летит выше.

    Порядок важен: `BadProposal` — `ValueError`, `FolderNotEditable` — частный
    случай `FolderNotFound`. Классифицируем только по типам и полям.
    """
    if isinstance(exc, ToolError):
        return exc
    if isinstance(exc, BadProposal):
        return ToolError(
            "код не принят: он неверный, предложение просрочено или уже "
            "использовано, либо код выдан для другого канала или другого "
            f"действия. Запросите новое предложение. ({exc})"
        )
    if isinstance(exc, AmbiguousMove):
        wait = f" Телеграм просит подождать {exc.seconds} с." if exc.seconds else ""
        return ToolError(
            f"перенос оборвался с неясным состоянием: старая папка {exc.old!r}, "
            f"новая {exc.new!r}.{wait} Повтор переноса сходится (операции с "
            f"папками идемпотентны). Подробности: {exc}"
        )
    if isinstance(exc, FloodWait):
        return ToolError(f"телеграм просит подождать {exc.seconds} с; повторите позже")
    if isinstance(exc, FolderNotEditable):
        return ToolError(
            f"папка {exc.folder!r} — общий список (chatlist), её состав не "
            "правится; положите канал в обычную папку"
        )
    if isinstance(exc, FolderNotFound):
        return ToolError(
            f"папки {exc.folder!r} нет в аккаунте; агент папки не создаёт — "
            "создайте её в клиенте телеграма"
        )
    if isinstance(exc, (SourceInputError, SourceNotFound)):
        return ToolError(str(exc))
    return None


@contextmanager
def _translated() -> Iterator[None]:
    try:
        yield
    except Exception as exc:
        err = _translate(exc)
        if err is None:
            raise
        if err is exc:
            raise
        raise err from exc


def _candidate(c: Candidate, **extra: Any) -> dict[str, Any]:
    return {
        "peer_id": c.peer_id, "slug": c.slug, "title": c.title,
        "participants": c.participants, "public": c.public, **extra,
    }


def _row(r: SourceRow) -> dict[str, Any]:
    return {
        "peer_id": r.peer_id, "slug": r.slug, "title": r.title,
        "group": r.group_name, "trust": r.trust, "state": r.state,
        "added_by": r.added_by, "note": r.note,
    }


def build_sources_mcp(
    ops: TelegramOps,
    repo_factory: Callable[[Any], SourceRepository],
    store: ProposalStore,
    feeder_graph_id: str,
    *,
    ingest: IngestTarget | None = None,
    status: Callable[[], dict[str, Any]] | None = None,
    folders_timeout: float = 3.0,
    approved_moves: dict[str, dict[int, str]] | None = None,
) -> FastMCP:
    """Собрать сервер. `repo_factory(ctx)` строит репозиторий из контекста графа,
    который вернул шов доступа; `status()` отдаёт курсоры и итог последнего
    раунда свипа (состояние фидера, новых полей не заводит). `folders_timeout` —
    сколько `feeder_status` ждёт список папок (он берёт замок раунда)."""
    mcp = FastMCP(
        name="kb-feeder-sources",
        instructions=(
            "Управление источниками Telegram-фидера: поиск каналов, подключение, "
            "перенос по папкам, выход, доверие, отчёт. Запись в аккаунт — только "
            "по коду: sources_propose -> показать пользователю -> пользователь "
            "повторяет код -> sources_apply / source_move / source_leave."
        ),
        auth=build_sse_auth(),
    )
    # Папка, одобренная пользователем для переноса: source_move берёт её отсюда,
    # а не из аргумента вызова, иначе код подтверждал бы одно, а делалось другое.
    if approved_moves is None:
        approved_moves = {}
    # последний удавшийся список папок для feeder_status (замок раунда может держаться долго)
    folders_cache: list[str] | None = None

    async def _enter() -> tuple[Any, SourceRepository]:
        ctx = await require_sources_access(feeder_graph_id)
        return ctx, repo_factory(ctx)

    @mcp.tool
    async def sources_list() -> dict[str, Any]:
        """Подключённые каналы: группа, доверие и `in_folder` — лежит ли канал
        в своей папке Telegram прямо сейчас (False = расхождение: убрали руками)."""
        _, repo = await _enter()
        with _translated():
            rows = await repo.list_active()
            # одно чтение фильтров на весь листинг; названия сверяются как в _find_folder
            by_folder = await ops.folders_with_members()
            members = {t.casefold(): ids for t, ids in by_folder.items()}
            folders = list(by_folder)
            return {
                "sources": [
                    {**_row(r), "in_folder": r.peer_id in members.get(
                        r.group_name.strip().casefold(), set())}
                    for r in rows
                ],
                "folders": folders,
            }

    @mcp.tool
    async def sources_search(query: str, limit: int = 10) -> dict[str, Any]:
        """Поиск публичных каналов в Telegram; `connected` — уже в реестре."""
        _, repo = await _enter()
        with _translated():
            found = await ops.search(query, limit)
            active = {r.peer_id for r in await repo.list_active()}
            return {"candidates": [
                _candidate(c, connected=c.peer_id in active) for c in found
            ]}

    @mcp.tool
    async def sources_resolve(handle: str) -> dict[str, Any]:
        """Канал по `@слагу` или ссылке t.me; `candidate: null` — не найден."""
        _, repo = await _enter()
        with _translated():
            c = await ops.resolve(handle)
            if c is None:
                return {"candidate": None}
            known = await repo.get(c.peer_id)
            connected = known is not None and known.state == "active"
            return {"candidate": _candidate(c, connected=connected)}

    @mcp.tool
    async def sources_propose(action: str, channels: list[dict[str, Any]]) -> dict[str, Any]:
        """Предложение и одноразовый код подтверждения; в телеграм НИЧЕГО не пишет.

        action `connect`: channels = [{peer_id, slug, title, group}] (group — одна
        из существующих папок: news, analytics, digest, opinion, official, data).
        action `move`: ровно один [{peer_id, group}] — папка назначения.
        action `leave`: ровно один [{peer_id}].
        Покажите пользователю items и code; применять — только с кодом от него.
        """
        _, repo = await _enter()
        with _translated():
            if action not in (CONNECT, MOVE, LEAVE):
                raise SourceInputError(f"действие {action!r} не из connect, move, leave")
            if action != CONNECT and len(channels) != 1:
                raise SourceInputError(f"для {action} в предложении ровно один канал")
            items: list[ProposalItem] = []
            for ch in channels:
                try:
                    peer_id = int(ch["peer_id"])
                except (KeyError, TypeError, ValueError):
                    raise SourceInputError(f"у канала нет числового peer_id: {ch!r}") from None
                if action == CONNECT:
                    items.append(ProposalItem(
                        peer_id, str(ch.get("slug") or ""), str(ch.get("title") or ""),
                        str(ch.get("group") or ""),
                    ))
                    continue
                row = await repo.get(peer_id)
                if row is None or row.state != "active":
                    raise SourceNotFound(f"источник {peer_id} не подключён")
                group = str(ch.get("group") or "") if action == MOVE else row.group_name
                items.append(ProposalItem(peer_id, row.slug, row.title, group))
            proposal = store.create(items, action)
            # одобренные папки живут не дольше самого предложения
            for pid in [p for p in approved_moves if not store.is_live(p)]:
                del approved_moves[pid]
            if action == MOVE:
                approved_moves[proposal.id] = {it.peer_id: it.group_name for it in items}
            return {
                "proposal_id": proposal.id,
                "code": proposal.code,
                "action": proposal.action,
                "items": [
                    {"peer_id": it.peer_id, "slug": it.slug, "title": it.title,
                     "group": it.group_name}
                    for it in proposal.items
                ],
            }

    @mcp.tool
    async def sources_apply(
        proposal_id: str, code: str, peer_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Подключить каналы из предложения `connect` по коду (вступить, положить
        в папку, записать в реестр, подтянуть последние сообщения)."""
        _, repo = await _enter()
        with _translated():
            target = ingest or IngestTarget(http=None, api_base="", api_key="", bootstrap=0)
            res = await apply_proposal(
                store, ops, repo, proposal_id, code, peer_ids,
                added_by=current_principal() or "feeder-mcp",
                bootstrap=target.bootstrap, http=target.http,
                api_base=target.api_base, api_key=target.api_key, graph=target.graph,
            )
            return {
                "connected": res.connected,
                "skipped": [{"peer_id": p, "reason": r} for p, r in res.skipped],
                "bootstrapped": res.bootstrapped,
                "partial": [{"peer_id": p, "reason": r} for p, r in res.partial],
            }

    @mcp.tool
    async def source_move(proposal_id: str, code: str, peer_id: int) -> dict[str, Any]:
        """Переложить канал в папку, одобренную в предложении `move`, по коду."""
        _, repo = await _enter()
        with _translated():
            approved = approved_moves.pop(proposal_id, None)
            if approved is None or peer_id not in approved:
                # погасить предложение и отказать единым BadProposal
                store.take(proposal_id, code, MOVE)
                raise BadProposal("предложения нет, оно просрочено или не для этого канала")
            folder = approved[peer_id]
            await move_source(store, ops, repo, proposal_id, code, peer_id, folder)
            return {"moved": True, "peer_id": peer_id, "folder": folder}

    @mcp.tool
    async def source_leave(proposal_id: str, code: str, peer_id: int) -> dict[str, Any]:
        """Выйти из канала по коду. Строка и принятые документы остаются."""
        _, repo = await _enter()
        with _translated():
            await leave_source(store, ops, repo, proposal_id, code, peer_id)
            return {"left": True, "peer_id": peer_id}

    @mcp.tool
    async def source_trust_set(peer_id: int, trust: float | None) -> dict[str, Any]:
        """Личное доверие к каналу `0..1` или null («как у группы»). Кода нет.
        Действует только ВПЕРЁД: записанные связи не перештамповываются."""
        _, repo = await _enter()
        with _translated():
            return _row(await set_source_trust(repo, peer_id, trust))

    @mcp.tool
    async def source_report(peer_id: int, days: int = 30) -> dict[str, Any]:
        """Отчёт по каналу за `days` дней: объём, судьба документов, перепосты,
        вытеснения, отдача графу, покрытие, доверие (улика, не решение)."""
        ctx, _ = await _enter()
        with _translated():
            return await channel_report(ctx, peer_id, days=days)

    @mcp.tool
    async def feeder_status() -> dict[str, Any]:
        """Курсоры по диалогам, итог последнего раунда свипа и найденные папки.

        Курсоры и раунд читаются без замка и без телеграма: диагностика нужна
        именно тогда, когда раунд долгий или завис. Папки — по возможности:
        `folders_state` = `fresh` (прочитаны сейчас), `stale` (замок занят,
        отдан список прошлого ответа) или `unavailable` (читать нечем).
        `last_round.ok = false` увидеть почти нельзя: упавший раунд
        пробрасывает исключение и процесс фидера выходит (контейнер затем
        перезапускается), поэтому признак провала живёт в логе, а здесь после
        рестарта будет `last_round = null`.
        """
        nonlocal folders_cache
        await _enter()
        with _translated():
            snap = status() if status is not None else {}
            try:
                folders_cache = await asyncio.wait_for(ops.folders(), folders_timeout)
                folders, state = folders_cache, "fresh"
            except Exception:
                # Папки — не предмет этого инструмента: любой их сбой (замок,
                # FloodWait, обрыв сессии) не должен лишать оператора курсоров.
                folders = folders_cache
                state = "stale" if folders_cache is not None else "unavailable"
            return {
                "cursors": snap.get("cursors") or {},
                "last_round": snap.get("last_round"),
                "folders": folders,
                "folders_state": state,
            }

    return mcp


async def serve_sources_mcp(mcp: FastMCP, host: str, port: int) -> None:
    """Streamable HTTP (`/mcp`) до отмены задачи. Вызывающий ловит сбои:
    падение сервера не должно ронять свип."""
    assert_api_key_env_set()
    await mcp.run_http_async(
        transport="http", host=host, port=port, show_banner=False,
    )
