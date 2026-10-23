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


class ProposalStore:
    def __init__(
        self, ttl_s: int = 900, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_s
        self._clock = clock
        self._live: dict[str, tuple[Proposal, float]] = {}

    def create(self, items: list[ProposalItem]) -> Proposal:
        if not items:
            raise ValueError("пустое предложение")
        for it in items:
            if it.group_name not in GROUP_SET:
                raise ValueError(
                    f"группа {it.group_name!r} не из {sorted(GROUP_SET)}"
                )
        self._purge()
        proposal = Proposal(
            id=secrets.token_urlsafe(8),
            code="".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LEN)),
            items=list(items),
        )
        self._live[proposal.id] = (proposal, self._clock() + self._ttl)
        return proposal

    def take(self, proposal_id: str, code: str) -> Proposal:
        """Забрать предложение (одноразово).

        Неверный код предложение тоже сжигает: иначе код можно было бы
        подобрать перебором, а новое предложение стоит одного вызова.
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
        return proposal

    def _purge(self) -> None:
        now = self._clock()
        for pid in [p for p, (_, exp) in self._live.items() if exp <= now]:
            del self._live[pid]
