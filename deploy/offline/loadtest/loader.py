"""Load-test loader: docx -> docs2md -> KB /api/v1/ingest, same path as the web UI form.

Converted files are sent as the .md text plus the source bytes as `original`
(stored next to the text, served by GET /api/v1/documents/{id}).

Runs inside the kb-app:offline image (httpx is there). Every submitted file is
appended to a JSONL log; a rerun with the same log skips files already accepted,
so an interrupted run resumes where it stopped.

  python loader.py --list set.txt --root /lt/all --tag lt-s1 --log /lt/lt-s1.jsonl

Env: KB_API_URL, KB_API_KEY, DOCS2MD_URL (same as the web UI).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from pathlib import Path

import httpx

KB_API_URL = os.environ["KB_API_URL"].rstrip("/")
KB_API_KEY = os.environ["KB_API_KEY"]
DOCS2MD_URL = os.environ["DOCS2MD_URL"].rstrip("/")
ASSET_IMG = re.compile(r"!\[([^\]]*)\]\(assets/[^)]*\)")

# Отступление на квотный отказ приёма (429, шаг 1.6).
QUOTA_ATTEMPTS = 3
QUOTA_DEFAULT_WAIT_S = 30
QUOTA_MAX_WAIT_S = 60


def _quota_wait(r: httpx.Response) -> int:
    try:
        wait = int(r.headers.get("Retry-After", QUOTA_DEFAULT_WAIT_S))
    except (TypeError, ValueError):
        wait = QUOTA_DEFAULT_WAIT_S
    return max(1, min(wait, QUOTA_MAX_WAIT_S))
TIMEOUT = httpx.Timeout(300.0, connect=10.0)


def done_files(log: Path) -> set[str]:
    if not log.exists():
        return set()
    out = set()
    for line in log.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if rec.get("ingest_status") in (200, 201, 202):
            out.add(rec["file"])
    return out


async def submit(
    c: httpx.AsyncClient, root: Path, rel: str, tag: str, priority: int | None, backfill: bool = False,
) -> dict:
    rec: dict = {"file": rel, "t_start": time.time()}
    data = (root / rel).read_bytes()
    files: dict = {}
    if rel.endswith(".md"):  # already text (generated corpus): skip docs2md
        markdown = data.decode("utf-8")
    else:
        t0 = time.monotonic()
        r = await c.post(
            f"{DOCS2MD_URL}/convert",
            files={"file": (Path(rel).name, data, "application/octet-stream")},
            data={"page_markers": "false"},
        )
        rec["convert_ms"] = round((time.monotonic() - t0) * 1000)
        rec["convert_status"] = r.status_code
        if r.status_code != 200:
            rec["error"] = r.text[:500]
            return rec
        markdown = ASSET_IMG.sub(lambda m: m.group(1), r.json()["markdown"])
        # Keep the source next to the text so the KB can serve the original.
        files["original"] = (Path(rel).name, data, "application/octet-stream")
    rec["md_chars"] = len(markdown)
    t0 = time.monotonic()
    # Квота графа (шаг 1.6) отвечает 429 с Retry-After: в пайплайне нет
    # места.  Загрузчик — массовый, ждать ему естественно; счётчик отказов
    # остаётся в записи, чтобы по логу было видно, что прогон упирался в
    # потолок, а не в сбой.  Исчерпав попытки, запись остаётся не-2xx, и
    # повторный прогон по тому же логу вернётся к этому файлу.
    for attempt in range(QUOTA_ATTEMPTS):
        r = await c.post(
            f"{KB_API_URL}/api/v1/ingest",
            headers={"X-API-Key": KB_API_KEY},
            files={"file": (Path(rel).stem + ".md", markdown.encode("utf-8"), "text/markdown")} | files,
            data={"department": tag}
            | ({"priority": str(priority)} if priority is not None else {})
            | ({"backfill": "true"} if backfill else {}),
        )
        if r.status_code != 429:
            break
        rec["quota_waits"] = rec.get("quota_waits", 0) + 1
        if attempt == QUOTA_ATTEMPTS - 1:
            break
        await asyncio.sleep(_quota_wait(r))
    rec["ingest_ms"] = round((time.monotonic() - t0) * 1000)
    rec["ingest_status"] = r.status_code
    try:
        rec["resp"] = r.json()
    except ValueError:
        rec["error"] = r.text[:500]
    return rec


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", required=True, help="file with paths relative to --root")
    ap.add_argument("--root", required=True)
    ap.add_argument("--tag", required=True, help="stored as documents.department")
    ap.add_argument("--log", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--priority", type=int, default=None, help="RabbitMQ priority 0..10 (live=5)")
    ap.add_argument("--backfill", action="store_true",
                    help="re-ingest: fill entity-watch journals without raising watch events")
    a = ap.parse_args()

    root, log = Path(a.root), Path(a.log)
    files = [f for f in Path(a.list).read_text(encoding="utf-8").splitlines() if f.strip()]
    skip = done_files(log)
    todo = [f for f in files if f not in skip]
    print(f"{len(files)} in list, {len(skip)} already accepted, {len(todo)} to submit", flush=True)

    queue: asyncio.Queue[str] = asyncio.Queue()
    for f in todo:
        queue.put_nowait(f)
    ok = fail = 0
    with log.open("a", encoding="utf-8") as fh:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:

            async def worker() -> None:
                nonlocal ok, fail
                while not queue.empty():
                    rel = queue.get_nowait()
                    try:
                        rec = await submit(c, root, rel, a.tag, a.priority, a.backfill)
                    except Exception as e:  # noqa: BLE001 — log and keep going
                        rec = {"file": rel, "t_start": time.time(), "error": f"{type(e).__name__}: {e}"}
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fh.flush()
                    if rec.get("ingest_status") in (200, 201, 202):
                        ok += 1
                    else:
                        fail += 1
                        print("FAIL", rel, rec.get("error", rec.get("ingest_status")), flush=True)
                    if (ok + fail) % 100 == 0:
                        print(f"submitted ok={ok} fail={fail}", flush=True)

            await asyncio.gather(*(worker() for _ in range(a.workers)))
    print(f"done ok={ok} fail={fail}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
