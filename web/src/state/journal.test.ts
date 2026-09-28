import { describe, expect, it } from "vitest";
import { newJournal, reduce, shortArgs, type AgentEvent } from "./journal";

let seq = 0;
const ev = (type: AgentEvent["type"], f: Record<string, unknown> = {}): AgentEvent =>
  ({ run_id: "r1", seq: ++seq, ts: "", type, ...f });

describe("journal reducer", () => {
  it("turns a run into journal lines", () => {
    seq = 0;
    const events = [
      ev("run_started", { input: { text: "Росатом", mentions: [] }, mcp: [
        { name: "kb", status: "up" }, { name: "dead", status: "down" }] }),
      ev("thinking", { delta: "хм" }), ev("thinking", { delta: "м" }),
      ev("tool_call", { call_id: "c1", server: "kb", tool: "find", args: { name: "Росатом" } }),
      ev("tool_result", { call_id: "c1", ok: true, summary: { items: 2, bytes: 2048 }, truncated: true }),
      ev("tool_call", { call_id: "c2", server: "kb", tool: "boom", args: {} }),
      ev("tool_result", { call_id: "c2", ok: false, error: "источник упал", summary: {} }),
      ev("text", { delta: "При" }), ev("text", { delta: "вет" }),
      ev("final", { answer: "Привет" }), ev("done", { status: "done" }),
    ];
    const j = events.reduce(reduce, newJournal("r1"));
    expect(j.status).toBe("done");
    expect(j.input).toBe("Росатом");
    expect(j.answer).toBe("Привет");
    expect(j.lines.map((l) => [l.kind, l.text])).toEqual([
      ["sources", "kb ✓ · dead ✗"],
      ["thinking", "хмм"],
      ["call", "→ kb.find(name=\"Росатом\")"],
      ["result", "← 2 эл., 2.0 КБ · усечено"],
      ["call", "→ kb.boom()"],
      ["result", "← источник упал"],
      ["final", "Привет"],
    ]);
    expect(j.lines[5].ok).toBe(false);
  });

  it("ignores replayed events", () => {
    seq = 0;
    const a = ev("text", { delta: "a" });
    const j = [a, a, ev("text", { delta: "b" })].reduce(reduce, newJournal("r1"));
    expect(j.lines).toEqual([{ kind: "text", text: "ab" }]);
  });

  it("shows errors and failed status", () => {
    seq = 0;
    const j = [ev("error", { where: "limit", message: "время вышло" }), ev("done", { status: "failed" })]
      .reduce(reduce, newJournal("r1"));
    expect(j.lines).toEqual([{ kind: "error", text: "limit: время вышло" }]);
    expect(j.status).toBe("failed");
  });
});

describe("shortArgs", () => {
  it("summarises arrays and cuts long values", () => {
    expect(shortArgs({ objects: [1, 2, 3], limit: 5 })).toBe("objects=[3], limit=5");
    expect(shortArgs({ q: "x".repeat(200) }, 20)).toHaveLength(20);
  });
});