// Renderer contract (spec §7): the shell talks to any board engine through this only.
// vis-network now; cytoscape / tldraw / React Flow adapters swap in one line of main.ts.

export interface Point {
  x: number;
  y: number;
}

export type Tone = "entity" | "event" | "tech";

export interface NodeView {
  key: string;
  label: string;
  type: string;
  tone: Tone;
  selected: boolean; // mentioned in the input
  fresh: boolean; // touched by the latest run
  pin: Point | null;
  title: string; // hover text
}

export interface EdgeView {
  key: string;
  from: string;
  to: string;
  label: string;
}

export interface BoardView {
  nodes: NodeView[];
  edges: EdgeView[];
}

export type RendererEvent = "select" | "dragEnd" | "open";

export interface BoardRenderer {
  mount(el: HTMLElement): void;
  render(view: BoardView): void;
  focus(key: string): void;
  on(ev: RendererEvent, cb: (key: string, pos?: Point) => void): void;
  destroy(): void;
}

