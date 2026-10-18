"""Tenants and API keys — created here and nowhere else (spec 2026-10-18 §4, A5).

There is deliberately NO HTTP route for any of this: a service that can mint
keys over HTTP can mint itself rights.  The operator runs this script against
Postgres directly.

The raw key exists only in the terminal, once.  Only its sha256 reaches the
database, so a lost key is re-issued, never recovered.

After ``revoke`` the rights do not die instantly: ``ApiKeyStore`` caches a
lookup (including its absence) for 30 s, in every api/mcp process.  Restart
api + mcp-* when a revocation has to take effect now.

Usage::

    uv run python -m scripts.tenant_admin create --id acme --name 'ACME Inc'
    uv run python -m scripts.tenant_admin key --tenant acme --owner ci --scopes read,write
    uv run python -m scripts.tenant_admin key --tenant acme --owner bot --scopes read \
        --graphs acme_news,acme_docs
    uv run python -m scripts.tenant_admin revoke --key-hash <sha256>
    uv run python -m scripts.tenant_admin list
"""

from __future__ import annotations

import argparse
import secrets
import sys
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from loguru import logger

from src.config import settings
from src.tenancy.api_keys import hash_api_key
from src.tenancy.authz import ALL_ACTIONS
from src.tenancy.context import InvalidGraphId, validate_graph_id
from src.utils.logging import configure_logging

ConnFactory = Callable[[], AbstractContextManager[Any]]

# Long enough that guessing is not a threat model; url-safe so it survives
# .env files, headers and shell quoting untouched.
_KEY_BYTES = 32


def _connect():
    pg = settings.postgres
    return psycopg.connect(pg.dsn, connect_timeout=pg.connect_timeout_s, autocommit=True)


# ── argument parsing and validation ──────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="tenant_admin",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,  # keep the examples readable
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="create a tenant (idempotent)")
    c.add_argument("--id", required=True, help="tenant slug, same rule as a graph id")
    c.add_argument("--name", required=True, help="human-readable name")

    k = sub.add_parser("key", help="issue an API key; the raw key is printed once")
    k.add_argument("--tenant", required=True, help="owning tenant slug")
    k.add_argument("--owner", required=True, help="who/what the key is for (free text)")
    k.add_argument(
        "--scopes",
        required=True,
        help=f"comma-separated actions out of: {', '.join(sorted(ALL_ACTIONS))}",
    )
    k.add_argument(
        "--graphs",
        default=None,
        help="comma-separated graph ids the key is narrowed to (default: every graph of the tenant)",
    )

    r = sub.add_parser("revoke", help="delete a key by its sha256")
    r.add_argument("--key-hash", required=True, help="sha256 as printed by `list`")

    sub.add_parser("list", help="tenants with their graphs and keys (no raw keys)")
    return p.parse_args(argv)


def _parse_scopes(raw: str) -> list[str]:
    """``read,write`` -> a sorted list; every name must be a real action.

    An empty set is refused rather than stored: a key with no rights is far
    more likely a typo (``--scopes ''``) than an intention, and it would fail
    later as an opaque 404 instead of here.
    """
    names = [s.strip() for s in raw.split(",") if s.strip()]
    if not names:
        raise ValueError("--scopes must name at least one action")
    unknown = sorted(set(names) - ALL_ACTIONS)
    if unknown:
        raise ValueError(
            f"unknown scope(s): {', '.join(unknown)}; known: {', '.join(sorted(ALL_ACTIONS))}"
        )
    return sorted(set(names))


def _parse_graphs(raw: str | None) -> list[str] | None:
    """``a,b`` -> a narrowing; the flag left out -> None = every graph of the tenant.

    None and ``[]`` are NOT the same thing downstream (``ApiKeyRecord.graph_ids
    is None`` is the unnarrowed key), so a flag that names nothing is an error
    rather than a silently empty list.
    """
    if raw is None:
        return None
    ids = [validate_graph_id(g.strip()) for g in raw.split(",") if g.strip()]
    if not ids:
        raise ValueError("--graphs was given but names no graph")
    return ids


# ── commands ─────────────────────────────────────────────────────────


def _cmd_create(cur, args: argparse.Namespace) -> int:
    cur.execute(
        "INSERT INTO public.tenants (id, name) VALUES (%s, %s) "
        "ON CONFLICT (id) DO NOTHING RETURNING id",
        (args.id, args.name),
    )
    print(f"tenant {args.id}  {'created' if cur.fetchone() else 'already exists'}")
    return 0


