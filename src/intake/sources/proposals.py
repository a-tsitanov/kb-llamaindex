"""Предложение с кодом подтверждения: замок на запись в телеграм-аккаунт.

Агент сначала показывает пользователю список каналов и получает от
`ProposalStore.create` код; вступать, править папку и выходить можно только
предъявив этот код обратно. Хранилище живёт в памяти процесса фидера:
предложение живёт минуты, перезапуск его отменяет — и это нормально.
"""

from __future__ import annotations

import hmac
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

from src.retrieval.groups import GROUP_SET

# Без 0/O/I/l/1: код читают глазами и переписывают руками.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LEN = 6

# Действие, на которое выдан код: код на вступление не открывает перенос и выход.
CONNECT = "connect"
MOVE = "move"
LEAVE = "leave"
ACTIONS = frozenset({CONNECT, MOVE, LEAVE})


class SourceInputError(ValueError):
    """Отказ по входным данным источников (группа, действие, доверие): текст
    для человека, адресован харнессу. Чужой `ValueError` (драйвера, библиотеки)
    сюда не относится и харнессу текстом не отдаётся."""


class SourceNotFound(LookupError):
    """Источника нет в реестре или он не активен (наш отказ, не чужой `KeyError`)."""


class BadProposal(ValueError):
    """Предложения нет, оно просрочено, уже использовано или код не тот."""


@dataclass(frozen=True)
class ProposalItem:
    peer_id: int
    slug: str
    title: str
    group_name: str


@dataclass(frozen=True)
class Proposal:
    id: str
    code: str
    items: list[ProposalItem]
    # на какое действие выдан код: CONNECT, MOVE или LEAVE
    action: str


class ProposalStore:
    def __init__(
        self, ttl_s: int = 900, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_s
        self._clock = clock
        self._live: dict[str, tuple[Proposal, float]] = {}

    def create(self, items: list[ProposalItem], action: str) -> Proposal:
        if action not in ACTIONS:
            raise SourceInputError(f"действие {action!r} не из {sorted(ACTIONS)}")
        if not items:
            raise SourceInputError("пустое предложение")
        # Группа значима только там, где её выбирают (подключение, перенос); при
        # выходе она берётся из строки реестра, а та могла уйти из набора.
        for it in items if action != LEAVE else ():
            if it.group_name not in GROUP_SET:
                raise SourceInputError(
                    f"группа {it.group_name!r} не из {sorted(GROUP_SET)}"
                )
        self._purge()
        proposal = Proposal(
            id=secrets.token_urlsafe(8),
            code="".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LEN)),
            items=list(items),
            action=action,
        )
        self._live[proposal.id] = (proposal, self._clock() + self._ttl)
        return proposal

    def take(self, proposal_id: str, code: str, action: str) -> Proposal:
        """Забрать предложение (одноразово).

        Неверный код предложение тоже сжигает: иначе код можно было бы
        подобрать перебором, а новое предложение стоит одного вызова. Так же
        и код, предъявленный для другого действия: пользователь подтвердил
        вступление, а не перенос или выход.
        """
        self._purge()
        entry = self._live.pop(proposal_id, None)
        if entry is None:
            raise BadProposal("предложения нет, оно просрочено или уже использовано")
        proposal, _ = entry
        if not hmac.compare_digest(
            proposal.code.encode(), code.strip().upper().encode(),
        ):
            raise BadProposal("код подтверждения не совпал; предложение погашено")
        if proposal.action != action:
            raise BadProposal(
                f"код выдан на действие {proposal.action!r}, а не {action!r}; "
                "предложение погашено"
            )
        return proposal

    def is_live(self, proposal_id: str) -> bool:
        """Предложение ещё действует (не использовано и не просрочено)."""
        self._purge()
        return proposal_id in self._live

    def _purge(self) -> None:
        now = self._clock()
        for pid in [p for p, (_, exp) in self._live.items() if exp <= now]:
            del self._live[pid]
