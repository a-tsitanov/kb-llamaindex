"""Run the Lens normalizer benchmark against the real LLM (no cache).

Usage:
  uv run python scripts/lens_normalizer_bench.py [--model <litellm model>] [--glob '*.json']
Prints per-fixture scores and the aggregate (valid_rate, recall, precision, type_acc).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from src.lens.config import lens_settings
from src.lens.llm import OpenAICompatLLM
from src.lens.model import ToolCallRecord
from src.lens.normalizer import Normalizer
from src.lens.shape import shape_hash
from src.lens.store import MemoryLensStore
from tests.eval.lens_normalizer.scoring import aggregate, score

FIXTURES = Path("tests/eval/lens_normalizer/fixtures")


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=lens_settings.normalizer_model())
    p.add_argument("--glob", default="*.json")
    a = p.parse_args()

    llm = OpenAICompatLLM()
    scores = []
    for path in sorted(FIXTURES.glob(a.glob)):
        try:
            fx = json.loads(path.read_text())
            norm = Normalizer(llm, MemoryLensStore(), model=a.model,
                              vocabulary=lens_settings.vocabulary,
                              aggregate_threshold=lens_settings.aggregate_threshold,
                              sample_chars=lens_settings.sample_chars)
            call = ToolCallRecord(id=path.stem, input_id=None, server=fx["server"],
                                  namespace=fx.get("namespace"), tool=fx["tool"], args=fx["args"], payload=fx["payload"],
                                  shape_hash=shape_hash(fx["payload"]), latency_ms=0)
            result = await norm.normalize(call, fx.get("description", ""))
            s = score(result, fx["golden"])
            scores.append(s)
            print(f"{path.name:40s} source={result.source:6s} {s}")
        except Exception as e:
            s = {"valid": False, "recall": 0.0, "precision": 0.0, "type_acc": 0.0}
            scores.append(s)
            print(f"{path.name:40s} ERROR {e}")
    print("AGGREGATE", json.dumps(aggregate(scores), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
