"""Record one real MCP response as a Lens normalizer benchmark fixture.

Usage:
  LENS_MCP_SERVERS='[...]' uv run python scripts/lens_capture_fixture.py \
      --server kb-tools --tool find_entity_by_name --args '{"name": "Росатом"}' \
      --out tests/eval/lens_normalizer/fixtures/kb_find_rosatom.json

Then fill ``golden.objects`` by hand: [{"key": "<namespace>:<id>", "type": "<vocab type>"}].
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from src.lens.config import lens_settings
from src.lens.mcp_hub import McpHub


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--server", required=True)
    p.add_argument("--tool", required=True)
    p.add_argument("--args", default="{}")
    p.add_argument("--out", required=True)
    a = p.parse_args()

    hub = McpHub([s for s in lens_settings.mcp_servers if s.name == a.server])
    await hub.start()
    try:
        info = hub.find(f"{a.server}__{a.tool}")
        res = await hub.call(a.server, a.tool, json.loads(a.args))
    finally:
        await hub.close()
    if res.is_error:
        raise SystemExit(f"tool error: {res.error}")
    ns = next(c.ns for c in lens_settings.mcp_servers if c.name == a.server)
    fixture = {"server": a.server, "namespace": ns, "tool": a.tool,
               "description": info.description if info else "",
               "args": json.loads(a.args), "payload": res.payload,
               "golden": {"objects": []}}
    Path(a.out).write_text(json.dumps(fixture, ensure_ascii=False, indent=2))
    print(f"wrote {a.out} — now fill golden.objects")


if __name__ == "__main__":
    asyncio.run(main())
