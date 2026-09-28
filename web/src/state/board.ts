// Board state as the board service returns it, plus cheap local application of ops.
// Anything that needs the server's fold rules (merge into an existing key, undo, merge,
// a seq gap) returns null: the caller re-fetches the whole board.

export interface Source {
  server: string;
  tool: string;
  call_id: string;
  run_id: string | null;
  namespace: string;
}

export interface BoardObject {
  key: string;
  type: string;
  label: string;
  description?: string | null;
  attrs: Record<string, unknown>;
  sources?: Source[];
  inputs: string[];
  hidden: boolean;
  pin: { x: number; y: number } | null;
}

export interface Relation {
  key: string;
  from_key: string;
  to_key: string;
  kind: string;
  attrs?: Record<string, unknown>;
}

export interface Note {
  key: string;
  text: string;
  cites: string[];
}

export interface BoardState {
  objects: BoardObject[];
  relations: Relation[];
  notes: Note[];
  aliases: Record<string, string>;
  inputs: string[];
  last_seq: number;
}

export interface Op {
  seq: number;
  kind: string;
  payload: Record<string, any>;
  input_id: string | null;
}

const relKey = (r: { from_key: string; kind: string; to_key: string }) =>
  `${r.from_key}|${r.kind}|${r.to_key}`;

/** New state with `ops` applied, or null when a full re-fetch is needed. */
export function applyOps(st: BoardState, ops: Op[]): BoardState | null {
  const next: BoardState = {
    ...st,
    objects: st.objects.map((o) => ({ ...o })),
    relations: [...st.relations],
    notes: [...st.notes],
    inputs: [...st.inputs],
  };
  const byKey = new Map(next.objects.map((o) => [o.key, o]));
  for (const op of [...ops].sort((a, b) => a.seq - b.seq)) {
    if (op.seq <= next.last_seq) continue;
    if (op.seq !== next.last_seq + 1) return null; // gap
    const p = op.payload;
    switch (op.kind) {
      case "pin": {
        const o = byKey.get(p.key);
        if (o) o.pin = { x: p.x, y: p.y };
        break;
      }
      case "hide":
      case "show":
        for (const k of p.keys as string[]) {
          const o = byKey.get(k);
          if (o) o.hidden = op.kind === "hide";
        }
        break;
      case "add_note": {
        const i = next.notes.findIndex((n) => n.key === p.note.key);
        if (i >= 0) next.notes[i] = p.note;
        else next.notes.push(p.note);
        break;
      }
      case "add_objects":
        for (const raw of p.objects as BoardObject[]) {
          if (byKey.has(raw.key) || raw.key in next.aliases) return null; // server merges
          const o: BoardObject = { ...raw, inputs: op.input_id ? [op.input_id] : [],
                                   hidden: false, pin: null };
          next.objects.push(o);
          byKey.set(o.key, o);
        }
        break;
      case "add_relations":
        for (const r of p.relations as Relation[]) {
          const key = relKey(r);
          if (next.relations.some((x) => x.key === key)) return null;
          next.relations.push({ ...r, key });
        }
        break;
      default:
        return null; // undo, merge, views, mode…: server fold only
    }
    if (op.input_id && !next.inputs.includes(op.input_id)) next.inputs.push(op.input_id);
    next.last_seq = op.seq;
  }
  return next;
}

/** A citation key → the object key it now lives under (after merges). */
export function canon(st: BoardState, key: string): string {
  let k = key;
  for (let i = 0; i < 10 && st.aliases[k]; i++) k = st.aliases[k];
  return k;
}