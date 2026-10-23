"""Папки Телеграма (dialog filters): разбор состава и групп каналов.

Общий код фидера (`scripts/tg_ingest.py`) и операций MCP над источниками
(`telegram.py`): зависимость идёт только scripts → src.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from loguru import logger

from src.retrieval.groups import GROUP_SET, pick_priority


def dialog_slug(dialog: Any) -> str:
    """Stable human-ish id for filenames: @username when the dialog has
    one, else the numeric dialog id (negative for channels/groups)."""
    username = getattr(getattr(dialog, "entity", None), "username", None)
    return username if username else str(dialog.id)


# ── Telegram folders (dialog filters) as sync scope ─────────────────


def filter_title(folder: Any) -> str:
    """Folder title across TL layers: plain str in old ones,
    TextWithEntities(.text) in new ones; '' for DialogFilterDefault."""
    t = getattr(folder, "title", "")
    return getattr(t, "text", t) or ""


def resolve_folders(
    folders: list[Any], names: list[str], *, peer_id: Callable[[Any], int],
) -> tuple[dict, list[str]]:
    """Merge the wanted folders (matched by title, case-insensitive) into a
    single selection spec.

    Returns ``({include_ids, exclude_ids, groups, broadcasts}, missing)``:
    explicit peers (include + pinned) union'ed across folders, excluded
    peers likewise, plus the two category flags a folder may carry instead
    of explicit peers («все группы» / «все каналы»).  ``exclude_muted`` /
    ``exclude_read`` / archive flags are intentionally ignored — the sync
    cares about membership, not the client-side unread cosmetics."""
    wanted = {n.strip().casefold(): n.strip() for n in names if n.strip()}
    spec = {
        "include_ids": set(), "exclude_ids": set(),
        "groups": False, "broadcasts": False,
    }
    found: set[str] = set()
    for f in folders:
        title = filter_title(f).strip()
        if title.casefold() not in wanted:
            continue
        found.add(title.casefold())
        for p in [*getattr(f, "include_peers", []), *getattr(f, "pinned_peers", [])]:
            spec["include_ids"].add(peer_id(p))
        for p in getattr(f, "exclude_peers", []):
            spec["exclude_ids"].add(peer_id(p))
        spec["groups"] = spec["groups"] or bool(getattr(f, "groups", False))
        spec["broadcasts"] = spec["broadcasts"] or bool(getattr(f, "broadcasts", False))
    missing = [orig for key, orig in wanted.items() if key not in found]
    return spec, missing


def resolve_group_map(folders: list[Any], *, peer_id: Callable[[Any], int]) -> dict[int, str]:
    """Map dialog_id → channel group (folder title ∈ GROUP_SET).

    A group is the lowercase folder title. Disjoint: if a channel appears in
    >1 group-folder keep the higher-priority group (``pick_priority``) and log
    a WARNING. Folders whose title is not a known group are ignored here (they
    may still scope the sync via ``resolve_folders``). Category-flag folders
    («все каналы») don't enumerate peers, so channels included only by a flag
    stay ungrouped (``""``)."""
    out: dict[int, str] = {}
    for f in folders:
        title = filter_title(f).strip().casefold()
        if title not in GROUP_SET:
            continue
        for p in [*getattr(f, "include_peers", []), *getattr(f, "pinned_peers", [])]:
            pid = peer_id(p)
            prev = out.get(pid)
            if prev and prev != title:
                winner = pick_priority(prev, title)
                logger.warning(
                    "tg_ingest: channel {c} in multiple group-folders "
                    "({a}, {b}) → keeping {w}", c=pid, a=prev, b=title, w=winner,
                )
                out[pid] = winner
            else:
                out[pid] = title
    return out
