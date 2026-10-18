"""AUTHZ_MODE — the one switch that arms graph authorization.

The declared default is asserted WITHOUT instantiating: the repo root holds
a 134-line ``.env``, and this step is accepted by running the suite twice —
once with no ``AUTHZ_MODE`` in the environment and once with
``AUTHZ_MODE=enforce`` exported.  A bare ``AuthzSettings()`` would read both
sources, so the assertion would flip depending on how the suite was started.
Env-independent default check = ``model_fields[...].default`` (same pattern as
tests/test_config/test_settings.py::test_er_native_vector_knn_on_by_default).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config import AuthzSettings, settings


def test_default_mode_is_log() -> None:
    # Ships OFF: `log` observes and reports, it does not refuse anything.
    assert AuthzSettings.model_fields["mode"].default == "log"


@pytest.mark.parametrize("mode", ["off", "log", "enforce"])
def test_env_override(monkeypatch, mode: str) -> None:
    monkeypatch.setenv("AUTHZ_MODE", mode)
    assert AuthzSettings().mode == mode


def test_bad_value_rejected(monkeypatch) -> None:
    monkeypatch.setenv("AUTHZ_MODE", "enforced")  # plausible typo
    with pytest.raises(ValidationError):
        AuthzSettings()


def test_settings_exposes_authz() -> None:
    # Behavioural tests pin the mode by assigning to this very object, so it
    # has to be the cached instance `guard()` reads.
    assert isinstance(settings.authz, AuthzSettings)
    assert settings.authz is settings.authz
