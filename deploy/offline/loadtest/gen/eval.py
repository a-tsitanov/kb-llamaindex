"""Score the knowledge graph built from the generated corpus against its world.

Under the nebula backend the graph keeps no per-document mention list (only
`first_doc_id` on entities/edges), so scoring is corpus-level:

  * recall      — share of gold entities / relations (union over the ingested
                  documents) that have a matching node / edge in the graph;
  * duplicates  — world persons that ended up as 2+ graph nodes (ER missed);
  * false merges— graph Person nodes whose attached facts (phone, birth date,
                  address) belong to 2+ different world persons (ER over-merged;
                  the namesake pairs are the trap for this);
  * noise       — Person / Phone nodes first seen in corpus documents that match
                  nothing in the world (hallucinated or invented by the writer).

Runs inside the worker container (needs the app's nebula store):

  docker cp eval.py kb-worker-1:/tmp/ && docker exec -w /app kb-worker-1 \
    python /tmp/eval.py --world /tmp/world.json --gold /tmp/gold.jsonl \
      --docmap /tmp/docmap.tsv --out /tmp/eval.json

docmap.tsv: "<kb document uuid>\\t<D-id>" for every COMPLETED corpus document.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys


def norm(s: str) -> str:
    return re.sub(r"[«»\"'“”]", "", (s or "").lower().replace("ё", "е")).strip()


def digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def phone_key(s: str) -> str | None:
    d = digits(s)
    return d[-10:] if len(d) >= 10 else None


DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b")


def date_keys(s: str) -> set[str]:
    out = set()
    for m in DATE_RE.finditer(s or ""):
        out.add(f"{m[1]}.{m[2]}.{m[3]}" if m[1] else f"{m[6]}.{m[5]}.{m[4]}")
    return out


ADDR_RE = re.compile(r"ул\.?\s*([а-яё\-]+)[^\d]{0,20}?д\.?\s*(\d+)", re.I)


def addr_key(s: str) -> str | None:
    m = ADDR_RE.search(norm(s))
    return f"{m[1][:5]}|{m[2]}" if m else None


def male_base(surname: str, sex: str) -> str:
    if sex == "F" and surname.endswith("ая"):
        return surname[:-2] + "ий"
    if sex == "F" and surname.endswith("а"):
        return surname[:-1]
    return surname


class PersonIndex:
    """Name -> candidate world persons. Handles case endings and initials."""

    def __init__(self, persons: dict):
        self.P = persons
        self.by_stem: dict[str, list[str]] = collections.defaultdict(list)
        for pid, p in persons.items():
            base = norm(male_base(p["surname"], p["sex"]))
            self.by_stem[base[:-1] if len(base) > 4 else base].append(pid)

    def match(self, name: str) -> set[str]:
        n = norm(name)
        toks = re.findall(r"[а-я]+", n)
        cands: set[str] = set()
        for t in toks:
            if len(t) < 4:
                continue
            for k in range(len(t), 3, -1):
                if t[:k] in self.by_stem:
                    cands.update(self.by_stem[t[:k]])
                    break
        if not cands:
            return set()
        # initials "А.В." or full first name / patronymic narrow it down
        inits = re.findall(r"\b([а-я])\.\s*([а-я])\.", n)
        out = set()
        for pid in cands:
            p = self.P[pid]
            fn, pn = norm(p["name"]), norm(p["patronymic"])
            if inits:
                if any(a == fn[0] and b == pn[0] for a, b in inits):
                    out.add(pid)
                continue
            words = [t for t in toks if len(t) >= 3]
            has_fn = any(w[:3] == fn[:3] for w in words)
            has_pn = any(w[:4] == pn[:4] for w in words)
            if has_fn and (has_pn or len(words) == 2):
                out.add(pid)
            elif len(words) == 1:  # bare surname: ambiguous but counts as a mention
                out.add(pid)
        return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--docmap", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    from src.graph.nebula_store import build_nebula_graph_store

    world = json.load(open(a.world, encoding="utf-8"))
    P, O = world["persons"], world["orgs"]
    docmap = dict(line.split("\t") for line in open(a.docmap).read().split("\n") if "\t" in line)
    did2uuid = {v.strip(): k.strip() for k, v in docmap.items()}
    gold = [json.loads(l) for l in open(a.gold, encoding="utf-8") if l.strip()]
    gold = [g for g in gold if g["doc_id"] in did2uuid]

    # ---- gold union ---------------------------------------------------------
    g_ents: dict[str, dict] = {}
    g_rels: set[tuple] = set()
    for g in gold:
        for e in g["entities"]:
            g_ents.setdefault(e["key"], e)
        for s, r, d in g["relations"]:
            g_rels.add((s, r, d))

    # ---- graph pull -----------------------------------------------------------
    store = build_nebula_graph_store()
    nodes: dict[str, dict] = {}
    for i, (uuid, did) in enumerate(docmap.items()):
        rows = store.structured_query(
            f'MATCH (e:Entity) WHERE e.Entity.first_doc_id == "{uuid}" RETURN id(e) AS vid, '
            'e.Entity.name AS name, e.Entity.label AS label, e.Entity.description AS descr')
        for r in rows:
            nodes[r["vid"]] = r | {"doc": did}
        if i % 100 == 0:
            print(f"pulled {i}/{len(docmap)} docs, {len(nodes)} nodes", file=sys.stderr)
    edges = []
    vids = list(nodes)
    for i in range(0, len(vids), 300):
        chunk = ",".join(f'"{v}"' for v in vids[i:i + 300])
        edges += store.structured_query(
            f"GO FROM {chunk} OVER RELATED BIDIRECT YIELD DISTINCT src(edge) AS s, dst(edge) AS t, "
            "RELATED.rel_type AS rel")
    ext = {v for e in edges for v in (e["s"], e["t"]) if v not in nodes}
    ext = list(ext)
    for i in range(0, len(ext), 300):
        chunk = ",".join(f'"{v}"' for v in ext[i:i + 300])
        for r in store.structured_query(
                f"FETCH PROP ON Entity {chunk} YIELD id(vertex) AS vid, Entity.name AS name, "
                "Entity.label AS label, Entity.description AS descr"):
            nodes[r["vid"]] = r | {"doc": None}
    print(f"nodes={len(nodes)} edges={len(edges)} (external {len(ext)})", file=sys.stderr)

    # ---- match graph nodes -> world keys --------------------------------------
    pidx = PersonIndex(P)
    phones = {phone_key(e["name"]): k for k, e in g_ents.items() if e["type"] == "Phone"}
    addrs: dict[str, list[str]] = collections.defaultdict(list)
    for k, e in g_ents.items():
        if e["type"] == "Address" and addr_key(e["name"]):
            addrs[addr_key(e["name"])].append(k)
    dates = collections.defaultdict(list)
    for k, e in g_ents.items():
        if e["type"] == "Date":
            dates[e["name"]].append(k)
    orgs = {}
    for k, e in g_ents.items():
        if e["type"] == "Organization":
            names = re.findall(r"«([^»]+)»", e["name"]) or [e["name"]]
            orgs[k] = [norm(n) for n in names]
    plates = {norm(e["plate"]).replace(" ", ""): k for k, e in g_ents.items() if e["type"] == "Vehicle"}

    node2keys: dict[str, set[str]] = {}
    for vid, n in nodes.items():
        name, lab = n["name"] or "", (n["label"] or "")
        keys: set[str] = set()
        pk = phone_key(name)
        if pk and pk in phones and lab in ("PhoneNumber", "Phone", ""):
            keys.add(phones[pk])
        elif lab == "Person":
            keys |= {pid for pid in pidx.match(name) if pid in g_ents}
        elif lab in ("PostalAddress", "Location", "Address"):
            ak = addr_key(name)
            if ak:
                keys.update(addrs.get(ak, []))
        elif lab in ("DocumentDate", "Date", "Event"):
            for d in date_keys(name):
                keys.update(dates.get(d, []))
        elif lab == "Organization":
            nn = norm(name)
            keys |= {k for k, ns in orgs.items() if all(x[:-1] in nn for x in ns[-1:])}
        nn = norm(name).replace(" ", "")
        for pl, k in plates.items():
            if pl[:6] in nn:
                keys.add(k)
        node2keys[vid] = keys

    key2nodes = collections.defaultdict(set)
    for vid, ks in node2keys.items():
        for k in ks:
            key2nodes[k].add(vid)

    # ---- metrics --------------------------------------------------------------
    by_type = collections.defaultdict(lambda: [0, 0])
    for k, e in g_ents.items():
        by_type[e["type"]][1] += 1
        if key2nodes.get(k):
            by_type[e["type"]][0] += 1
    recall = {t: {"found": f, "gold": n, "recall": round(f / n, 3)} for t, (f, n) in sorted(by_type.items())}

    adj = collections.defaultdict(set)
    rel_types = collections.Counter()
    for e in edges:
        adj[e["s"]].add(e["t"])
        adj[e["t"]].add(e["s"])
        rel_types[e["rel"]] += 1
    rel_found = collections.Counter()
    rel_total = collections.Counter()
    for s, r, d in g_rels:
        rel_total[r] += 1
        ns, nd = key2nodes.get(s, set()), key2nodes.get(d, set())
        if any(adj[x] & nd for x in ns):
            rel_found[r] += 1
    rel_recall = {r: {"found": rel_found[r], "gold": n, "recall": round(rel_found[r] / n, 3)}
                  for r, n in sorted(rel_total.items())}

    # persons: duplicates and false merges
    gold_persons = [k for k, e in g_ents.items() if e["type"] == "Person"]
    dups = {k: sorted(nodes[v]["name"] for v in key2nodes[k]) for k in gold_persons if len(key2nodes.get(k, ())) > 1}
    fact_owner = {}
    for s, r, d in g_rels:
        if r in ("PHONE", "BIRTH_DATE") and s in P:
            fact_owner[d] = s
    merges = []
    for vid, n in nodes.items():
        if (n["label"] or "") != "Person":
            continue
        owners = set()
        for nb in adj[vid]:
            for k in node2keys.get(nb, ()):
                if k in fact_owner:
                    owners.add(fact_owner[k])
        if len(owners) > 1:
            merges.append({"node": n["name"], "world": sorted(P[o]["full"] + " " + P[o]["birth"] for o in owners),
                           "namesakes": any(P[o].get("namesake_of") in owners for o in owners)})
    corpus_nodes = {v: n for v, n in nodes.items() if n["doc"]}
    noise_person = [n["name"] for n in corpus_nodes.values() if n["label"] == "Person" and not node2keys[n["vid"]]]
    noise_phone = [n["name"] for n in corpus_nodes.values() if phone_key(n["name"] or "") and not node2keys[n["vid"]]
                   and n["label"] in ("PhoneNumber", "Phone")]
    labels = collections.Counter(n["label"] for n in corpus_nodes.values())

    namesake_pairs = [(pid, p["namesake_of"]) for pid, p in P.items() if p.get("namesake_of")
                      and pid in g_ents and p["namesake_of"] in g_ents]
    namesake_merged = sum(1 for a_, b_ in namesake_pairs if key2nodes.get(a_, set()) & key2nodes.get(b_, set())
                          and any(set(m["world"]) >= {P[a_]["full"] + " " + P[a_]["birth"],
                                                      P[b_]["full"] + " " + P[b_]["birth"]} for m in merges))

    res = {
        "docs_scored": len(gold),
        "graph": {"nodes_from_corpus": len(corpus_nodes), "edges": len(edges), "labels": labels.most_common(15),
                  "rel_types": len(rel_types), "top_rel_types": rel_types.most_common(15),
                  "generic_RELATED_share": round(rel_types.get("RELATED", 0) / max(1, len(edges)), 3)},
        "entity_recall": recall,
        "relation_recall": rel_recall,
        "persons": {"gold": len(gold_persons), "found": sum(1 for k in gold_persons if key2nodes.get(k)),
                    "duplicated": len(dups), "dup_examples": dict(list(dups.items())[:10]),
                    "false_merge_nodes": len(merges), "false_merge_examples": merges[:10],
                    "namesake_pairs_in_corpus": len(namesake_pairs), "namesake_pairs_merged": namesake_merged},
        "noise": {"unmatched_person_nodes": len(noise_person), "person_examples": noise_person[:20],
                  "unmatched_phone_nodes": len(noise_phone), "phone_examples": noise_phone[:10]},
    }
    json.dump(res, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    main()
