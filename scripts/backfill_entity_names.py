"""Backfill for KB name resolution (src/graph/name_resolution.py). Resumable, idempotent.

Three passes, each a dry run (counts + a report) unless ``--apply``:

  names     entity.name_norm / name_translit for rows written before the columns existed;
  liveness  entity.alive = the vertex still exists in the graph (ER deletes merged-away
            losers; the mirror kept their rows — 13% of it on 2026-09-30);
  aliases   entity_alias rows for dead names from er_verdict SAME pairs whose partner is
            alive (chains followed): «Росатом» → "Rosatom", source verdict_backfill,
            confidence 0.85. Only DEAD names get aliases, so a noisy verdict between two
            living entities (Fomc ≡ ФРС) never becomes one. The dry run writes every
            proposed alias and a random sample for manual review.

Run ``names`` and ``liveness`` before ``aliases`` (it reads entity.alive).

    python scripts/backfill_entity_names.py names [--apply]
    python scripts/backfill_entity_names.py liveness [--apply]
    python scripts/backfill_entity_names.py aliases [--apply] [--report out.csv] [--sample 200]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from src.utils.names import norm_name, translit_key

CONFIDENCE = 0.85
MAX_CHAIN = 3


def verdict_names(er_key: str) -> tuple[str, str] | None:
    """er_verdict.er_key = JSON [[norm, label], [norm, label]] → the two names."""
    try:
        (a, _), (b, _) = json.loads(er_key)
    except (ValueError, TypeError):
        return None
    return (str(a), str(b)) if a and b and a != b else None


def plan_aliases(pairs: Iterable[tuple[str, str]], alive: dict[str, int],
                 dead: set[str]) -> list[dict[str, Any]]:
    """Dead name → the most-mentioned live entity it was judged SAME as, directly or through
    up to ``MAX_CHAIN`` dead names. Names are matched by ``norm_name`` (verdict keys hold
    ER's normalized form, the mirror the stored name)."""
    live_by_norm: dict[str, str] = {}
    for n, mc in alive.items():
        cur = live_by_norm.get(norm_name(n))
        if cur is None or mc > alive[cur]:
            live_by_norm[norm_name(n)] = n
    dead_by_norm = {norm_name(n): n for n in dead}
    graph: dict[str, set[str]] = defaultdict(set)
    for a, b in pairs:
        na, nb = norm_name(a), norm_name(b)
        graph[na].add(nb)
        graph[nb].add(na)
    out = []
    for dn, d in dead_by_norm.items():
        if dn in live_by_norm:
            continue  # a live entity with the same normalized name: casefold finds it
        seen, frontier, best, depth = {dn}, [dn], None, 0
        while frontier and depth < MAX_CHAIN and best is None:
            depth += 1
            nxt = []
            for x in frontier:
                for y in graph.get(x, ()):
                    if y in seen:
                        continue
                    seen.add(y)
                    if y in live_by_norm:
                        c = live_by_norm[y]
                        if best is None or alive[c] > alive[best]:
                            best = c
                    elif y in dead_by_norm:
                        nxt.append(y)
            frontier = nxt
        if best is not None:
            out.append({"alias": d, "canonical": best, "hops": depth})
    return out


# ── passes ────────────────────────────────────────────────────────────


def _pg():
    from src.storage.pg_sync_pool import get_pg_sync_pool
    return get_pg_sync_pool()


def pass_names(apply: bool, batch: int = 5000) -> None:
    last, total = "", 0
    while True:
        with _pg().connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT vid, name FROM entity WHERE vid > %s AND "
                        "(name_norm IS NULL OR name_translit IS NULL) ORDER BY vid LIMIT %s",
                        [last, batch])
            rows = cur.fetchall()
            if not rows:
                break
            if apply:
                cur.executemany(
                    "UPDATE entity SET name_norm = %s, name_translit = %s WHERE vid = %s",
                    [(norm_name(n), translit_key(n), v) for v, n in rows])
        last, total = rows[-1][0], total + len(rows)
        print(f"names: {total} rows {'updated' if apply else 'to update'} last={last!r}",
              flush=True)
    print(f"names: done, {total} rows {'updated' if apply else 'to update (dry run)'}")


def pass_liveness(apply: bool, batch: int = 500) -> None:
    from src.graph.nebula_store import _q
    from src.graph.store import build_graph_store
    store = build_graph_store()
    last, seen, dead_total = "", 0, 0
    while True:
        with _pg().connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT vid FROM entity WHERE vid > %s ORDER BY vid LIMIT %s",
                        [last, batch])
            vids = [r[0] for r in cur.fetchall()]
            if not vids:
                break
            rows = store.structured_query(
                f"FETCH PROP ON `Entity` {', '.join(_q(v) for v in vids)} "
                "YIELD id(vertex) AS vid;")
            live = {r.get("vid") for r in rows or []}
            dead = [v for v in vids if v not in live]
            if apply:
                cur.execute("UPDATE entity SET alive = (vid = ANY(%s)) WHERE vid = ANY(%s)",
                            [list(live), vids])
        last, seen, dead_total = vids[-1], seen + len(vids), dead_total + len(dead)
        print(f"liveness: {seen} checked, {dead_total} dead last={last!r}", flush=True)
    print(f"liveness: done, {seen} rows, {dead_total} dead "
          f"({'written' if apply else 'dry run'})")


def pass_aliases(apply: bool, report: str, sample: int) -> None:
    from src.graph.nebula_store import entity_vid
    with _pg().connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT name, mention_count, alive FROM entity")
        alive, dead = {}, set()
        for name, mc, is_alive in cur.fetchall():
            if is_alive:
                alive[name] = int(mc or 0)
            else:
                dead.add(name)
        cur.execute("SELECT er_key FROM er_verdict WHERE same")
        pairs = [p for (k,) in cur.fetchall() if (p := verdict_names(k))]
    plan = plan_aliases(pairs, alive, dead)
    print(f"aliases: {len(dead)} dead names, {len(pairs)} SAME verdicts, "
          f"{len(plan)} aliases proposed")
    with open(report, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["alias", "canonical", "hops"])
        w.writeheader()
        w.writerows(plan)
    review = report.rsplit(".", 1)[0] + f".sample{sample}.csv"
    with open(review, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["alias", "canonical", "hops", "ok"])
        w.writeheader()
        w.writerows({**p, "ok": ""} for p in
                    random.Random(0).sample(plan, min(sample, len(plan))))
    print(f"aliases: all → {report}, review sample → {review}")
    if not apply:
        return
    with _pg().connection() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO entity_alias (alias, alias_norm, alias_translit, canonical_vid, "
            "canonical_name, source, confidence) VALUES (%s, %s, %s, %s, %s, "
            "'verdict_backfill', %s) ON CONFLICT (alias_norm, canonical_vid) DO NOTHING",
            [(p["alias"], norm_name(p["alias"]), translit_key(p["alias"]),
              entity_vid(p["canonical"]), p["canonical"], CONFIDENCE) for p in plan])
    print(f"aliases: {len(plan)} written")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pass_", choices=["names", "liveness", "aliases"], metavar="pass")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--report", default="entity_aliases.csv")
    ap.add_argument("--sample", type=int, default=200)
    args = ap.parse_args()
    if args.pass_ == "names":
        pass_names(args.apply)
    elif args.pass_ == "liveness":
        pass_liveness(args.apply)
    else:
        pass_aliases(args.apply, args.report, args.sample)


if __name__ == "__main__":
    sys.exit(main())
