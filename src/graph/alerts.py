"""Arc 2 — Alert store + watchlist helpers (called off-loop from activities).

Helpers here are synchronous and must never raise — they log a WARNING on failure
so the monitoring sweep stays alive even when the graph is transiently unavailable.
All reads/writes are dispatched through ``build_alert_store`` (nebula); no Cypher
lives in this module.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from src.graph.alert_store import build_alert_store

# ── Public helpers ────────────────────────────────────────────────────────────


def alert_key(kind: str, entity: str, detail: str) -> str:
    """Compose a stable dedup key for an Alert node.

    Format: ``kind:entity:detail`` — deterministic, so re-sweeps MERGE
    onto the same node instead of creating duplicates.
    """
    return f"{kind}:{entity}:{detail}"


def upsert_alert(
    store: Any,
    *,
    kind: str,
    entity: str,
    detail: str,
    created_at: int,
    score: float | None = None,
) -> None:
    """MERGE an :Alert node keyed on (kind, entity, detail); fail-soft on error.

    When ``score`` is given, the value is stored as ``a.score`` and refreshed
    in place on re-detection (ON MATCH) — one alert per (kind, entity, detail),
    no churn as the score drifts. The score is never part of the dedup key.
    """
    key = alert_key(kind, entity, detail)
    try:
        build_alert_store(store).upsert_alert(
            key=key, kind=kind, entity=entity, detail=detail,
            created_at=created_at, score=score,
        )
    except Exception as exc:
        logger.warning("upsert_alert failed (non-fatal): {e}", e=exc)


def read_alerts(
    store: Any,
    *,
    kind: str | None = None,
    entity: str | None = None,
    since: int | None = None,
    top_n: int = 50,
) -> list[dict]:
    """Read persisted :Alert rows (backend-dispatched); fail-soft → []."""
    try:
        return build_alert_store(store).read_alerts(kind, entity, since, top_n)
    except Exception as exc:
        logger.warning("read_alerts failed (non-fatal): {e}", e=exc)
        return []


def mark_watched(store: Any, names: list[str], watched: bool = True) -> None:
    """SET e.watched on __Entity__ nodes by name list; fail-soft on error."""
    if not names:
        return
    try:
        build_alert_store(store).mark_watched(names, watched)
    except Exception as exc:
        logger.warning("mark_watched failed (non-fatal): {e}", e=exc)


__all__ = ["alert_key", "mark_watched", "read_alerts", "upsert_alert"]
