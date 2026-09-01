"""Source trust — how much a document's origin is believed (0..1).

Trust is *policy*, not data: it lives in config (``SIGNALS_SOURCE_TRUST``),
keyed by the document ``group`` that ``/ingest`` already stamps, so retuning it
never needs a re-ingest.  Two consumers:

  * ``src/graph/edge_conflicts.py`` — when a new document contradicts a stored
    edge, the higher-trust source keeps the belief.
  * ``src/analytics/contradictions.py`` — claim versions are ranked by summed
    source trust instead of a plain distinct-source count.

Unknown / empty group falls back to ``SIGNALS_SOURCE_TRUST_DEFAULT`` (0.5), so
an unconfigured deployment behaves exactly as before: every source equal.
"""

from __future__ import annotations

from src.config import settings


def trust_for(group: str) -> float:
    """Trust of a document group, clamped to [0, 1].

    Lookup is case-insensitive and whitespace-tolerant; an unknown or empty
    group gets the configured default.
    """
    table = settings.signals.source_trust or {}
    key = (group or "").strip().lower()
    raw = table.get(key, settings.signals.source_trust_default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float(settings.signals.source_trust_default)
    return max(0.0, min(1.0, value))


__all__ = ["trust_for"]
