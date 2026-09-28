export const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

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
