"""Plan A invariants: no transitional default left; physical names only via GraphContext."""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
TESTS = ROOT / "tests"


def _hits(pattern: str, allow: set[str], base: pathlib.Path = SRC) -> list[str]:
    rx = re.compile(pattern)
    out = []
    for p in base.rglob("*.py"):
        rel = str(p.relative_to(ROOT))
        if rel in allow:
            continue
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if rx.search(line):
                out.append(f"{rel}:{i}")
    return out


def test_no_transitional_default_left():
    assert _hits(r"transitional_default_graph", {"src/tenancy/context.py"}) == []


def test_chunk_collection_setting_only_read_by_tenancy():
    assert _hits(r"settings\.milvus\.collection", {"src/tenancy/context.py"}) == []


def test_no_hardcoded_space_or_collection_names():
    assert _hits(r"SPACE_NAME|[\"']entity_er_vec[\"']|[\"']community_report_vec[\"']|USE `kb`", {"src/tenancy/context.py"}) == []


def test_graph_store_builders_require_a_graph():
    import inspect

    from src.graph.nebula_store import build_nebula_graph_store
    from src.graph.store import build_graph_store
    for fn in (build_graph_store, build_nebula_graph_store):
        assert list(inspect.signature(fn).parameters) == ["graph"]


# ── Tenancy/authz invariants (spec 2026-10-18) ───────────────────────────────

# Repository calls that accept a tenant filter.  `create_or_resume` is not
# here: its `tenant_id` is DATA (whose the new row is), not a filter.
_FILTERED_REPO_CALLS = ("list_rows", "patch_row", "mark_deleting")


def _call_args(text: str, func: str) -> list[str]:
    """Argument text of every ``func(...)`` call in ``text``, parens balanced.

    Definitions are skipped, so the repository's own ``async def list_rows(``
    is not read as a call site.
    """
    out = []
    for m in re.finditer(rf"(?<!\w){func}\s*\(", text):
        if re.search(r"\bdef\s+$", text[: m.start()]):
            continue
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        out.append(text[m.end() : i - 1])
    return out


def test_authorize_is_only_reached_through_guard():
    # `authorize` is the pure rule set and knows nothing about AUTHZ_MODE:
    # a seam calling it directly would refuse even with the kill switch
    # at `off`, and would log nothing in the `log` review window.
    pattern = (
        r"(?<![\w.])authorize\(|\bauthz\.authorize\(|"
        r"^from src\.tenancy\.authz import .*\bauthorize\b"
    )
    assert _hits(pattern, {"src/tenancy/authz.py"}) == []


def test_repository_tenant_filters_come_from_authz():
    # Same reason, the other half: a filter taken straight from the key
    # would keep hiding other tenants' graphs with AUTHZ_MODE=off, and
    # would already shrink GET /admin/graphs in `log`.
    offenders: list[str] = []
    for p in SRC.rglob("*.py"):
        rel = str(p.relative_to(ROOT))
        text = p.read_text()
        for func in _FILTERED_REPO_CALLS:
            for args in _call_args(text, func):
                if "key.tenant_id" in args:
                    offenders.append(f"{rel}: {func}(... key.tenant_id ...)")
                elif "tenant_id=" in args and "tenant_filter(" not in args:
                    offenders.append(f"{rel}: {func}(... tenant_id=<not tenant_filter> ...)")
    assert offenders == []


def test_authz_mode_is_never_flipped_through_the_environment():
    # `settings.authz` is a cached_property on a process-wide singleton, so
    # setenv after the first read is a silent no-op.  Behavioural tests pin
    # the mode with `setattr(settings.authz, "mode", ...)`; only the settings
    # test, which builds a fresh AuthzSettings(), may touch the variable.
    pattern = r"(?:setenv|delenv)\(\s*[\"']AUTHZ_MODE[\"']"
    assert _hits(pattern, {"tests/test_config/test_authz_settings.py"}, base=TESTS) == []
