// REST helper: same-origin paths (/board/*, /agent/*), key from page settings.

export interface Settings {
  key: string;
  /** Last-opened workspace id, restored on reload (undefined = none / cleared). */
  ws?: string;
}

const STORAGE = "lensWeb";

export function loadSettings(): Settings {
  try {
    return { key: "", ...JSON.parse(localStorage.getItem(STORAGE) || "{}") };
  } catch {
    return { key: "" };
  }
}

export function saveSettings(s: Settings): void {
  try {
    localStorage.setItem(STORAGE, JSON.stringify(s));
  } catch {
    /* private mode: keep in memory only */
  }
}

export class HttpError extends Error {
  constructor(public status: number, public body: string) {
    super(`${status} ${body}`);
  }
}

export async function api<T>(settings: Settings, path: string,
                             opt: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(path, {
    method: opt.method ?? "GET",
    headers: { "X-API-Key": settings.key, "Content-Type": "application/json" },
    body: opt.body === undefined ? undefined : JSON.stringify(opt.body),
  });
  if (!res.ok) throw new HttpError(res.status, await res.text());
  return res.json() as Promise<T>;
}
