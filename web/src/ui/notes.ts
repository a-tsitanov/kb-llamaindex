// Notes (answers on the board): rendered text with [[key]] chips of live objects.
import type { BoardState } from "../state/board";
import { bindRefs, richText } from "./rich";

export function renderNotes(el: HTMLElement, st: BoardState, onCite: (key: string) => void): void {
  const notes = st.notes.slice(-4).reverse();
  el.innerHTML = notes.length
    ? `<div class="ptitle">Заметки на доске</div>` +
      notes.map((n) => `<div class="note">${richText(n.text, st)}</div>`).join("")
    : `<div class="ptitle">Заметки на доске</div><div class="empty">Ответы агента появятся здесь</div>`;
  bindRefs(el, onCite);
}
