// vis-network adapter for BoardRenderer.
import { DataSet } from "vis-data/peer";
import { Network, type Edge, type Node } from "vis-network/peer";
import type { BoardRenderer, BoardView, NodeView, Point, RendererEvent } from "./types";

const SELECTED = "#f25f9c";
const FRESH = "#3ccf6e";
const EDGE = "#3a4250";
const EDGE_HOT = "#9aa4b5";
const DIM = 0.18;
const MIN_SCALE = 0.8;

export class VisRenderer implements BoardRenderer {
  private nodes = new DataSet<Node>();
  private edges = new DataSet<Edge>();
  private net?: Network;
  private view: BoardView = { nodes: [], edges: [] };
  private focusKey: string | null = null; // node whose neighbourhood is highlighted
  private shown = 0; // node count at the last fit
  private handlers: Record<RendererEvent, ((key: string, pos?: Point) => void)[]> =
    { select: [], dragEnd: [], open: [] };

  mount(el: HTMLElement): void {
    this.net = new Network(el, { nodes: this.nodes, edges: this.edges }, {
      physics: {
        solver: "forceAtlas2Based",
        // enough pull to the centre that unlinked objects stay close (a board is often
        // half isolated objects; with weak gravity they fly to the edges and the fit shrinks
        // everything to unreadable)
        forceAtlas2Based: { gravitationalConstant: -70, springLength: 150, avoidOverlap: 1,
                            centralGravity: 0.05 },
        stabilization: { iterations: 250 },
      },
      interaction: { hover: true, tooltipDelay: 250 },
      nodes: { font: { color: "#e3e7ee", size: 14, face: "Inter, -apple-system, Segoe UI, sans-serif" },
               borderWidth: 1.5, shape: "box", margin: { top: 7, right: 10, bottom: 7, left: 10 },
               shapeProperties: { borderRadius: 9 } },
      edges: { color: { color: EDGE, highlight: EDGE_HOT, hover: EDGE_HOT },
               font: { color: "#b7bfcc", size: 11, strokeWidth: 3, strokeColor: "#0f1115" },
               smooth: { enabled: true, type: "continuous", roundness: 0.4 }, width: 1.2,
               arrows: { to: { enabled: true, scaleFactor: 0.45 } } },
    });
    this.net.on("click", (p) => {
      if (p.nodes.length) {
        const key = String(p.nodes[0]);
        this.focusKey = key;
        this.emit("select", key);
      } else {
        this.focusKey = null;
      }
      this.paint();
    });
    this.net.on("doubleClick", (p) => { if (p.nodes.length) this.emit("open", String(p.nodes[0])); });
    this.net.on("dragEnd", (p) => {
      if (!p.nodes.length || !this.net) return;
      const key = String(p.nodes[0]);
      const pos = this.net.getPositions([key])[key];
      this.emit("dragEnd", key, { x: Math.round(pos.x), y: Math.round(pos.y) });
    });
    // new objects arrived: once the layout settles, bring the whole board into view
    this.net.on("stabilized", () => {
      if (this.view.nodes.length !== this.shown) {
        this.shown = this.view.nodes.length;
        this.fit();
      }
    });
    new ResizeObserver(() => this.fit()).observe(el);
  }

  render(view: BoardView): void {
    this.view = view;
    if (this.focusKey && !view.nodes.some((n) => n.key === this.focusKey)) this.focusKey = null;
    this.paint();
  }

  private paint(): void {
    const near = this.neighbourhood();
    const want: Node[] = this.view.nodes.map((n) => this.node(n, near));
    const wantE: Edge[] = this.view.edges.map((e) => {
      const hot = !!this.focusKey && (e.from === this.focusKey || e.to === this.focusKey);
      return {
        id: e.key, from: e.from, to: e.to, title: e.label,
        label: hot ? e.label : "", // labels only around the selected object: no "related" wall
        color: { color: hot ? EDGE_HOT : EDGE, opacity: near && !hot ? DIM : 1 },
        width: hot ? 2 : 1.2,
      };
    });
    sync(this.nodes, want);
    sync(this.edges, wantE);
  }

  private node(n: NodeView, near: Set<string> | null): Node {
    const border = n.selected ? SELECTED : n.fresh ? FRESH : n.color;
    const node: Node = {
      id: n.key, label: n.label, title: n.title,
      color: { background: "#161b24", border,
               highlight: { background: "#1d2532", border: SELECTED },
               hover: { background: "#1b2230", border } },
      borderWidth: n.selected ? 3 : n.fresh ? 2 : 1.5,
      font: { size: 13 + Math.min(n.degree, 6) }, // hubs read larger
      opacity: near && !near.has(n.key) ? DIM : 1,
    };
    if (n.pin) Object.assign(node, { x: n.pin.x, y: n.pin.y, fixed: true });
    return node;
  }

  private neighbourhood(): Set<string> | null {
    if (!this.focusKey) return null;
    const near = new Set([this.focusKey]);
    for (const e of this.view.edges) {
      if (e.from === this.focusKey) near.add(e.to);
      if (e.to === this.focusKey) near.add(e.from);
    }
    return near;
  }

  private fit(): void {
    if (!this.net || !this.view.nodes.length) return;
    this.net.fit({ animation: false });
    // never fit smaller than readable: a big board is panned, not shrunk to dots
    if (this.net.getScale() < MIN_SCALE) this.net.moveTo({ scale: MIN_SCALE });
  }

  focus(key: string): void {
    this.focusKey = key;
    this.paint();
    this.net?.focus(key, { scale: 1.1, animation: true });
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
