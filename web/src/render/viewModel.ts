// Board state → renderer-neutral view.
import type { BoardState } from "../state/board";
import type { BoardView, Tone } from "./types";

const TECH = new Set(["ip", "domain", "certificate", "service", "asn"]);
export const ICON: Record<string, string> = {
  person: "👤", organization: "🏢", event: "📅", location: "📍", document: "📄", topic: "🏷",
  ip: "🖥", domain: "🌐", certificate: "🔒", service: "🔌", asn: "🛰", other: "•",
};

export const toneOf = (type: string): Tone =>
  TECH.has(type) ? "tech" : type === "event" ? "event" : "entity";

export function toView(st: BoardState, mentions: string[], latestRun?: string): BoardView {
  const visible = st.objects.filter((o) => !o.hidden);
  const keys = new Set(visible.map((o) => o.key));
  return {
    nodes: visible.map((o) => {
      const date = o.type === "event" && typeof o.attrs?.date === "string" ? `\n${o.attrs.date}` : "";
      const src = (o.sources ?? []).map((s) => `${s.server}.${s.tool} ${s.call_id}`);
      return {
        key: o.key,
        label: `${ICON[o.type] ?? "•"} ${o.label}${date}`,
        type: o.type,
        tone: toneOf(o.type),
        selected: mentions.includes(o.key),
        fresh: !!latestRun && o.inputs.includes(latestRun),
        pin: o.pin,
        title: [o.key, o.type, o.description ?? "", ...src].filter(Boolean).join("\n"),
      };
    }),
    edges: st.relations
      .filter((r) => keys.has(r.from_key) && keys.has(r.to_key))
      .map((r) => ({ key: r.key, from: r.from_key, to: r.to_key, label: r.kind })),
  };
}
