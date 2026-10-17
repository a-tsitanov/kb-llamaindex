"""bge-m3 dense cosine for each eval pair (same text ER embeds: "name: desc" or name).

  CUDA_VISIBLE_DEVICES= nice -n 10 python run_bge.py --model ~/models/bge-m3 \
      --pairs eval_pairs.jsonl --out scores_bge.jsonl --threads 16
"""
from __future__ import annotations

import argparse
import json
import os


def text(x):
    return f"{x['name']}: {x['desc']}" if x.get("desc") else x["name"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, default=16)
    a = ap.parse_args()
    import torch
    from transformers import AutoModel, AutoTokenizer
    torch.set_num_threads(a.threads)
    p = os.path.expanduser(a.model)
    tok = AutoTokenizer.from_pretrained(p)
    m = AutoModel.from_pretrained(p).eval()
    rows = [json.loads(l) for l in open(a.pairs, encoding="utf-8")]
    uniq = sorted({text(r[k]) for r in rows for k in ("a", "b")})
    vec = {}
    with torch.inference_mode():
        for i in range(0, len(uniq), 64):
            b = uniq[i: i + 64]
            enc = tok(b, padding=True, truncation=True, max_length=128, return_tensors="pt")
            out = m(**enc).last_hidden_state[:, 0]
            out = torch.nn.functional.normalize(out, dim=-1)
            for t, v in zip(b, out):
                vec[t] = v
    with open(a.out, "w") as f:
        for r in rows:
            c = float(vec[text(r["a"])] @ vec[text(r["b"])])
            f.write(json.dumps({"id": r["id"], "cos": c}) + "\n")
    print("done", len(rows), "pairs,", len(uniq), "texts")


if __name__ == "__main__":
    main()
