"""NebulaGraph connection settings."""
from __future__ import annotations


def test_nebula_settings_default_port(monkeypatch):
    monkeypatch.delenv("NEBULA_PORT", raising=False)
    from src.config import NebulaSettings

    assert NebulaSettings().port == 9669
