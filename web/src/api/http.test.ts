import { describe, expect, it, vi } from "vitest";
import { loadSettings, saveSettings } from "./http";

function fakeStorage(): Storage {
  const map = new Map<string, string>();
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => { map.set(k, v); },
    removeItem: (k: string) => { map.delete(k); },
    clear: () => map.clear(),
    key: () => null,
    get length() { return map.size; },
  } as Storage;
}

describe("settings round-trip", () => {
  it("defaults to an empty key and no remembered workspace", () => {
    vi.stubGlobal("localStorage", fakeStorage());
    expect(loadSettings()).toEqual({ key: "" });
    vi.unstubAllGlobals();
  });

  it("persists and restores the selected workspace id alongside the key", () => {
    vi.stubGlobal("localStorage", fakeStorage());
    saveSettings({ key: "abc", ws: "ws-1" });
    expect(loadSettings()).toEqual({ key: "abc", ws: "ws-1" });
    vi.unstubAllGlobals();
  });

  it("drops ws once it is cleared", () => {
    vi.stubGlobal("localStorage", fakeStorage());
    saveSettings({ key: "abc", ws: "ws-1" });
    saveSettings({ key: "abc", ws: undefined });
    expect(loadSettings().ws).toBeUndefined();
    vi.unstubAllGlobals();
  });
});
