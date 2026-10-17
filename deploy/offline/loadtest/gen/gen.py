"""Write police/court documents from world.json with an LLM and emit their gold.

For each case a set of documents is planned (КУСП, объяснения, рапорт о проверке
ломбардов, справка о стоимости, сведения о телефонах, протокол допроса,
постановление об отказе / обвинительное заключение) plus multi-case daily
summaries. Each document gets ONLY the facts it should mention; those facts are
its gold (entities + relations). After generation every fact is checked in the
text; a document missing facts is regenerated once with the misses listed, and
whatever is still missing is dropped from that document's gold.

Stdlib only (runs on a bare host).

  LITELLM_KEY=... python gen.py --world world.json --samples orig/ --out corpus/ \
      --url http://localhost:4000/v1/chat/completions --model small --workers 12

Output: corpus/docs/<doc_id>.md, corpus/gold.jsonl (one line per document),
corpus/gen.log.jsonl. Re-running skips documents already in gold.jsonl.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

DOC_TYPES = {
    # type: (title for the prompt, sample keyword, sample file preference, target chars)
    "kusp": ("Рапорт оперативного дежурного / протокол принятия устного заявления о преступлении (КУСП)",
             "КУСП", ["12"], 2500),
    "expl_victim": ("Объяснение потерпевшего (заявителя), полученное сотрудником полиции", "ОБЪЯСНЕНИЕ", [], 3500),
    "expl_witness": ("Объяснение очевидца (свидетеля), полученное сотрудником полиции", "ОБЪЯСНЕНИЕ", [], 2500),
    "pawn_report": ("Рапорт оперуполномоченного о проверке ломбардов и скупок на предмет сдачи похищенного имущества",
                    "ломбард", ["3", "5"], 3000),
    "price_ref": ("Запрос сотрудника полиции о стоимости имущества и ответная справка организации",
                  "СПРАВКА", ["3", "11"], 2000),
    "phone_book": ("Сведения о номерах телефонов, записанных в изъятом мобильном телефоне (ОРМ «Проверочная закупка»)",
                   "СВЕДЕНИЯ", ["23"], 3500),
    "interrogation": ("Протокол допроса подозреваемого", "ДОПРОСА", ["7", "8", "9", "10", "11"], 5000),
    "refusal": ("Постановление об отказе в возбуждении уголовного дела", "отказе в возбуждении", ["2", "4"], 4500),
    "indictment": ("Обвинительное заключение (обвинительный акт) по уголовному делу", "ОБВИНИТЕЛЬНОЕ", ["6", "7", "8"], 7000),
    "summary": ("Оперативная сводка дежурной части за сутки (несколько происшествий)", "сводка", ["1"], 4000),
}

SYSTEM = (
    "Ты пишешь служебные документы российских органов внутренних дел и прокуратуры. "
    "Пиши живым канцелярским языком, как реальный сотрудник: с типичными оборотами, реквизитами, "
    "шапкой и подписями. Каждый документ уникален по формулировкам и подробностям. "
    "Отвечай только текстом документа, без markdown, без пояснений."
)


# ---------------------------------------------------------------------------
# planning
# ---------------------------------------------------------------------------
class Planner:
    def __init__(self, world: dict, seed: int):
        self.w = world
        self.P = world["persons"]
        self.O = world["orgs"]
        self.r = random.Random(seed)

    def plan(self) -> list[dict]:
        docs = []
        for c in self.w["cases"]:
            docs.extend(self._case_docs(c))
        docs.extend(self._summaries())
        for i, d in enumerate(docs):
            d["doc_id"] = f"D{i + 1:05d}"
        return docs

    def _case_docs(self, c: dict) -> list[dict]:
        out = [self._doc("kusp", c, people=[(c["victim"] or c["extra"].get("representative"), "заявитель")],
                         officers=[c["officers"][1]], with_items=True)]
        claimant = c["victim"] or c["extra"].get("representative")
        if claimant:
            out.append(self._doc("expl_victim", c, people=[(claimant, "потерпевший" if c["victim"] else
                                                            "представитель потерпевшей организации")],
                                 officers=[c["officers"][0]], with_items=True, with_vehicle=True))
        for wid in c["witnesses"][:1]:
            out.append(self._doc("expl_witness", c, people=[(wid, "очевидец")], officers=[c["officers"][0]]))
        if c["crime"] in ("burglary", "robbery", "car_theft"):
            out.append(self._doc("pawn_report", c, people=[], officers=[c["officers"][0], c["officers"][2]],
                                 orgs=c["orgs"], org_staff=True, with_items=True))
        if c["crime"] in ("shoplifting", "contract"):
            out.append(self._doc("price_ref", c, people=[], officers=[c["officers"][0]], orgs=c["orgs"][:1],
                                 org_staff=True, with_items=True))
        if c["crime"] == "drugs":
            out.append(self._doc("phone_book", c, people=[(c["suspects"][0], "проверяемое лицо")],
                                 officers=[c["officers"][0], c["officers"][2]], phone_book=True))
        if c["outcome"] == "charged":
            out.append(self._doc("interrogation", c, people=[(c["suspects"][0], "подозреваемый")],
                                 officers=[c["officers"][1]], with_items=True, with_vehicle=True))
            people = [(s, "обвиняемый") for s in c["suspects"]]
            if c["victim"]:
                people.append((c["victim"], "потерпевший"))
            people += [(w, "свидетель") for w in c["witnesses"]]
            out.append(self._doc("indictment", c, people=people, officers=[c["officers"][1], c["officers"][2]],
                                 orgs=c["orgs"][:1], with_items=True, with_vehicle=True))
        else:
            people = [(c["victim"] or c["extra"].get("representative"), "заявитель")]
            people += [(s, "лицо, в отношении которого проводилась проверка") for s in c["suspects"][:1]]
            out.append(self._doc("refusal", c, people=[p for p in people if p[0]],
                                 officers=[c["officers"][1], c["officers"][2]], with_items=True))
        return out

    def _summaries(self) -> list[dict]:
        """Daily summaries: 3-5 cases of one police unit in one document."""
        by_unit: dict[str, list] = {}
        for c in self.w["cases"]:
            by_unit.setdefault(c["unit"], []).append(c)
        out = []
        for uid, cases in by_unit.items():
            self.r.shuffle(cases)
            for i in range(0, len(cases) - 2, 4):
                group = cases[i:i + self.r.randint(3, 5)]
                out.append({"type": "summary", "cases": [c["id"] for c in group], "unit": uid,
                            "people": [(c["victim"] or c["suspects"][0], "фигурант") for c in group],
                            "officers": [group[0]["officers"][1]], "orgs": [], "org_staff": False,
                            "items": False, "vehicle": False, "phone_book": False})
        return out

    def _doc(self, t, c, *, people, officers, orgs=(), org_staff=False, with_items=False,
             with_vehicle=False, phone_book=False) -> dict:
        return {"type": t, "cases": [c["id"]], "unit": c["unit"], "people": [p for p in people if p[0]],
                "officers": officers, "orgs": list(orgs), "org_staff": org_staff, "items": with_items,
                "vehicle": with_vehicle, "phone_book": phone_book}


# ---------------------------------------------------------------------------
# facts -> prompt + gold
# ---------------------------------------------------------------------------
class Facts:
    """Collects the facts of one document as prompt lines AND gold entities/relations."""

    def __init__(self, world: dict):
        self.P = world["persons"]
        self.O = world["orgs"]
        self.C = {c["id"]: c for c in world["cases"]}
        self.lines: list[str] = []
        self.ents: dict[str, dict] = {}
        self.rels: list[tuple[str, str, str]] = []

    def ent(self, key, typ, name, **kw):
        self.ents.setdefault(key, {"key": key, "type": typ, "name": name, **kw})
        return key

    def person(self, pid, role, *, contacts=True, birth=True):
        p = self.P[pid]
        k = self.ent(pid, "Person", p["full"], short=p["short"], surname=p["surname"], world_id=pid)
        s = f"- {role}: {p['full']}"
        if birth:
            b = self.ent(f"{pid}:birth", "Date", p["birth"])
            self.rels.append((k, "BIRTH_DATE", b))
            s += f", {p['birth']} г.р."
        if contacts and p.get("address"):
            a = self.ent(f"addr:{p['address']}", "Address", p["address"])
            self.rels.append((k, "ADDRESS", a))
            s += f", адрес: {p['address']}"
        if contacts and p.get("phone"):
            ph = self.ent(f"tel:{p['phone']}", "Phone", p["phone"])
            self.rels.append((k, "PHONE", ph))
            s += f", тел. {p['phone']}"
        if p.get("job") and p.get("unit"):
            o = self.org(p["unit"], with_contacts=False)
            self.rels.append((k, "WORKS_AT", o))
            s += f", {p['job']} {self.O[p['unit']]['name']}"
        self.lines.append(s)
        return k

    def officer(self, pid):
        p = self.P[pid]
        k = self.ent(pid, "Person", p["full"], short=p["short"], surname=p["surname"], world_id=pid)
        u = self.org(p["unit"], with_contacts=False)
        self.rels.append((k, "WORKS_AT", u))
        self.lines.append(f"- сотрудник: {p['position']} {self.O[p['unit']]['name']}, {p['rank']} {p['full']}")
        return k

    def org(self, oid, *, with_contacts=True):
        o = self.O[oid]
        k = self.ent(oid, "Organization", o["name"], world_id=oid)
        if with_contacts and o.get("address") and f"{oid}:line" not in self.ents:
            self.ents[f"{oid}:line"] = {"key": f"{oid}:line", "type": "_marker"}
            s = f"- организация: {o['name']}"
            a = self.ent(f"addr:{o['address']}", "Address", o["address"])
            self.rels.append((k, "ADDRESS", a))
            s += f", адрес: {o['address']}"
            if o.get("phone"):
                ph = self.ent(f"tel:{o['phone']}", "Phone", o["phone"])
                self.rels.append((k, "PHONE", ph))
                s += f", тел. {o['phone']}"
            self.lines.append(s)
        return k

    def case_line(self, c, short=False):
        s = (f"- происшествие: {c['descr']} ({c['article']}), дата: {c['date_event']}, место: {c['place']}, "
             f"КУСП № {c['kusp']} от {c['date_kusp']}")
        self.ent(f"date:{c['date_event']}", "Date", c["date_event"])
        self.ent(f"kusp:{c['kusp']}", "Document", f"КУСП № {c['kusp']}")
        a = self.ent(f"addr:{c['place']}", "Address", c["place"])
        if not short and c["amount"]:
            s += f", ущерб/сумма: {c['amount']} руб."
            self.ent(f"amt:{c['id']}", "Amount", str(c["amount"]), value=c["amount"])
        self.lines.append(s)
        return a

    def finish(self) -> dict:
        ents = [e for e in self.ents.values() if e["type"] != "_marker"]
        keys = {e["key"] for e in ents}
        rels = sorted({r for r in self.rels if r[0] in keys and r[2] in keys})
        return {"entities": ents, "relations": [list(r) for r in rels]}


def build_facts(doc: dict, world: dict) -> tuple[str, dict]:
    f = Facts(world)
    cases = [f.C[cid] for cid in doc["cases"]]
    for c in cases:
        f.case_line(c, short=doc["type"] == "summary")
    for pid in doc["officers"]:
        f.officer(pid)
    unit = f.O[doc["unit"]]
    if unit.get("head") and doc["type"] in ("refusal", "indictment", "pawn_report", "phone_book", "summary"):
        f.person(unit["head"], "начальник подразделения (утверждает документ)", contacts=False, birth=False)
    for pid, role in doc["people"]:
        f.person(pid, role)
    c = cases[0]
    if doc["type"] != "summary":
        for oid in doc["orgs"]:
            f.org(oid)
            if doc["org_staff"]:
                for p in world["persons"].values():
                    if p.get("unit") == oid and p.get("job"):
                        f.person(p["id"], "работник организации")
        if doc["items"] and c["items"]:
            items = "; ".join(f"{i['name']} — {i['qty']} шт. по {i['price']} руб." for i in c["items"])
            f.lines.append(f"- имущество/товары: {items}")
        if doc["vehicle"] and c.get("vehicle"):
            v = c["vehicle"]
            k = f.ent(f"car:{v['plate']}", "Vehicle", f"{v['model']} {v['plate']}", plate=v["plate"])
            if v.get("owner") and v["owner"] in f.ents:
                f.rels.append((v["owner"], "OWNS", k))
            f.lines.append(f"- автомобиль: {v['model']} {v['color']} цвета, г.р.з. {v['plate']}")
        ex = c["extra"]
        if c["crime"] == "phone_fraud":
            ph = f.ent(f"tel:{ex['fraud_phone']}", "Phone", ex["fraud_phone"])
            bank = f.org(c["orgs"][0], with_contacts=False)
            f.lines.append(f"- звонивший мошенник использовал номер {ex['fraud_phone']}, представлялся сотрудником "
                           f"службы безопасности {f.O[c['orgs'][0]]['name']}; деньги переведены на карту, "
                           f"оканчивающуюся на {ex['card']}")
        if c["crime"] == "beating":
            f.lines.append(f"- телесные повреждения: {ex['injuries']}")
        if c["crime"] == "drugs":
            f.lines.append(f"- изъято: {ex['substance']} массой {ex['mass_g']} г, сбыто {ex['buyer_alias']} за "
                           f"{c['amount']} руб.")
            if doc["phone_book"]:
                sp = c["suspects"][0]
                sim = f.ent(f"tel:{ex['sim']}", "Phone", ex["sim"])
                f.rels.append((sp, "PHONE", sim))
                book = []
                for e in ex["phone_book"]:
                    ph = f.ent(f"tel:{e['phone']}", "Phone", e["phone"])
                    if e.get("person"):
                        pk = f.ent(e["person"], "Person", f.P[e["person"]]["full"], short=f.P[e["person"]]["short"],
                                   surname=f.P[e["person"]]["surname"], world_id=e["person"])
                        f.rels.append((pk, "PHONE", ph))
                    book.append(f"{e['phone']} — {e['label']}")
                f.lines.append(f"- SIM-карта в телефоне проверяемого: {ex['sim']}")
                f.lines.append("- записная книжка телефона (номер — подпись контакта):\n    " + "\n    ".join(book))
    if doc["type"] == "indictment":
        sus = doc["people"][0][0]
        if c["victim"]:
            f.rels.append((sus, "CRIME_AGAINST", c["victim"]))
    return "\n".join(f.lines), f.finish()


# ---------------------------------------------------------------------------
# style samples
# ---------------------------------------------------------------------------
def load_samples(d: Path) -> dict[str, str]:
    return {p.stem: p.read_text(encoding="utf-8", errors="replace") for p in sorted(d.glob("*.txt"))}


def sample_for(t: str, samples: dict[str, str], r: random.Random, n: int = 3000) -> str:
    _, kw, pref, _ = DOC_TYPES[t]
    cands = []
    for name, text in samples.items():
        i = text.find(kw)
        if i < 0:
            i = text.lower().find(kw.lower())
        if i >= 0:
            cands.append((0 if name in pref else 1, name, max(0, i - 300)))
    if not cands:
        name = r.choice(pref or list(samples))
        return samples[name][:n]
    cands.sort()
    best = [x for x in cands if x[0] == cands[0][0]]
    _, name, start = r.choice(best)
    return samples[name][start:start + n]


def prompt_for(doc: dict, facts: str, sample: str, r: random.Random) -> str:
    title, _, _, target = DOC_TYPES[doc["type"]]
    length = int(target * r.uniform(0.7, 1.3))
    year = doc.get("year", "")
    return (
        f"Напиши документ: {title}.\n\n"
        f"ФАКТЫ (используй ВСЕ, ничего не пропускай):\n{facts}\n\n"
        "ТРЕБОВАНИЯ:\n"
        "1. Каждое ФИО, дата, телефон, адрес, сумма, номер КУСП, госномер и название организации из фактов "
        "должны явно присутствовать в тексте. ФИО можно склонять и сокращать до инициалов "
        "(«Петров А.В.», «А.В. Петров»), но хотя бы один раз укажи ФИО полностью. Телефоны можно писать "
        "в привычном виде (8-9XX-XXX-XX-XX, +7 (XXX) XXX-XX-XX).\n"
        "2. СТРОГО: не придумывай других людей с фамилиями, организаций, телефонов, адресов, госномеров, "
        "паспортных данных и номеров уголовных дел. Если у человека в фактах нет адреса или телефона — не пиши "
        "их вовсе. Адрес отдела полиции не указывай, если его нет в фактах. Если нужен ещё участник — называй его "
        "по должности без фамилии («сотрудник ОПВС», «продавец-кассир», «понятой»).\n"
        "3. Можешь добавлять правдоподобные подробности: время, обстоятельства, описание действий, "
        "ссылки на статьи УПК РФ, служебные формулы.\n"
        f"4. Объём примерно {length} символов.\n"
        "5. Не копируй людей, адреса и номера из образца — только его стиль и структуру.\n\n"
        f"ОБРАЗЕЦ СТИЛЯ (фрагмент реального документа другого дела):\n<<<\n{sample}\n>>>\n"
    )


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    return s.lower().replace("ё", "е")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def present(e: dict, text_n: str, text_d: str) -> bool:
    t = e["type"]
    if t == "Person":
        sur = _norm(e["surname"])
        stem = sur[:-2] if len(sur) > 6 else sur[:-1]
        return stem in text_n
    if t == "Phone":
        return _digits(e["name"])[-7:] in text_d
    if t == "Address":
        m = re.search(r"ул\. ([^,]+), д\. (\d+)", e["name"])
        if not m:
            return True
        street = _norm(m.group(1))[:-1]
        return street in text_n and re.search(rf"\b{m.group(2)}\b", text_n) is not None
    if t == "Organization":
        names = re.findall(r"«([^»]+)»", e["name"]) or [e["name"]]
        return all(_norm(n)[:-1] in text_n for n in names[-1:])
    if t == "Date":
        return e["name"] in text_n or e["name"][-4:] in text_n and e["name"][:5] in text_n
    if t == "Amount":
        v = str(e["value"])
        return v in text_d.replace(" ", "")  # digit runs, separators removed
    if t == "Vehicle":
        return _norm(e["plate"]).replace(" ", "")[:6] in text_n.replace(" ", "")
    if t == "Document":
        return _digits(e["name"]) in text_d
    return True


PHONE_RE = re.compile(r"(?:\+7|\b8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}\b")


def extra_phones(gold: dict, text: str) -> list[str]:
    """Phone numbers in the text that are not in the facts (the model invented them)."""
    known = {_digits(e["name"])[-10:] for e in gold["entities"] if e["type"] == "Phone"}
    return sorted({m.group(0) for m in PHONE_RE.finditer(text) if _digits(m.group(0))[-10:] not in known})


def clean(text: str) -> str:
    text = re.sub(r"^```\w*\n|\n```$", "", text.strip())
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text).replace("**", "")


def check(gold: dict, text: str) -> list[dict]:
    tn = _norm(text)
    td = _digits(text)
    return [e for e in gold["entities"] if not present(e, tn, td)]


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
def call_llm(url: str, key: str, model: str, prompt: str, temperature: float) -> str:
    body = json.dumps({"model": model, "temperature": temperature, "max_tokens": 6000,
                       "messages": [{"role": "system", "content": SYSTEM},
                                    {"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                          "Authorization": f"Bearer {key}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                j = json.loads(r.read())
            return j["choices"][0]["message"]["content"].strip()
        except Exception as e:  # noqa: BLE001 — retry any transport/server error
            if attempt == 3:
                raise
            time.sleep(10 * (attempt + 1))
            print(f"retry {attempt + 1}: {e}", file=sys.stderr)
    raise RuntimeError("unreachable")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", required=True)
    ap.add_argument("--samples", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--url", default="http://localhost:4000/v1/chat/completions")
    ap.add_argument("--model", default="small")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int, default=0, help="generate only the first N planned docs")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--plan-only", action="store_true")
    a = ap.parse_args()

    world = json.loads(Path(a.world).read_text(encoding="utf-8"))
    samples = load_samples(Path(a.samples))
    docs = Planner(world, a.seed).plan()
    out = Path(a.out)
    (out / "docs").mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for d in docs:
        counts[d["type"]] = counts.get(d["type"], 0) + 1
    print(f"planned {len(docs)} docs: {counts}", file=sys.stderr)
    if a.plan_only:
        facts, gold = build_facts(docs[0], world)
        print(facts)
        print(json.dumps(gold, ensure_ascii=False)[:1500])
        return
    if a.limit:
        docs = docs[:a.limit]

    gold_path = out / "gold.jsonl"
    done = set()
    if gold_path.exists():
        done = {json.loads(l)["doc_id"] for l in gold_path.read_text(encoding="utf-8").splitlines() if l}
    todo = [d for d in docs if d["doc_id"] not in done]
    key = os.environ["LITELLM_KEY"]
    lock = Lock()

    def work(doc: dict) -> dict:
        r = random.Random(f"{a.seed}:{doc['doc_id']}")
        facts, gold = build_facts(doc, world)
        sample = sample_for(doc["type"], samples, r)
        prompt = prompt_for(doc, facts, sample, r)
        t0 = time.monotonic()
        text = clean(call_llm(a.url, key, a.model, prompt, temperature=0.9))
        missing = check(gold, text)
        retried = False
        if missing:
            retried = True
            fix = ("\n\nВ прошлой версии ты пропустил эти факты — обязательно включи их: "
                   + "; ".join(e["name"] for e in missing))
            text = clean(call_llm(a.url, key, a.model, prompt + fix, temperature=0.7))
            missing = check(gold, text)
        miss_keys = {e["key"] for e in missing}
        gold["entities"] = [e for e in gold["entities"] if e["key"] not in miss_keys]
        gold["relations"] = [r_ for r_ in gold["relations"] if r_[0] not in miss_keys and r_[2] not in miss_keys]
        (out / "docs" / f"{doc['doc_id']}.md").write_text(text, encoding="utf-8")
        rec = {"doc_id": doc["doc_id"], "type": doc["type"], "cases": doc["cases"], **gold}
        log = {"doc_id": doc["doc_id"], "type": doc["type"], "chars": len(text), "retried": retried,
               "missing": [e["name"] for e in missing], "extra_phones": extra_phones(gold, text),
               "sec": round(time.monotonic() - t0, 1)}
        with lock:
            with open(gold_path, "a", encoding="utf-8") as g:
                g.write(json.dumps(rec, ensure_ascii=False) + "\n")
            with open(out / "gen.log.jsonl", "a", encoding="utf-8") as g:
                g.write(json.dumps(log, ensure_ascii=False) + "\n")
        return log

    n = 0
    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(work, d) for d in todo]
        for fut in as_completed(futs):
            n += 1
            try:
                lg = fut.result()
                print(f"[{n}/{len(todo)}] {lg['doc_id']} {lg['type']} {lg['chars']}c {lg['sec']}s "
                      f"retry={lg['retried']} miss={len(lg['missing'])} extra_tel={len(lg['extra_phones'])}", file=sys.stderr)
            except Exception as e:  # noqa: BLE001
                print(f"[{n}/{len(todo)}] FAILED: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
