// vis-network adapter for BoardRenderer (look of the old debug page).
import { DataSet } from "vis-data/peer";
import { Network, type Edge, type Node } from "vis-network/peer";
import type { BoardRenderer, BoardView, Point, RendererEvent } from "./types";

const TONE = { entity: "#6b8afd", event: "#e0a030", tech: "#2a9d8f" } as const;
const SELECTED = "#f25f9c";
const FRESH = "#3ccf6e";

export class VisRenderer implements BoardRenderer {
  private nodes = new DataSet<Node>();
  private edges = new DataSet<Edge>();
  private net?: Network;
  private handlers: Record<RendererEvent, ((key: string, pos?: Point) => void)[]> =
    { select: [], dragEnd: [], open: [] };

  mount(el: HTMLElement): void {
    this.net = new Network(el, { nodes: this.nodes, edges: this.edges }, {
      physics: { solver: "forceAtlas2Based", forceAtlas2Based: { gravitationalConstant: -60, springLength: 140 },
                 stabilization: { iterations: 150 } },
      interaction: { hover: true },
      nodes: { font: { color: "#d7dce4", size: 13, face: "Helvetica Neue, Arial, sans-serif" },
               borderWidth: 1.5, shape: "box", margin: { top: 8, right: 8, bottom: 8, left: 8 },
               shapeProperties: { borderRadius: 8 } },
      edges: { color: { color: "#3a4250", highlight: "#8a93a3" },
               font: { color: "#8a93a3", size: 10, strokeWidth: 0 }, smooth: { enabled: true, type: "continuous", roundness: 0.5 },
               arrows: { to: { enabled: true, scaleFactor: 0.4 } } },
    });
    this.net.on("click", (p) => { if (p.nodes.length) this.emit("select", String(p.nodes[0])); });
    this.net.on("doubleClick", (p) => { if (p.nodes.length) this.emit("open", String(p.nodes[0])); });
    this.net.on("dragEnd", (p) => {
      if (!p.nodes.length || !this.net) return;
      const key = String(p.nodes[0]);
      const pos = this.net.getPositions([key])[key];
      this.emit("dragEnd", key, { x: Math.round(pos.x), y: Math.round(pos.y) });
    });
  }

  render(view: BoardView): void {
    const want: Node[] = view.nodes.map((n) => {
      const border = n.selected ? SELECTED : n.fresh ? FRESH : TONE[n.tone];
      const node: Node = {
        id: n.key, label: n.label, title: n.title,
        color: { background: "#161b23", border, highlight: { background: "#1f2633", border: SELECTED } },
        borderWidth: n.selected ? 3 : 1.5,
      };
      if (n.pin) Object.assign(node, { x: n.pin.x, y: n.pin.y, fixed: true });
      return node;
    });
    const wantE: Edge[] = view.edges.map((e) => ({ id: e.key, from: e.from, to: e.to, label: e.label }));
    sync(this.nodes, want);
    sync(this.edges, wantE);
  }

  focus(key: string): void {
    this.net?.focus(key, { scale: 1.2, animation: true });
    this.net?.selectNodes([key]);
  }

  on(ev: RendererEvent, cb: (key: string, pos?: Point) => void): void {
    this.handlers[ev].push(cb);
  }

  destroy(): void {
    this.net?.destroy();
    this.net = undefined;
  }

  private emit(ev: RendererEvent, key: string, pos?: Point) {
    for (const cb of this.handlers[ev]) cb(key, pos);
  }
}

function sync<T extends { id?: string | number }>(ds: DataSet<T>, want: T[]) {
  const keep = new Set(want.map((w) => w.id));
  ds.update(want as any);
  ds.remove(ds.getIds().filter((id) => !keep.has(id)));
}

