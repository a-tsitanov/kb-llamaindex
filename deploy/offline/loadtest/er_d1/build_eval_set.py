"""Build the ER pre-filter eval set (JSONL) for d1 / rule / cosine baselines.

Sources
  a) er_verdict export (CSV: er_key,same)  -> subset "llm" (labels = Qwen judge opinion).
     Person pairs whose both names resolve unambiguously against world.json also get a
     gold label (subset tag "llm_person_gold").
  b) synthetic hard cases from world.json (labels = ground truth) -> subset "gold".

Row: {id, subset, cat, a:{name,label,desc}, b:{...}, y (1=SAME), y_gold (or null)}

Usage: python build_eval_set.py --verdicts data/er_verdict_sample.csv \
          --world ../../../../input/gen-v1/world.json --out data/eval_pairs.jsonl
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import random
import re

R = random.Random(42)

# ── crude Russian FIO declension (gen / dat / ins) ───────────────────────


def _decl_surname(s: str, sex: str, case: str) -> str:
    if sex == "M":
        if s.endswith(("ий", "ой")):
            return s[:-2] + {"gen": "ого", "dat": "ому", "ins": "им"}[case]
        if s.endswith(("ов", "ев", "ёв", "ин", "ын")):
            return s + {"gen": "а", "dat": "у", "ins": "ым"}[case]
        return s + {"gen": "а", "dat": "у", "ins": "ом"}[case]
    if s.endswith(("ова", "ева", "ёва", "ина", "ына")):
        return s[:-1] + {"gen": "ой", "dat": "ой", "ins": "ой"}[case]
    if s.endswith("ая"):
        return s[:-2] + {"gen": "ой", "dat": "ой", "ins": "ой"}[case]
    return s


def _decl_name(n: str, sex: str, case: str) -> str:
    if n.endswith("ия"):
        return n[:-1] + {"gen": "и", "dat": "и", "ins": "ей"}[case]
    if n.endswith("я"):
        return n[:-1] + {"gen": "и", "dat": "е", "ins": "ей"}[case]
    if n.endswith("а"):
        soft = n[-2] in "гкхжшчщ"
        return n[:-1] + {"gen": "и" if soft else "ы", "dat": "е",
                         "ins": "ой" if not n[-2] in "жшчщц" else "ей"}[case]
    if n.endswith(("й", "ь")):
        return n[:-1] + {"gen": "я", "dat": "ю", "ins": "ем"}[case]
    return n + {"gen": "а", "dat": "у", "ins": "ом"}[case]


def _decl_patr(p: str, sex: str, case: str) -> str:
    if sex == "M":
        return p + {"gen": "а", "dat": "у", "ins": "ем"}[case]
    return p[:-1] + {"gen": "ы", "dat": "е", "ins": "ой"}[case]


def fio_forms(p: dict) -> dict[str, str]:
    s, n, pt, sex = p["surname"], p["name"], p["patronymic"], p["sex"]
    ini = f"{n[0]}.{pt[0]}."
    f = {
        "full": p["full"],
        "short": f"{s} {ini}",
        "short_nospace": f"{s} {n[0]}. {pt[0]}.",
        "ini_first": f"{ini} {s}",
        "name_first": f"{n} {pt} {s}",
        "surname": s,
    }
    for c in ("gen", "dat", "ins"):
        f[f"full_{c}"] = f"{_decl_surname(s, sex, c)} {_decl_name(n, sex, c)} {_decl_patr(pt, sex, c)}"
        f[f"short_{c}"] = f"{_decl_surname(s, sex, c)} {ini}"
    return f


def item(name, label, desc=""):
    return {"name": name, "label": label, "desc": desc}


def birth_desc(p, style=0):
    y = p["birth"][-4:]
    return [f"{y} г.р.", f"дата рождения {p['birth']}", f"{p['birth']} года рождения"][style]


# ── phones / addresses / orgs ───────────────────────────────────────────


def phone_forms(ph: str) -> list[str]:
    d = ph[-10:]
    return [
        f"+7{d}",
        f"8{d}",
        f"8-{d[:3]}-{d[3:6]}-{d[6:8]}-{d[8:]}",
        f"8 ({d[:3]}) {d[3:6]}-{d[6:8]}-{d[8:]}",
        f"+7 ({d[:3]}) {d[3:6]}-{d[6:8]}-{d[8:]}",
        f"+7 {d[:3]} {d[3:6]} {d[6:8]} {d[8:]}",
    ]


ADDR_RE = re.compile(r"^(?P<reg>[^,]+), г\. (?P<city>[^,]+), ул\. (?P<st>[^,]+), д\. (?P<h>\d+)(?:, кв\. (?P<kv>\d+))?$")


def addr_forms(a: str) -> list[str]:
    m = ADDR_RE.match(a)
    if not m:
        return [a]
    g = m.groupdict()
    kv = f", кв. {g['kv']}" if g["kv"] else ""
    kv2 = f"-{g['kv']}" if g["kv"] else ""
    return [
        a,
        f"г. {g['city']}, ул. {g['st']}, д. {g['h']}{kv}",
        f"{g['city']}, {g['st']} ул., {g['h']}{kv2}",
        f"{g['reg']}, {g['city']}, улица {g['st']}, дом {g['h']}{kv}",
    ]


def addr_mutate(a: str) -> str | None:
    m = ADDR_RE.match(a)
    if not m:
        return None
    h = int(m["h"])
    nh = h + R.choice([1, 2, 3, 10])
    return a.replace(f"д. {h}", f"д. {nh}", 1)


QUOTED = re.compile(r"«([^»]+)»")


def org_forms(o: dict) -> list[str]:
    n = o["name"]
    out = [n]
    if n.startswith("ООО «"):
        core = QUOTED.search(n).group(1)
        out += [core, f"ООО \"{core}\"", f"Общество с ограниченной ответственностью «{core}»",
                f"ООО {core}"]
    elif n.startswith("магазин «"):
        q = QUOTED.findall(n)
        out += [f"магазин «{q[0]}»", f"«{q[0]}»", f"{q[0]}"]
    elif n.startswith("УМВД России «"):
        core = QUOTED.search(n).group(1)
        out += [f"УМВД «{core}»", f"Управление МВД России «{core}»"]
    elif n.startswith("УМВД России по "):
        out += [n.replace("УМВД России", "УМВД"), n.replace("УМВД России", "Управление МВД России")]
    return list(dict.fromkeys(out))


# ── builders ─────────────────────────────────────────────────────────────


def build_gold(world: dict) -> list[dict]:
    P = world["persons"]
    rows = []

    def add(cat, a, b, y):
        rows.append({"subset": "gold", "cat": cat, "a": a, "b": b, "y": y, "y_gold": y})

    persons = [p for p in P.values() if not p["namesake_of"] and p["id"] not in
               {q["namesake_of"] for q in P.values() if q["namesake_of"]}]
    # 1) FIO forms of the same person -> SAME
    fio_pairs = [("full", "short"), ("full", "ini_first"), ("short", "ini_first"),
                 ("full", "full_gen"), ("full", "full_dat"), ("full", "full_ins"),
                 ("short", "full_gen"), ("short_gen", "full"), ("short_dat", "short"),
                 ("full", "name_first"), ("short_nospace", "full"), ("full", "surname"),
                 ("short", "surname"), ("full_gen", "ini_first")]
    for p in R.sample(persons, 70):
        f = fio_forms(p)
        for x, y in R.sample(fio_pairs, 4):
            add(f"fio_same:{x}~{y}", item(f[x], "Person"), item(f[y], "Person"), 1)
    # with matching birth descriptions -> SAME
    for p in R.sample(persons, 25):
        f = fio_forms(p)
        add("fio_same_desc", item(f["full"], "Person", birth_desc(p, 1)),
            item(f["short"], "Person", birth_desc(p, 0)), 1)

    # 2) namesakes (same surname + initials, different people) -> DIFFERENT
    for q in [p for p in P.values() if p["namesake_of"]]:
        o = P[q["namesake_of"]]
        fq, fo = fio_forms(q), fio_forms(o)
        add("namesake:full~full", item(fq["full"], "Person"), item(fo["full"], "Person"), 0)
        add("namesake:full~full_gen", item(fq["full"], "Person"), item(fo["full_gen"], "Person"), 0)
        add("namesake:ini_first~full", item(fq["ini_first"], "Person"), item(fo["full"], "Person"), 0)  # ambiguous-by-name
        add("namesake:short+birth", item(fq["short"], "Person", birth_desc(q, 0)),
            item(fo["short"], "Person", birth_desc(o, 0)), 0)
        add("namesake:full+birth", item(fq["full"], "Person", birth_desc(q, 1)),
            item(fo["full"], "Person", birth_desc(o, 1)), 0)
        add("namesake:short+birth_vs_full+birth", item(fq["short"], "Person", birth_desc(q, 2)),
            item(fo["full"], "Person", birth_desc(o, 1)), 0)
        # control: same person, short+birth vs full+same birth -> SAME
        add("namesake_ctrl:short+birth~full+birth", item(fq["short"], "Person", birth_desc(q, 0)),
            item(fq["full"], "Person", birth_desc(q, 1)), 1)

    # 3) different people with same surname (different initials) -> DIFFERENT
    by_sur = {}
    for p in persons:
        by_sur.setdefault(p["surname"].replace("ё", "е"), []).append(p)
    ss = [(a, b) for v in by_sur.values() for a, b in itertools.combinations(v, 2)
          if (a["name"][0], a["patronymic"][0]) != (b["name"][0], b["patronymic"][0])]
    for a, b in R.sample(ss, min(110, len(ss))):
        fa, fb = fio_forms(a), fio_forms(b)
        x, y = R.choice([("full", "full"), ("short", "short"), ("full", "short"),
                         ("full_gen", "full"), ("ini_first", "short")])
        add(f"same_surname_diff:{x}~{y}", item(fa[x], "Person"), item(fb[y], "Person"), 0)

    # 4) male vs female forms of different people (Иванов vs Иванова) -> DIFFERENT
    stem = lambda p: re.sub(r"(а|ая)$", "", p["surname"]) if p["sex"] == "F" else p["surname"]
    mf = {}
    for p in persons:
        mf.setdefault((stem(p).replace("ё", "е"), p["sex"]), []).append(p)
    pairs = [(m, f) for (s, sx), ms in mf.items() if sx == "M"
             for m in ms for f in mf.get((s, "F"), [])]
    for m, f in R.sample(pairs, min(70, len(pairs))):
        fm, ff = fio_forms(m), fio_forms(f)
        x, y = R.choice([("full", "full"), ("short", "short"), ("short", "full"), ("full_gen", "full")])
        add(f"male_female:{x}~{y}", item(fm[x], "Person"), item(ff[y], "Person"), 0)

    # 5) orgs: format variants -> SAME; different orgs -> DIFFERENT
    orgs = list({o["name"]: o for o in world["orgs"].values()}.values())
    for o in orgs:
        fs = org_forms(o)
        for x, y in R.sample(list(itertools.combinations(fs, 2)), min(3, len(fs) * (len(fs) - 1) // 2)):
            add("org_same", item(x, "Organization"), item(y, "Organization"), 1)
    for a, b in R.sample(list(itertools.combinations(orgs, 2)), 120):
        if a["kind"] != b["kind"] and R.random() < 0.6:
            continue
        add(f"org_diff:{a['kind']}", item(R.choice(org_forms(a)), "Organization"),
            item(R.choice(org_forms(b)), "Organization"), 0)

    # 6) phones
    phones = sorted({p["phone"] for p in P.values() if p["phone"]} |
                    {o["phone"] for o in world["orgs"].values() if o.get("phone")})
    for ph in R.sample(phones, 70):
        x, y = R.sample(phone_forms(ph), 2)
        add("phone_same", item(x, "Phone"), item(y, "Phone"), 1)
    for ph in R.sample(phones, 40):
        d = list(ph[-10:])
        i = R.randrange(3, 10)
        d[i] = str((int(d[i]) + R.randint(1, 9)) % 10)
        add("phone_diff_1digit", item(R.choice(phone_forms(ph)), "Phone"),
            item(R.choice(phone_forms("+7" + "".join(d))), "Phone"), 0)
    for a, b in R.sample(list(itertools.combinations(phones, 2)), 40):
        add("phone_diff", item(R.choice(phone_forms(a)), "Phone"), item(R.choice(phone_forms(b)), "Phone"), 0)

    # 7) addresses
    addrs = sorted({p["address"] for p in P.values() if p["address"]} |
                   {o["address"] for o in world["orgs"].values() if o.get("address")})
    addrs = [a for a in addrs if ADDR_RE.match(a)]
    for a in R.sample(addrs, 70):
        x, y = R.sample(addr_forms(a), 2)
        add("addr_same", item(x, "Address"), item(y, "Address"), 1)
    for a in R.sample(addrs, 50):
        b = addr_mutate(a)
        add("addr_diff_house", item(R.choice(addr_forms(a)), "Address"), item(R.choice(addr_forms(b)), "Address"), 0)
    for a, b in R.sample(list(itertools.combinations(addrs, 2)), 30):
        add("addr_diff", item(R.choice(addr_forms(a)), "Address"), item(R.choice(addr_forms(b)), "Address"), 0)
    return rows


def person_index(world: dict) -> dict[str, set[str]]:
    """normalized name form -> set(person ids); ambiguous forms map to >1 id."""
    idx: dict[str, set[str]] = {}
    for p in world["persons"].values():
        for k, v in fio_forms(p).items():
            if k == "surname" or k.startswith(("short_g", "short_d", "short_i")):
                continue
            idx.setdefault(_n(v), set()).add(p["id"])
    return idx


def _n(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("ё", "е").replace(". ", ".")).strip()


def build_llm(path: str, world: dict) -> list[dict]:
    idx = person_index(world)
    rows = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        (na, la), (nb, lb) = json.loads(r["er_key"])
        y = 1 if r["same"] in ("t", "true", "True") else 0
        yg = None
        if la == lb == "Person":
            ia, ib = idx.get(_n(na)), idx.get(_n(nb))
            if ia and ib:
                if len(ia) == 1 and ia == ib:
                    yg = 1
                elif not (ia & ib):
                    yg = 0
        rows.append({"subset": "llm", "cat": f"llm:{la}~{lb}" if la != lb else f"llm:{la}",
                     "a": item(na, la), "b": item(nb, lb), "y": y, "y_gold": yg})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", required=True)
    ap.add_argument("--world", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    world = json.load(open(a.world, encoding="utf-8"))
    rows = build_llm(a.verdicts, world) + build_gold(world)
    with open(a.out, "w", encoding="utf-8") as f:
        for i, r in enumerate(rows):
            r = {"id": i, **r}
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    from collections import Counter
    c = Counter((r["subset"], r["cat"].split(":")[0], r["y"]) for r in rows)
    for k in sorted(c):
        print(k, c[k])
    print("llm person rows with gold:", sum(1 for r in rows if r["subset"] == "llm" and r["y_gold"] is not None))
    print("total", len(rows))


if __name__ == "__main__":
    main()
