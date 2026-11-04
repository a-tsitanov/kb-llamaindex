"""Write gen-v2 documents (plan.json from world2.py) with an LLM.

Same loop as gen.py: one prompt per planned document, every fact checked in the
text, one retry with the misses listed, still-missing facts dropped from gold.
New here: identifiers that carry the hidden links (INN, card, IMEI, serial,
plate) are checked too, and the prompt forbids the model to connect anybody
beyond the given facts — the links must stay implicit.

  LITELLM_KEY=... python gen2.py --plan plan.json --samples orig/ --out corpus2/ \
      --url http://localhost:4000/v1/chat/completions --model small --workers 12

Output: corpus2/docs/<doc_id>.md, gold.jsonl, gen.log.jsonl, links.json, README.md.
Re-running skips documents already in gold.jsonl.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import gen as g1
from world2 import DOC_TYPES

SYSTEM = (
    "Ты пишешь служебные документы российских органов внутренних дел, прокуратуры, банков, операторов связи, "
    "налоговой службы, Росреестра, ГИБДД и органов местного самоуправления. Пиши живым канцелярским языком, "
    "как реальный исполнитель: с шапкой, реквизитами, типичными оборотами и подписями. Каждый документ уникален. "
    "Отвечай только текстом документа, без markdown и пояснений."
)


def title_of(t: str) -> tuple[str, int, str | None]:
    if t in DOC_TYPES:
        return DOC_TYPES[t]
    title, _, _, target = g1.DOC_TYPES[t]
    return title, target, t


def prompt_for(doc: dict, sample: str | None, r: random.Random) -> str:
    title, target, _ = title_of(doc["type"])
    length = int(target * r.uniform(0.75, 1.25))
    note = f"\nОСОБО: {doc['note']}\n" if doc.get("note") else ""
    style = (f"\nОБРАЗЕЦ СТИЛЯ (фрагмент реального документа другого дела):\n<<<\n{sample}\n>>>\n"
             if sample else "\nОформи как типовой документ этого вида.\n")
    return (
        f"Напиши документ: {title}.\n\n"
        f"ФАКТЫ (используй ВСЕ, ничего не пропускай):\n{doc['facts']}\n{note}\n"
        "ТРЕБОВАНИЯ:\n"
        "1. Каждое ФИО, дата, телефон, адрес, сумма, ИНН, номер карты, IMEI, серийный номер, госномер, номер "
        "закупки/контракта и название организации из фактов должны явно присутствовать в тексте. Номера карт, ИНН, "
        "IMEI и серийные номера пиши полностью, без маскировки. ФИО можно склонять и сокращать до инициалов, но хотя "
        "бы один раз укажи полностью.\n"
        "2. СТРОГО: не придумывай других людей с фамилиями, организаций, телефонов, адресов, карт, госномеров и "
        "номеров дел. Если нужен ещё участник — называй по должности без фамилии.\n"
        "3. СТРОГО: не делай выводов и намёков о связях между людьми и организациями сверх того, что прямо "
        "сказано в фактах (родство, знакомство, совпадение адресов или телефонов, заинтересованность). Автор "
        "документа таких связей не знает.\n"
        "4. Можешь добавлять правдоподобные подробности: время, обстоятельства, ссылки на нормы, служебные формулы.\n"
        f"5. Объём примерно {length} символов.\n"
        "6. Не копируй людей, адреса и номера из образца — только стиль и структуру.\n"
        f"{style}"
    )


def present(e: dict, tn: str, td: str) -> bool:
    t = e["type"]
    if t in ("Inn", "BankCard", "Device"):
        return g1._digits(e["name"]) in td
    if t == "Item":
        return e["serial"].lower() in tn.replace(" ", "")
    if t == "Phone":
        return g1._digits(e["name"])[-10:] in td
    if t == "Document":
        return g1._digits(e["name"]) in td
    if t == "Amount":
        return str(e["value"]) in td
    return g1.present(e, tn, td)


def check(gold: dict, text: str) -> list[dict]:
    tn, td = g1._norm(text), g1._digits(text)
    return [e for e in gold["entities"] if not present(e, tn, td)]


def readme(plan: dict) -> str:
    out = ["# gen-v2: неявные связи между преступлениями и следы коррупции", "",
           f"{len(plan['docs'])} документов (docs/*.md), эталон по документам — gold.jsonl, скрытые связи — "
           "links.json. Ни один документ не называет связь прямо: она видна только при сопоставлении "
           "телефонов, адресов, карт, ИНН, госномеров, IMEI и серийных номеров из разных документов.", "",
           "## Вопросы для демонстрации", ""]
    for lk in plan["links"]:
        docs = sorted({x for step in lk["chain"] for x in step[3]})
        out += [f"### {lk['scheme']} / {lk['instance']}", f"**Вопрос:** {lk['question']}", "",
                f"**Ответ:** {lk['answer']}", "", f"Документы цепочки: {', '.join(docs)}", ""]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--samples", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--url", default="http://localhost:4000/v1/chat/completions")
    ap.add_argument("--model", default="small")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="comma-separated doc ids")
    ap.add_argument("--seed", type=int, default=21)
    a = ap.parse_args()

    plan = json.loads(Path(a.plan).read_text(encoding="utf-8"))
    samples = g1.load_samples(Path(a.samples))
    out = Path(a.out)
    (out / "docs").mkdir(parents=True, exist_ok=True)
    (out / "links.json").write_text(json.dumps(plan["links"], ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "README.md").write_text(readme(plan), encoding="utf-8")
    docs = plan["docs"]
    if a.only:
        ids = set(a.only.split(","))
        docs = [x for x in docs if x["doc_id"] in ids]
    if a.limit:
        docs = docs[:a.limit]
    gold_path = out / "gold.jsonl"
    done = set()
    if gold_path.exists():
        done = {json.loads(l)["doc_id"] for l in gold_path.read_text(encoding="utf-8").splitlines() if l}
    todo = [x for x in docs if x["doc_id"] not in done]
    key = os.environ["LITELLM_KEY"]
    lock = Lock()

    def work(doc: dict) -> dict:
        r = random.Random(f"{a.seed}:{doc['doc_id']}")
        _, _, sample_kind = title_of(doc["type"])
        sample = g1.sample_for(sample_kind, samples, r) if sample_kind in g1.DOC_TYPES else None
        prompt = prompt_for(doc, sample, r)
        gold = {"entities": [dict(e) for e in doc["entities"]], "relations": [list(x) for x in doc["relations"]]}
        t0 = time.monotonic()
        text = g1.clean(g1.call_llm(a.url, key, a.model, prompt, temperature=0.9))
        missing = check(gold, text)
        retried = False
        if missing:
            retried = True
            fix = ("\n\nВ прошлой версии ты пропустил эти факты — обязательно включи их дословно: "
                   + "; ".join(e["name"] for e in missing))
            text = g1.clean(g1.call_llm(a.url, key, a.model, prompt + fix, temperature=0.7))
            missing = check(gold, text)
        miss = {e["key"] for e in missing}
        gold["entities"] = [e for e in gold["entities"] if e["key"] not in miss]
        gold["relations"] = [x for x in gold["relations"] if x[0] not in miss and x[2] not in miss]
        (out / "docs" / f"{doc['doc_id']}.md").write_text(text, encoding="utf-8")
        rec = {"doc_id": doc["doc_id"], "type": doc["type"], "scheme": doc["scheme"], "instance": doc["instance"],
               **gold}
        log = {"doc_id": doc["doc_id"], "type": doc["type"], "scheme": doc["scheme"], "chars": len(text),
               "retried": retried, "missing": [e["name"] for e in missing],
               "extra_phones": g1.extra_phones(gold, text), "sec": round(time.monotonic() - t0, 1)}
        with lock:
            with open(gold_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            with open(out / "gen.log.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(log, ensure_ascii=False) + "\n")
        return log

    n = 0
    with ThreadPoolExecutor(a.workers) as ex:
        futs = [ex.submit(work, x) for x in todo]
        for fut in as_completed(futs):
            n += 1
            try:
                lg = fut.result()
                print(f"[{n}/{len(todo)}] {lg['doc_id']} {lg['type']} {lg['chars']}c {lg['sec']}s "
                      f"retry={lg['retried']} miss={len(lg['missing'])} extra_tel={len(lg['extra_phones'])}",
                      file=sys.stderr)
            except Exception as e:  # noqa: BLE001
                print(f"[{n}/{len(todo)}] FAILED: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
