// Agent run events → journal lines (one block per run). Pure; replays are idempotent.

export interface AgentEvent {
  run_id: string;
  seq: number;
  ts: string;
  type: "run_started" | "thinking" | "text" | "tool_call" | "tool_result" | "final" | "error" | "done";
  [field: string]: any;
}

export type RunStatus = "running" | "done" | "failed" | "cancelled";

export interface JournalLine {
  kind: "sources" | "call" | "result" | "text" | "thinking" | "final" | "error";
  text: string;
  callId?: string;
  ok?: boolean;
  truncated?: boolean;
}

export interface RunJournal {
  runId: string;
  input: string;
  mentions: string[];
  lines: JournalLine[];
  status: RunStatus;
  answer?: string;
  lastSeq: number;
}

export const newJournal = (runId: string, input = "", mentions: string[] = []): RunJournal =>
  ({ runId, input, mentions, lines: [], status: "running", lastSeq: 0 });

/** Short one-line view of tool args: arrays become [n], long strings are cut. */
export function shortArgs(args: Record<string, unknown> | undefined, max = 80): string {
  const parts = Object.entries(args ?? {}).map(([k, v]) => {
    const val = Array.isArray(v) ? `[${v.length}]` : JSON.stringify(v);
    return `${k}=${val}`;
  });
  const s = parts.join(", ");
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

function resultText(ev: AgentEvent): string {
  if (!ev.ok) return ev.error ?? "ошибка";
  if (ev.cached_from) return `повтор ${ev.cached_from}`;
  const items = ev.summary?.items;
  const size = ev.summary?.bytes ?? 0;
  const kb = size >= 1024 ? `${(size / 1024).toFixed(1)} КБ` : `${size} Б`;
  return `${items != null ? `${items} эл., ` : ""}${kb}${ev.truncated ? " · усечено" : ""}`;
}

export function reduce(j: RunJournal, ev: AgentEvent): RunJournal {
  if (ev.seq <= j.lastSeq) return j;
  const lines = [...j.lines];
  const next: RunJournal = { ...j, lines, lastSeq: ev.seq };
  const appendDelta = (kind: "text" | "thinking") => {
    const last = lines[lines.length - 1];
    if (last?.kind === kind) lines[lines.length - 1] = { ...last, text: last.text + ev.delta };
    else lines.push({ kind, text: ev.delta });
  };
  switch (ev.type) {
    case "run_started":
      next.input = ev.input?.text ?? next.input;
      next.mentions = ev.input?.mentions ?? next.mentions;
      lines.push({ kind: "sources", text: (ev.mcp ?? []).map(
        (m: { name: string; status: string }) => `${m.name} ${m.status === "up" ? "✓" : "✗"}`).join(" · ") });
      break;
    case "text":
    case "thinking":
      appendDelta(ev.type);
      break;
    case "tool_call":
      lines.push({ kind: "call", callId: ev.call_id,
                   text: `→ ${ev.server}.${ev.tool}(${shortArgs(ev.args)})` });
      break;
    case "tool_result":
      // A cached result's payload lives under the original call's id, not this one's.
      lines.push({ kind: "result", callId: ev.cached_from ?? ev.call_id, ok: ev.ok, truncated: ev.truncated,
                   text: `← ${resultText(ev)}` });
      break;
    case "final": {
      next.answer = ev.answer;
      const last = lines[lines.length - 1];
      if (last?.kind === "text" && last.text.trim() === String(ev.answer).trim()) lines.pop();
      lines.push({ kind: "final", text: ev.answer });
      break;
    }
    case "error":
      lines.push({ kind: "error", text: `${ev.where}: ${ev.message}` });
      break;
    case "done":
      next.status = ev.status;
      break;
  }
  return next;
}
