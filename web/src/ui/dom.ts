export const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

/** True when a scrollable panel is at, or very near, its bottom — the signal for whether a
 * redraw should auto-scroll (the user hasn't scrolled up to read something earlier). */
export const isNearBottom = (
  el: { scrollTop: number; scrollHeight: number; clientHeight: number },
  slack = 32,
): boolean => el.scrollHeight - el.scrollTop - el.clientHeight <= slack;

export const esc = (s: unknown) =>
  String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" })[c]!);

let toastTimer: ReturnType<typeof setTimeout> | undefined;
export function toast(text: string, err = false): void {
  const el = $("toast");
  el.textContent = text;
  el.className = "toast" + (err ? " err" : "");
  el.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.style.display = "none"), err ? 9000 : 5000);
}
