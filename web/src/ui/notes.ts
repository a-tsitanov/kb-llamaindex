// Notes (answers on the board): [[key]] becomes a clickable citation of a live object.
import { canon, type BoardState } from "../state/board";
import { esc } from "./dom";

export function renderNotes(el: HTMLElement, st: BoardState, onCite: (key: string) => void): void {
  const labels = new Map(st.objects.filter((o) => !o.hidden).map((o) => [o.key, o.label]));
  el.innerHTML = st.notes.slice(-4).reverse().map((n) => {
    const html = esc(n.text).replace(/\[\[([^\]]+)\]\]/g, (_, raw: string) => {
      const k = canon(st, raw);
      const label = labels.get(k);
      return label ? `<span class="cite" data-k="${esc(k)}">${esc(label)}</span>` : esc(raw.split(":").pop());
    });
    return `<div class="note">${html}</div>`;
  }).join("");
  el.querySelectorAll<HTMLElement>(".cite").forEach((c) => (c.onclick = () => onCite(c.dataset.k!)));
}