def _cmd_key(cur, args: argparse.Namespace, scopes: list[str], graphs: list[str] | None) -> int:
    # Checked here rather than in `run`: it needs the connection.  Without it a
    # typo surfaces as an unhandled ForeignKeyViolation traceback.
    cur.execute("SELECT 1 FROM public.tenants WHERE id = %s", (args.tenant,))
    if cur.fetchone() is None:
        print(f"no tenant {args.tenant!r} — create it first: tenant_admin create --id {args.tenant} --name ...")
        return 2
    raw = secrets.token_urlsafe(_KEY_BYTES)
    key_hash = hash_api_key(raw)
    cur.execute(
        "INSERT INTO public.api_keys (key_hash, owner, tenant_id, scopes, graph_ids) "
        "VALUES (%s, %s, %s, %s, %s)",
        (key_hash, args.owner, args.tenant, scopes, graphs),
    )
    print(
        f"key issued  tenant={args.tenant}  owner={args.owner}  "
        f"scopes={','.join(scopes)}  graphs={','.join(graphs) if graphs else '*'}"
    )
    print(f"key_hash={key_hash}")
    print("X-API-Key (shown once, not recoverable):")
    print(raw)  # last line, and the only place the raw key ever appears
    return 0


def _env_key_hashes() -> set[str]:
    """sha256 of every key still listed in env ``API_KEYS``.

    Its own function so the revoke warning can be driven in tests without
    reaching into the settings singleton, which other tests rebuild."""
    return {hash_api_key(k) for k in settings.api.keys_list}


def _cmd_revoke(cur, args: argparse.Namespace) -> int:
    cur.execute(
        "DELETE FROM public.api_keys WHERE key_hash = %s RETURNING owner",
        (args.key_hash,),
    )
    row = cur.fetchone()
    if row is None:
        print(f"no key with hash {args.key_hash}")
        return 1
    print(f"revoked  owner={row[0]}  key_hash={args.key_hash[:12]}")
    print("note: cached lookups keep working for up to 30 s (restart api/mcp-* to cut it short)")
    # A key still listed in env API_KEYS is NOT revoked by deleting its row:
    # ApiKeyStore.lookup falls back to `ApiKeyRecord.full("legacy-env")`, which
    # hands it EVERY action in tenant `default` — broader than whatever it just
    # lost — and the next `setup_db` re-inserts the row.  Say so instead of
    # reporting a revocation that did not happen.
    if args.key_hash in _env_key_hashes():
        print(
            "WARNING: this key is also in env API_KEYS, so it still authenticates "
            "with FULL rights in tenant 'default' via the legacy fallback. "
            "Remove it from API_KEYS and re-run scripts.setup_db to finish the revocation."
        )
        return 2
    return 0


def _cmd_list(cur) -> int:
    cur.execute("SELECT id, name FROM public.tenants ORDER BY id")
    tenants = cur.fetchall()
    cur.execute("SELECT tenant_id, id, status FROM public.graphs ORDER BY tenant_id, id")
    graphs = cur.fetchall()
    cur.execute(
        "SELECT tenant_id, owner, key_hash, scopes, graph_ids FROM public.api_keys "
        "ORDER BY tenant_id, owner"
    )
    keys = cur.fetchall()
    for tid, name in tenants:
        print(f"{tid}  {name}")
        for _, gid, status in (g for g in graphs if g[0] == tid):
            print(f"    graph  {gid}  {status}")
        for _, owner, key_hash, scopes, graph_ids in (k for k in keys if k[0] == tid):
            # A prefix of the hash: enough to name the key in `revoke`'s
            # output and in a ticket, useless to anyone who finds it.
            print(
                f"    key    {owner}  {key_hash[:12]}  scopes={','.join(scopes or ())}  "
                f"graphs={','.join(graph_ids) if graph_ids else '*'}"
            )
    return 0


def run(args: argparse.Namespace, conn_factory: ConnFactory | None = None) -> int:
    """Execute one subcommand; returns the process exit code.

    Everything the operator can get wrong is validated BEFORE a connection is
    opened, so a bad ``--scopes`` costs nothing and — more to the point —
    writes nothing.
    """
    scopes: list[str] = []
    graphs: list[str] | None = None
    try:
        if args.cmd == "create":
            validate_graph_id(args.id)
        elif args.cmd == "key":
            validate_graph_id(args.tenant)
            scopes = _parse_scopes(args.scopes)
            graphs = _parse_graphs(args.graphs)
    except (InvalidGraphId, ValueError) as exc:
        logger.error("{e}", e=exc)
        return 2

    with (conn_factory or _connect)() as conn, conn.cursor() as cur:
        if args.cmd == "create":
            return _cmd_create(cur, args)
        if args.cmd == "key":
            return _cmd_key(cur, args, scopes, graphs)
        if args.cmd == "revoke":
            return _cmd_revoke(cur, args)
        return _cmd_list(cur)


def main() -> int:
    configure_logging(level=settings.api.log_level, json_output=False)
    return run(_parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
