// Answer text → HTML: a little markdown (bold, inline code, headings, bullets) and every
// [[key]] / [[key|alias]] as a chip of the board object (type colour + icon), clickable.
import { canon, type BoardState } from "../state/board";
import { ICON, TYPE_COLOR } from "../render/viewModel";
import { esc } from "./dom";

export function richText(text: string, st: BoardState | null): string {
  const objects = new Map((st?.objects ?? []).filter((o) => !o.hidden).map((o) => [o.key, o]));
  const lines = esc(text).split("\n").map((line) => {
    let l = line;
    const h = /^#{1,4}\s+(.*)$/.exec(l);
    if (h) return `<div class="rh">${inline(h[1])}</div>`;
    const b = /^\s*(?:[-*•]|\d+[.)])\s+(.*)$/.exec(l);
    if (b) {
      const num = /^\s*(\d+)[.)]/.exec(l);
      return `<div class="rli"><span class="rmark">${num ? num[1] + "." : "•"}</span><span>${inline(b[1])}</span></div>`;
    }
    l = inline(l);
    return l.trim() ? `<div class="rp">${l}</div>` : `<div class="rgap"></div>`;
  });
  return lines.join("");

  function inline(s: string): string {
    return s
      .replace(/\[\[([^\]]+)\]\]/g, (_, raw: string) => chip(raw))
      .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  function chip(raw: string): string {
    const [ref, alias] = raw.split("|");
    const k = st ? canon(st, ref.trim()) : ref.trim();
    const o = objects.get(k);
    if (!o) return `<span class="ref gone">${alias ?? ref.split(":").pop()}</span>`;
    const color = TYPE_COLOR[o.type] ?? TYPE_COLOR.other;
    return `<span class="ref" data-k="${esc(k)}" style="--c:${color}">` +
      `<i>${ICON[o.type] ?? "•"}</i>${esc(alias?.trim() || o.label)}</span>`;
  }
}

export function bindRefs(el: HTMLElement, onRef: (key: string) => void): void {
  el.querySelectorAll<HTMLElement>(".ref[data-k]").forEach((c) => (c.onclick = () => onRef(c.dataset.k!)));
}
