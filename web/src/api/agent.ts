// Agent service (lens-agent) REST + run event stream, reached at /agent/*.
import type { AgentEvent } from "../state/journal";
import { api, type Settings } from "./http";
import { openStream } from "./sse";

export interface RunInfo {
  id: string;
  workspace_id: string;
  text: string;
  mentions: string[];
  status: "running" | "done" | "failed" | "cancelled";
  created_at: string;
}

export const startRun = (s: Settings, workspace_id: string, text: string, mentions: string[]) =>
  api<{ run_id: string; stream_token: string }>(s, "/agent/runs",
                                                 { method: "POST", body: { workspace_id, text, mentions } });
export const cancelRun = (s: Settings, runId: string) =>
  api<{ run_id: string }>(s, `/agent/runs/${runId}/cancel`, { method: "POST" });
export const listRuns = (s: Settings, ws: string, limit = 5) =>
  api<{ active: RunInfo | null; runs: RunInfo[] }>(s, `/agent/runs?workspace_id=${ws}&limit=${limit}`);
export const getCall = (s: Settings, runId: string, callId: string) =>
  api<{ server: string; tool: string; args: unknown; payload: unknown }>(
    s, `/agent/runs/${runId}/calls/${callId}`);

/** Streams one run from the start (or `after`) until `done`. */
export function followRun(s: Settings, runId: string, onEvent: (e: AgentEvent) => void,
                          signal: AbortSignal, firstToken?: string): Promise<void> {
  let token = firstToken;
  let finished = false;
  return openStream({
    url: async () => {
      if (!token) {
        token = (await api<{ stream_token: string }>(s, `/agent/runs/${runId}/stream_token`,
                                                     { method: "POST" })).stream_token;
      }
      const url = `/agent/runs/${runId}/events?token=${encodeURIComponent(token)}`;
      token = undefined; // next reconnect gets a fresh one
      return url;
    },
    onMessage: (m) => {
      const ev = JSON.parse(m.data) as AgentEvent;
      if (ev.type === "done") finished = true;
      onEvent(ev);
    },
    finished: () => finished,
    signal,
  });
}
