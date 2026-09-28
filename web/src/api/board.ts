// Board service (lens) REST + stream, reached at /board/* (nginx → /lens/v1/*).
import type { BoardState, Op } from "../state/board";
import { api, type Settings } from "./http";
import { openStream } from "./sse";

export interface Workspace {
  id: string;
  title: string;
}

export const listWorkspaces = (s: Settings) => api<Workspace[]>(s, "/board/workspaces");
export const createWorkspace = (s: Settings, title: string) =>
  api<Workspace>(s, "/board/workspaces", { method: "POST", body: { title } });
export const getBoard = (s: Settings, ws: string) =>
  api<{ workspace: Workspace; state: BoardState }>(s, `/board/workspaces/${ws}`);
export const pin = (s: Settings, ws: string, key: string, x: number, y: number) =>
  api<{ seq: number }>(s, `/board/workspaces/${ws}/pin`, { method: "POST", body: { key, x, y } });

export type BoardEvent = { type: "ready" } | { type: "ops"; ops: Op[] } | { type: "resync" };

/** Follows the board stream; reconnects (fresh token) forever until aborted. */
export function followBoard(s: Settings, ws: string, onEvent: (e: BoardEvent) => void,
                            signal: AbortSignal): Promise<void> {
  return openStream({
    url: async () => {
      const { token } = await api<{ token: string }>(s, `/board/workspaces/${ws}/stream_token`,
                                                     { method: "POST" });
      return `/board/workspaces/${ws}/stream?token=${encodeURIComponent(token)}`;
    },
    onMessage: (m) => onEvent(JSON.parse(m.data) as BoardEvent),
    signal,
  });
}
