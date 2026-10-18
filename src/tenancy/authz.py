"""Graph access decisions: the one place that says who may do what.

Holds no I/O and does not import the key store at runtime (only under
``TYPE_CHECKING``), so every enforcement seam — HTTP, MCP, the graph
admin routes — can depend on it without an import cycle.

Spec: ``docs/superpowers/specs/2026-10-18-tenancy-authz-design.md`` §2.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from loguru import logger

from src.config import settings

if TYPE_CHECKING:
    from src.tenancy.api_keys import ApiKeyRecord


class Action(StrEnum):
    """What a key is being asked to do (spec A4).

    ``DOWNLOAD_ORIGINAL`` is deliberately NOT part of ``READ``: handing out
    the source file is a stronger right than reading what was extracted
    from it.
    """

    READ = "read"
    WRITE = "write"
    DOWNLOAD_ORIGINAL = "download_original"
    ADMIN = "admin"


ALL_ACTIONS: frozenset[str] = frozenset(a.value for a in Action)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""  # empty when allowed; "scope" | "unknown" | "tenant" | "graph"


def authorize(
    key: ApiKeyRecord,
    graph_id: str,
    graph_tenant: str | None,
    action: Action,
) -> Decision:
    """Decide whether ``key`` may perform ``action`` on ``graph_id`` (spec §2).

    Rules, strictly in this order: (1) the action is outside ``key.scopes``
    -> ``scope``; (2) the graph's tenant is unknown -> ``unknown``;
    (3) the graph belongs to another tenant -> ``tenant``; (4) the key is
    narrowed to graphs that do not include this one -> ``graph``; otherwise
    allowed.  The order is what keeps a reason from leaking: a key without
    the scope learns nothing about whether the graph it named exists.

    Deliberate deviation from the spec's ``async def authorize(key, graph_id,
    action)``: the graph's tenant is passed IN.  All three enforcement seams
    have already resolved the graph by the time they call this, so a second
    trip to the registry cache would buy nothing — and the built-in
    ``default`` graph, which has no row in ``public.graphs``, would otherwise
    come back as a false ``unknown``.  Pure: no I/O, no registry, no db.
    """
    if action not in key.scopes:
        return Decision(False, "scope")
    if graph_tenant is None:
        return Decision(False, "unknown")
    if graph_tenant != key.tenant_id:
        return Decision(False, "tenant")
    if key.graph_ids is not None and graph_id not in key.graph_ids:
        return Decision(False, "graph")
    return Decision(True)


def _mode() -> str:
    """Current AUTHZ_MODE, read on EVERY call.

    Never cached in this module: ``settings.authz`` is a ``cached_property``
    on the process-wide ``settings`` singleton, so operators flip the switch
    by restarting, and tests flip it by assigning ``settings.authz.mode``.
    A module-level copy would make both of those silently ineffective.
    """
    return settings.authz.mode


def guard(
    key: ApiKeyRecord,
    graph_id: str,
    graph_tenant: str | None,
    action: Action,
) -> Decision:
    """``authorize`` wrapped in the AUTHZ_MODE switch — call this, not ``authorize``.

    ``off``: allowed without even consulting the rules (emergency lever).
    ``log``: decide, report a refusal as ``authz would-deny …`` and allow
    anyway — the dark-launch window where the lines are reviewed.
    ``enforce``: report as ``authz deny …`` and return the real decision.

    The two log lines are a contract: they are what the review window reads,
    so keep the ``key=value`` shape if you touch them.
    """
    mode = _mode()
    if mode == "off":
        return Decision(True)
    decision = authorize(key, graph_id, graph_tenant, action)
    if decision.allowed:
        return decision
    tail = (
        f"key_owner={key.owner} tenant={key.tenant_id} graph={graph_id} "
        f"action={action} reason={decision.reason}"
    )
    if mode == "enforce":
        logger.warning(f"authz deny {tail}")
        return decision
    logger.warning(f"authz would-deny {tail}")
    return Decision(True)


def tenant_filter(key: ApiKeyRecord) -> str | None:
    """The tenant repository queries must filter by, or None for "do not filter".

    Repository-level filters MUST come through here; passing ``key.tenant_id``
    straight into a repository call is a bug.  Two invariants depend on it:
    ``off`` is a real kill switch (nothing anywhere filters, so a foreign
    graph is listed and deletable again, exactly as before this feature), and
    ``log`` genuinely leaves external behaviour unchanged instead of quietly
    shrinking ``GET /admin/graphs``.
    """
    return key.tenant_id if _mode() == "enforce" else None
