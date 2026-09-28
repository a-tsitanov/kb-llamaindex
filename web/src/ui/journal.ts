// Journal panel: one block per run — calls, results («подробнее» = full payload), text,
// collapsed thinking, final answer, errors in red.
import type { RunJournal } from "../state/journal";
import { esc } from "./dom";

const STATUS: Record<string, string> = { running: "идёт", done: "готово", failed: "ошибка", cancelled: "остановлено" };

export function renderJournal(el: HTMLElement, runs: RunJournal[],
                              onDetails: (runId: string, callId: string) => void): void {
  el.innerHTML = runs.map((j) => `
    <div class="run" data-run="${esc(j.runId)}">
      <div class="h"><b title="${esc(j.input)}">${esc(j.input || "…")}</b>
        <span class="badge ${j.status}">${STATUS[j.status] ?? j.status}</span></div>
      ${j.lines.map((l) => l.kind === "thinking"
        ? `<details class="line"><summary>размышления</summary>${esc(l.text)}</details>`
        : `<div class="line ${l.kind}${l.ok === false ? " bad" : ""}">${esc(l.text)}${
            l.kind === "result" && l.ok !== false && l.callId
              ? `<span class="more" data-call="${esc(l.callId)}">подробнее</span>` : ""}</div>`).join("")}
    </div>`).join("");
  el.querySelectorAll<HTMLElement>(".more").forEach((m) => {
    m.onclick = () => onDetails(m.closest<HTMLElement>(".run")!.dataset.run!, m.dataset.call!);
  });
  el.scrollTop = el.scrollHeight;
}
