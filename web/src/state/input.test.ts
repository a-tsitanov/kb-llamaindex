import { describe, expect, it } from "vitest";
import { decide, isStop, toggleMention } from "./input";

describe("input protocol", () => {
  it("recognises stop words like the board router", () => {
    for (const t of ["стоп", "Стоп!", " остановись ", "прекрати.", "stop"]) expect(isStop(t)).toBe(true);
    for (const t of ["стоп-кран", "остановка Росатома", "не стоп"]) expect(isStop(t)).toBe(false);
  });

  it("decides what an Enter does", () => {
    expect(decide("Росатом", false)).toBe("send");
    expect(decide("Росатом", true)).toBe("busy");
    expect(decide("стоп", true)).toBe("stop");
    expect(decide("стоп", false)).toBe("ignore");
    expect(decide("   ", false)).toBe("ignore");
  });

  it("toggles mentions", () => {
    expect(toggleMention([], "kb:a")).toEqual(["kb:a"]);
    expect(toggleMention(["kb:a", "kb:b"], "kb:a")).toEqual(["kb:b"]);
  });
});
