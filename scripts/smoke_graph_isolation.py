"""Live smoke: create a graph, ingest into it, prove `default` cannot see it,
delete it.  Touches a real stack — run only with explicit approval.

    uv run python -m scripts.smoke_graph_isolation --api-base http://localhost:8000 --api-key K
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx


async def wait_for[T](
    probe: Callable[[], Awaitable[T | None]], *, timeout_s: float, interval_s: float = 3.0,
) -> T:
    """Poll ``probe`` until it returns a truthy value; raise TimeoutError past ``timeout_s``."""
    deadline = time.monotonic() + timeout_s
    while True:
        value = await probe()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise TimeoutError("condition not met in time")
        await asyncio.sleep(interval_s)


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    if not ok:
        raise SystemExit(1)


def _entities(body: dict[str, Any]) -> list[Any]:
    # `/api/v1/entities` returns {"entities": [...]} plus `error` when the
    # lookup could not run — an error must fail the smoke, not read as "absent".
    if body.get("error"):
        raise SystemExit(f"FAIL  entity lookup error: {body['error']}")
    return body.get("entities") or []


async def run(api_base: str, api_key: str, gid: str, timeout_s: float) -> None:
    key = {"X-API-Key": api_key}
    in_g = {**key, "X-Graph": gid}
    token = f"smokeiso{uuid.uuid4().hex[:8]}"
    async with httpx.AsyncClient(base_url=api_base, timeout=60.0) as http:
        r = await http.post("/api/v1/ingest", headers=in_g,
                            files={"file": ("x.txt", b"x", "text/plain")},
                            data={"document_date": "2026-10-18"})
        _check("unknown graph ingest is 404 (no auto-create)", r.status_code == 404, str(r.status_code))

        r = await http.post("/admin/graphs", headers=key, json={"id": gid, "owner": "smoke"})
        _check("create accepted", r.status_code == 202, r.text)

        async def ready():
            row = (await http.get(f"/admin/graphs/{gid}", headers=key)).json()
            if row.get("status") == "failed":
                raise SystemExit(f"FAIL  provisioning failed: {row.get('status_error')}")
            return row if row.get("status") == "ready" else None
        await wait_for(ready, timeout_s=300)
        _check("graph ready", True)

        text = f"{token} Corporation signed a contract with {token} Holdings in Berlin.".encode()
        r = await http.post("/api/v1/ingest", headers=in_g,
                            files={"file": (f"{token}.txt", text, "text/plain")},
                            data={"document_date": "2026-10-18"})
        _check("ingest into new graph accepted", r.status_code == 202, r.text)
        job = r.json()["job_id"]

        async def done():
            j = (await http.get(f"/api/v1/ingest/{job}", headers=in_g)).json()
            if j.get("status") == "failed":
                raise SystemExit(f"FAIL  ingest failed: {j.get('error')}")
            return j if j.get("status") == "completed" else None
        await wait_for(done, timeout_s=timeout_s, interval_s=10)
        _check("ingest completed in new graph", True)

        r = await http.get(f"/api/v1/ingest/{job}", headers=key)
        _check("job invisible from default", r.status_code == 404, str(r.status_code))

        hits_g = _entities((await http.get("/api/v1/entities", headers=in_g, params={"query": token})).json())
        hits_d = _entities((await http.get("/api/v1/entities", headers=key, params={"query": token})).json())
        _check("entity found in new graph", bool(hits_g), str(hits_g)[:200])
        _check("entity absent from default", not hits_d, str(hits_d)[:200])

        r = await http.delete(f"/admin/graphs/{gid}", headers=key, params={"confirm": gid})
        _check("delete accepted", r.status_code == 202, r.text)

        async def gone():
            return (await http.get(f"/admin/graphs/{gid}", headers=key)).status_code == 404
        await wait_for(gone, timeout_s=600, interval_s=10)
        _check("graph deleted", True)

        r = await http.get(f"/api/v1/ingest/{job}", headers=in_g)
        _check("deleted graph is 404", r.status_code == 404, str(r.status_code))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--api-base", default="http://localhost:8000")
    p.add_argument("--api-key", required=True)
    p.add_argument("--graph", default="smoke_iso")
    p.add_argument("--timeout", type=float, default=900.0, help="ingest completion timeout, s")
    a = p.parse_args()
    asyncio.run(run(a.api_base, a.api_key, a.graph, a.timeout))
    return 0


if __name__ == "__main__":
    sys.exit(main())
