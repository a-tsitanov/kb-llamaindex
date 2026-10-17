"""Score ER eval pairs with a Liquid d1 decision model (zero-shot, CPU).

Writes one JSONL row per pair: {id, q: {qname: P(yes)}}, plus a timing JSON.

  CUDA_VISIBLE_DEVICES= nice -n 10 python run_d1.py --model ~/models/d1-3B \
      --pairs eval_pairs.jsonl --out scores_d1-3B.jsonl --threads 16 --dtype bf16
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time

QUESTIONS = {
    "ru": {"type": "noul",
           "instructions": "Это одна и та же сущность (один и тот же человек/организация/объект)?"},
    "en": {"type": "noul",
           "instructions": "Do mentions A and B refer to the same real-world entity "
                           "(the same person, organization or object)?"},
    "ru_crit": {"type": "noul",
                "instructions": "Упоминания A и B обозначают одну и ту же сущность?",
                "criteria": {
                    "true": "одна и та же сущность, записанная по-разному: полное ФИО и фамилия с "
                            "инициалами, другой падеж, другой формат телефона или адреса, "
                            "название организации с/без ООО и кавычек",
                    "false": "разные сущности: разные люди (в т.ч. однофамильцы с другими "
                             "инициалами, именем или датой рождения), разные организации, "
                             "разные номера или адреса, общее понятие и частный случай"}},
}


def state_of(r: dict) -> dict:
    def m(x):
        d = {"name": x["name"], "type": x["label"]}
        if x.get("desc"):
            d["description"] = x["desc"]
        return d
    return {"A": m(r["a"]), "B": m(r["b"])}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, default=16)
    ap.add_argument("--dtype", default="bf16", choices=["bf16", "fp32"])
    ap.add_argument("--questions", default="ru,en,ru_crit")
    ap.add_argument("--chunk", type=int, default=128, help="requests per system_one_batch call")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--latency-n", type=int, default=30, help="single-pair calls for latency")
    a = ap.parse_args()

    import torch
    from transformers import AutoModel
    torch.set_num_threads(a.threads)
    dtype = torch.bfloat16 if a.dtype == "bf16" else torch.float32
    t0 = time.time()
    model = AutoModel.from_pretrained(os.path.expanduser(a.model), trust_remote_code=True,
                                      dtype=dtype).to("cpu")
    load_s = time.time() - t0
    rows = [json.loads(l) for l in open(a.pairs, encoding="utf-8")]
    if a.limit:
        rows = rows[: a.limit]
    qnames = a.questions.split(",")

    # warmup
    model.system_one(state_of(rows[0]), {"x": QUESTIONS[qnames[0]]})

    # single-pair latency (one question)
    lat = []
    for r in rows[: a.latency_n]:
        t = time.perf_counter()
        model.system_one(state_of(r), {"x": QUESTIONS[qnames[0]]})
        lat.append(time.perf_counter() - t)

    scores = {r["id"]: {} for r in rows}
    timing = {"model": a.model, "dtype": a.dtype, "threads": a.threads, "n_pairs": len(rows),
              "load_s": round(load_s, 1), "single_latency_ms_median": round(1000 * statistics.median(lat), 1),
              "single_latency_ms_p90": round(1000 * sorted(lat)[int(0.9 * len(lat)) - 1], 1),
              "batched": {}}
    for qn in qnames:
        q = {"x": QUESTIONS[qn]}
        tok = 0
        t = time.perf_counter()
        for i in range(0, len(rows), a.chunk):
            chunk = rows[i: i + a.chunk]
            res = model.system_one_batch([(state_of(r), q) for r in chunk])
            for r, o in zip(chunk, res):
                scores[r["id"]][qn] = float(o["answers"]["x"]["noul"])
                tok += o["usage"]["input_tokens"]
            el = time.perf_counter() - t
            print(f"[{qn}] {i + len(chunk)}/{len(rows)}  {(i + len(chunk)) / el:.1f} pairs/s", flush=True)
        el = time.perf_counter() - t
        timing["batched"][qn] = {"seconds": round(el, 1), "pairs_per_s": round(len(rows) / el, 2),
                                 "avg_tokens": round(tok / len(rows), 1)}
    with open(a.out, "w", encoding="utf-8") as f:
        for rid, s in scores.items():
            f.write(json.dumps({"id": rid, "q": s}) + "\n")
    with open(a.out.replace(".jsonl", "") + ".timing.json", "w") as f:
        json.dump(timing, f, indent=2)
    print(json.dumps(timing, indent=2))


if __name__ == "__main__":
    main()
