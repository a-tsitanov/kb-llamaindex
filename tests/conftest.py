"""Pytest-asyncio mode is set globally in pyproject.toml.

Project-wide fixtures land here as the codebase grows.

Known: ``beartype.claw`` (transitively pulled in by fastmcp) has
a circular-import quirk when Temporal's workflow sandbox re-imports
modules after fastmcp has already loaded.  Pre-importing here
helps in some cases.  If you hit
``ImportError: cannot import name 'claw_state'`` during a combined
run, split the suites:

    pytest tests/test_mcp/
    pytest tests/test_workflow/test_search_orchestrator.py

Both pass green individually.  The flake is order-dependent, not
correctness-related.
"""

try:
    import beartype
    import beartype.claw  # noqa: F401
except ImportError:
    pass


import pytest


@pytest.fixture(autouse=True)
def _offline_graph_registry(monkeypatch):
    from src.tenancy import registry as reg
    from src.tenancy.context import default_graph_context, new_graph_context

    class _Stub:
        async def get(self, gid):
            return default_graph_context() if gid == "default" else new_graph_context(gid)

        def invalidate(self, gid=None):
            pass
    monkeypatch.setattr(reg, "get_graph_registry", lambda: _Stub())
    import src.tenancy.activity as ta
    monkeypatch.setattr(ta, "get_graph_registry", lambda: _Stub())
