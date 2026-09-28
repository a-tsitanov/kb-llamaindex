import { describe, expect, it } from "vitest";
import { applyOps, canon, type BoardState, type Op } from "./board";

const obj = (key: string) => ({ key, type: "person", label: key, attrs: {} });
const base = (): BoardState => ({
  objects: [{ ...obj("kb:a"), inputs: ["r1"], hidden: false, pin: null }],
  relations: [],
  notes: [],
  aliases: { "kb:old": "kb:a" },
  inputs: ["r1"],
  last_seq: 1,
});
const op = (seq: number, kind: string, payload: Record<string, unknown>, input_id: string | null = "r2"): Op =>
  ({ seq, kind, payload, input_id });

describe("applyOps", () => {
  it("applies new objects, relations, notes, hide and pin in seq order", () => {
    const st = applyOps(base(), [
      op(3, "add_relations", { relations: [{ from_key: "kb:b", to_key: "kb:a", kind: "связан" }] }),
      op(2, "add_objects", { objects: [obj("kb:b")] }),
      op(4, "add_note", { note: { key: "note:r2", text: "см. [[kb:b]]", cites: ["kb:b"] } }),
      op(5, "hide", { keys: ["kb:a"] }),
      op(6, "pin", { key: "kb:b", x: 1, y: 2 }, null),
    ])!;
    expect(st.last_seq).toBe(6);
    expect(st.objects.map((o) => [o.key, o.hidden, o.inputs])).toEqual([
      ["kb:a", true, ["r1"]], ["kb:b", false, ["r2"]]]);
    expect(st.objects[1].pin).toEqual({ x: 1, y: 2 });
    expect(st.relations[0].key).toBe("kb:b|связан|kb:a");
    expect(st.notes).toHaveLength(1);
    expect(st.inputs).toEqual(["r1", "r2"]);
  });

  it("replaces a note with the same key and skips already-seen ops", () => {
    const once = applyOps(base(), [op(2, "add_note", { note: { key: "note:r2", text: "a", cites: [] } })])!;
    const twice = applyOps(once, [
      op(2, "add_note", { note: { key: "note:r2", text: "dup", cites: [] } }),
      op(3, "add_note", { note: { key: "note:r2", text: "b", cites: [] } }),
    ])!;
    expect(twice.notes.map((n) => n.text)).toEqual(["b"]);
  });

  it("asks for a refetch on gaps, merges into existing keys, undo and merge ops", () => {
    expect(applyOps(base(), [op(3, "hide", { keys: [] })])).toBeNull();
    expect(applyOps(base(), [op(2, "add_objects", { objects: [obj("kb:a")] })])).toBeNull();
    expect(applyOps(base(), [op(2, "add_objects", { objects: [obj("kb:old")] })])).toBeNull();
    expect(applyOps(base(), [op(2, "undo", { input_id: "r1" })])).toBeNull();
    expect(applyOps(base(), [op(2, "merge", { keep: "kb:a", drop: "kb:b" })])).toBeNull();
  });

  it("does not mutate the input state", () => {
    const st = base();
    applyOps(st, [op(2, "hide", { keys: ["kb:a"] })]);
    expect(st.objects[0].hidden).toBe(false);
  });
});

describe("canon", () => {
  it("follows merge aliases", () => {
    expect(canon(base(), "kb:old")).toBe("kb:a");
    expect(canon(base(), "kb:x")).toBe("kb:x");
  });
});