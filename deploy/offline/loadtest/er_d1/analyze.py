"""Metrics for d1 / bge cosine / rule baseline over the ER eval set.

  python analyze.py --pairs data/eval_pairs.jsonl --bge out/scores_bge.jsonl \
      --d1 d1-3B=out/scores_d1-3B.jsonl --d1 omni=out/scores_d1-omni.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict

# ── rule baseline ──────────────────────────────────────────────────────

INI = re.compile(r"^([А-ЯЁ])\.(?:([А-ЯЁ])\.)?$")
PATR = re.compile(r"(ович|евич|ич|овн|евн|ичн|иничн)(а|у|ем|ы|е|ой)?$")
END_SUR = ("ого", "ому", "ым", "ой", "ом", "ая", "а", "у", "е", "ы")
END_NAME = ("ого", "ому", "ем", "ей", "ой", "ым", "ом", "а", "у", "е", "ы", "и", "я", "ю", "й", "ь")


def _strip(w, ends):
    w = w.lower().replace("ё", "е")
    for e in ends:
        if w.endswith(e) and len(w) - len(e) >= 3:
            return w[: -len(e)]
    return w


def parse_fio(s: str):
    s = re.sub(r"([А-ЯЁ]\.)\s+(?=[А-ЯЁ]\.)", r"\1", s.strip())
    toks = s.split()
    if not toks or len(toks) > 3:
        return None
    ini = [t for t in toks if INI.match(t)]
    words = [t for t in toks if not INI.match(t)]
    if any(not re.fullmatch(r"[А-ЯЁ][а-яё\-]+", w) for w in words):
        return None
    f = {"sur": None, "n": None, "p": None, "ni": None, "pi": None, "sex": None}
    if ini:
        if len(words) != 1 or len(ini) != 1:
            return None
        m = INI.match(ini[0])
        f["sur"], f["ni"], f["pi"] = words[0], m.group(1), m.group(2)
    elif len(words) == 1:
        f["sur"] = words[0]
    elif len(words) == 3:
        if PATR.search(words[2].lower()):
            f["sur"], f["n"], f["p"] = words
        elif PATR.search(words[1].lower()):
            f["n"], f["p"], f["sur"] = words
        else:
            return None
    else:
        return None
    if f["p"]:
        pm = PATR.search(f["p"].lower())
        f["sex"] = "F" if "н" in pm.group(1) else "M"
        f["pi"] = f["p"][0]
        f["proot"] = f["p"].lower().replace("ё", "е")[: pm.start()]
    if f["n"]:
        f["ni"] = f["n"][0]
        f["nstem"] = _strip(f["n"], END_NAME)
    f["sstem"] = _strip(f["sur"], END_SUR)
    return f


def _same_name(x, y):
    """Case-form tolerant first-name match: common prefix >= shorter length - 1 (min 3)."""
    x, y = x.lower().replace("ё", "е"), y.lower().replace("ё", "е")
    cp = 0
    while cp < min(len(x), len(y)) and x[cp] == y[cp]:
        cp += 1
    return cp >= max(3, min(len(x), len(y)) - 1)


YEAR = re.compile(r"(19|20)\d\d")


def rule_person(a, b):
    fa, fb = parse_fio(a["name"]), parse_fio(b["name"])
    if not fa or not fb:
        return None
    if fa["sstem"] != fb["sstem"]:
        return 0.0
    ya, yb = YEAR.search(a.get("desc") or ""), YEAR.search(b.get("desc") or "")
    if ya and yb and ya.group() != yb.group():
        return 0.0
    if fa["sex"] and fb["sex"] and fa["sex"] != fb["sex"]:
        return 0.0
    for k in ("ni", "pi"):
        if fa[k] and fb[k] and fa[k] != fb[k]:
            return 0.0
    if fa.get("n") and fb.get("n") and not _same_name(fa["n"], fb["n"]):
        return 0.0
    if fa.get("proot") and fb.get("proot") and fa["proot"] != fb["proot"]:
        return 0.0
    bare = not (fa["ni"] and fb["ni"])
    return 0.7 if bare else 1.0


def rule_phone(a, b):
    da, db = re.sub(r"\D", "", a["name"]), re.sub(r"\D", "", b["name"])
    if len(da) < 10 or len(db) < 10:
        return None
    return 1.0 if da[-10:] == db[-10:] else 0.0


ADDR_DROP = {"московская", "область", "г", "ул", "улица", "д", "дом", "кв", "квартира"}


def rule_addr(a, b):
    def toks(s):
        t = re.findall(r"[а-яёa-z0-9]+", s.lower().replace("ё", "е"))
        return sorted(x for x in t if x not in ADDR_DROP)
    return 1.0 if toks(a["name"]) == toks(b["name"]) else 0.0


ORG_DROP = {"ооо", "общество", "с", "ограниченной", "ответственностью", "магазин", "россии",
            "управление", "мвд", "умвд", "ао", "пао", "зао"}


def rule_org(a, b):
    def core(s):
        q = re.findall(r"«([^»]+)»|\"([^\"]+)\"", s)
        base = " ".join(x or y for x, y in q) if q else s
        return {t for t in re.findall(r"[а-яёa-z0-9\-]+", base.lower().replace("ё", "е")) if t not in ORG_DROP}
    ca, cb = core(a["name"]), core(b["name"])
    if not ca or not cb:
        return None
    return 1.0 if (ca <= cb or cb <= ca) else 0.0


def rule(r):
    la, lb = r["a"]["label"], r["b"]["label"]
    if la == lb == "Person":
        return rule_person(r["a"], r["b"])
    if la == lb == "Phone":
        return rule_phone(r["a"], r["b"])
    if la == lb == "Address":
        return rule_addr(r["a"], r["b"])
    if la == lb == "Organization":
        return rule_org(r["a"], r["b"])
    return None


# ── metrics ─────────────────────────────────────────────────────────────


def auc(y, s):
    pos = [v for v, t in zip(s, y) if t == 1]
    neg = [v for v, t in zip(s, y) if t == 0]
    if not pos or not neg:
        return float("nan")
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    # rank-sum with ties
    ranks, i = {}, 0
    rk = [0.0] * len(allv)
    while i < len(allv):
        j = i
        while j < len(allv) and allv[j][0] == allv[i][0]:
            j += 1
        for k in range(i, j):
            rk[k] = (i + j + 1) / 2
        i = j
    rp = sum(r for r, (_, t) in zip(rk, allv) if t == 1)
    return (rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def at_recall(y, s, target=0.99):
    """Highest threshold t keeping SAME-recall >= target (pass if s >= t);
    returns (t, recall, filter_rate = share of DIFFERENT with s < t, share of all pairs filtered)."""
    pos = sorted(v for v, t in zip(s, y) if t == 1)
    if not pos:
        return None
    k = int(len(pos) * (1 - target))  # number of positives we may lose
    t = pos[k]
    rec = sum(1 for v in pos if v >= t) / len(pos)
    neg = [v for v, tt in zip(s, y) if tt == 0]
    fr = sum(1 for v in neg if v < t) / max(1, len(neg))
    allf = sum(1 for v in s if v < t) / len(s)
    return t, rec, fr, allf


def acc(y, s, t=0.5):
    return sum(1 for v, tt in zip(s, y) if (v >= t) == (tt == 1)) / max(1, len(y))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--bge")
    ap.add_argument("--d1", action="append", default=[])
    a = ap.parse_args()
    rows = {r["id"]: r for r in (json.loads(l) for l in open(a.pairs, encoding="utf-8"))}
    sc = defaultdict(dict)  # system -> id -> score
    if a.bge:
        for l in open(a.bge):
            o = json.loads(l)
            sc["bge_cos"][o["id"]] = o["cos"]
    for spec in a.d1:
        name, path = spec.split("=", 1)
        for l in open(path):
            o = json.loads(l)
            for qn, p in o["q"].items():
                sc[f"{name}/{qn}"][o["id"]] = p
    # rule: applicable rule, else bge cosine
    for rid, r in rows.items():
        v = rule(r)
        c = sc["bge_cos"].get(rid, 0.0) if a.bge else 0.0
        sc["rule(+cos)"][rid] = v + 0.01 * c if v is not None else c * 0.69
        sc["_rule_applies"][rid] = v is not None
    # hybrid: deterministic rule where it applies, else the first d1 system
    d1_first = next((k for k in sc if "/" in k), None)
    if d1_first:
        for rid, r in rows.items():
            v = rule(r)
            sc[f"rule>{d1_first}"][rid] = v if v is not None else sc[d1_first][rid]
    systems = [k for k in sc if not k.startswith("_")]

    def subset(pred, label_key="y"):
        ids = [i for i, r in rows.items() if pred(r) and (r[label_key] is not None)]
        return ids, [rows[i][label_key] for i in ids]

    blocks = [
        ("(a) er_verdict vs LLM labels", lambda r: r["subset"] == "llm", "y"),
        ("(a') er_verdict Person, gold-resolved", lambda r: r["subset"] == "llm" and r["y_gold"] is not None, "y_gold"),
        ("(b) gold synthetic, all", lambda r: r["subset"] == "gold", "y"),
        ("(b) gold Person only", lambda r: r["subset"] == "gold" and r["a"]["label"] == "Person", "y"),
        ("(b) gold non-Person", lambda r: r["subset"] == "gold" and r["a"]["label"] != "Person", "y"),
    ]
    print("system | AUC | acc@0.5 | thr@R.99 | SAME-recall | DIFF filtered | all filtered")
    for title, pred, lk in blocks:
        ids, y = subset(pred, lk)
        print(f"\n## {title}  n={len(ids)}  SAME={sum(y)}")
        for s in systems:
            if not all(i in sc[s] for i in ids):
                continue
            v = [sc[s][i] for i in ids]
            ar = at_recall(y, v)
            print(f"{s:22s} | {auc(y, v):.3f} | {acc(y, v):.3f} | {ar[0]:.3f} | {ar[1]:.3f} | {ar[2]:.3f} | {ar[3]:.3f}")
    # per-category accuracy (gold), at 0.5
    print("\n## gold per-category accuracy @0.5")
    cats = defaultdict(list)
    for i, r in rows.items():
        if r["subset"] == "gold":
            cats[r["cat"].split(":")[0]].append(i)
    print("cat | n | " + " | ".join(systems))
    for c, ids in sorted(cats.items()):
        line = []
        for s in systems:
            if all(i in sc[s] for i in ids):
                line.append(f"{acc([rows[i]['y'] for i in ids], [sc[s][i] for i in ids]):.2f}")
            else:
                line.append("-")
        print(f"{c} | {len(ids)} | " + " | ".join(line))
    # fine-grained namesake / fio
    print("\n## namesake / fio sub-forms @0.5")
    sub = defaultdict(list)
    for i, r in rows.items():
        if r["subset"] == "gold" and r["cat"].startswith(("namesake", "fio_same:", "male_female", "same_surname")):
            sub[r["cat"]].append(i)
    for c, ids in sorted(sub.items()):
        line = [f"{acc([rows[i]['y'] for i in ids], [sc[s][i] for i in ids]):.2f}" for s in systems
                if all(i in sc[s] for i in ids)]
        print(f"{c} | {len(ids)} | " + " | ".join(line))


if __name__ == "__main__":
    main()
