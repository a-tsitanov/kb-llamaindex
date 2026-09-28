import { describe, expect, it } from "vitest";
import type { BoardState } from "../state/board";
import { toView } from "./viewModel";

const st: BoardState = {
  objects: [
    { key: "kb:e1", type: "event", label: "Встреча", attrs: { date: "2024-05-16" }, inputs: ["r1"],
      hidden: false, pin: null, description: "саммит",
      sources: [{ server: "kb", tool: "find", call_id: "c2", run_id: "r1", namespace: "kb" }] },
    { key: "kb:p1", type: "person", label: "Персона", attrs: {}, inputs: ["r2"], hidden: false,
      pin: { x: 1, y: 2 } },
    { key: "kb:h", type: "ip", label: "10.0.0.1", attrs: {}, inputs: ["r1"], hidden: true, pin: null },
  ],
  relations: [
    { key: "kb:p1|участник|kb:e1", from_key: "kb:p1", to_key: "kb:e1", kind: "участник" },
    { key: "kb:h|связан|kb:e1", from_key: "kb:h", to_key: "kb:e1", kind: "связан" },
  ],
  notes: [], aliases: {}, inputs: ["r1", "r2"], last_seq: 5,
};

describe("toView", () => {
  it("maps visible objects and relations between them", () => {
    const v = toView(st, ["kb:p1"], "r2");
    expect(v.nodes.map((n) => [n.key, n.tone, n.selected, n.fresh])).toEqual([
      ["kb:e1", "event", false, false], ["kb:p1", "entity", true, true]]);
    expect(v.nodes[0].label).toBe("📅 Встреча\n2024-05-16");
    expect(v.nodes[0].title).toBe("kb:e1\nevent\nсаммит\nkb.find c2");
    expect(v.nodes[1].pin).toEqual({ x: 1, y: 2 });
    expect(v.edges).toEqual([{ key: "kb:p1|участник|kb:e1", from: "kb:p1", to: "kb:e1", label: "участник" }]);
  });
});

