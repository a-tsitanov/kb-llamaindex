"""Guards on docker-compose.prod.yml for the tenancy rollout.

Two separate regressions are pinned here:

* AUTHZ_MODE has to be listed in the `x-app-env` anchor — prod services get an
  explicit allow-list of variables and no `env_file`, so a var that is not in
  the anchor simply never reaches the container and the switch is dead.
* Every app service that reads the registry schema `init` creates
  (`public.api_keys` / `public.graphs`) must wait for it.  mcp-search /
  mcp-tools / mcp-stats did not, so network MCP could come up against an
  un-migrated table — and the broad `except Exception` in `ApiKeyStore.lookup`
  would turn that into a 403 for every db-only key, cached for 30 s.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_COMPOSE = Path("docker-compose.prod.yml")

# The six app services: api and the three MCP servers authenticate against
# public.api_keys; worker and ingest-consumer resolve graphs out of
# public.graphs.  All six need the schema `init` creates.
_REGISTRY_READERS = (
    "api",
    "worker",
    "ingest-consumer",
    "mcp-search",
    "mcp-tools",
    "mcp-stats",
)


def _compose() -> dict:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


def test_app_env_carries_authz_mode():
    env = _compose()["x-app-env"]
    assert env["AUTHZ_MODE"] == "${AUTHZ_MODE:-log}"


def test_every_registry_reader_waits_for_init():
    services = _compose()["services"]
    missing = [
        name
        for name in _REGISTRY_READERS
        if services[name].get("depends_on", {}).get("init", {}).get("condition")
        != "service_completed_successfully"
    ]
    assert missing == [], f"services that may start before setup_db: {missing}"


def test_registry_readers_inherit_app_env():
    # The guard above is only meaningful if these services actually get the
    # anchor (several merge it into a per-service `environment` block).
    services = _compose()["services"]
    for name in _REGISTRY_READERS:
        assert "AUTHZ_MODE" in services[name]["environment"], name
