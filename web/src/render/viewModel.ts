// Board state → renderer-neutral view.
import type { BoardState, Relation } from "../state/board";
import type { BoardView, Tone } from "./types";

const TECH = new Set(["ip", "domain", "certificate", "service", "asn"]);
export const ICON: Record<string, string> = {
  person: "👤", organization: "🏢", event: "📅", location: "📍", document: "📄", topic: "🏷",
  ip: "🖥", domain: "🌐", certificate: "🔒", service: "🔌", asn: "🛰", other: "•",
};

/** One colour per object type (graph border + legend + reference chips). */
export const TYPE_COLOR: Record<string, string> = {
  person: "#7aa2ff", organization: "#38b2ac", event: "#f0a43a", location: "#5ccf8a",
  document: "#b48cf2", topic: "#e07ab8", ip: "#8a93a3", domain: "#8a93a3",
  certificate: "#8a93a3", service: "#8a93a3", asn: "#8a93a3", other: "#6b7280",
};

export const TYPE_NAME: Record<string, string> = {
  person: "персона", organization: "организация", event: "событие", location: "место",
  document: "документ", topic: "тема", ip: "IP", domain: "домен", certificate: "сертификат",
  service: "сервис", asn: "ASN", other: "прочее",
};

// KB relation types (kept in attrs.kind_original when the board vocabulary has no word for
// them) → readable Russian; unknown ones are shown lowercased.
const KIND_RU: Record<string, string> = {
  DIPLOMACY: "дипломатия", PARTICIPATED_IN: "участник", EMPLOYMENT: "работа",
  OVERSIGHT: "надзор", ACCOMPANIMENT: "сопровождение", OWNERSHIP: "владеет",
  COOPERATION: "сотрудничество", LOCATED_IN: "место", MEMBER_OF: "член", LEADERSHIP: "руководит",
  HEADS: "руководит", MENTIONS: "упоминает", RELATED: "связан", PART_OF: "входит в",
  COMPETITION: "конкуренция", MAINTENANCE: "обслуживание", INFORMATION_SOURCE: "источник",
  CONFLICT: "конфликт", SUPPORT: "поддержка", CRITICISM: "критика", MEETING: "встреча",
  NEGOTIATION: "переговоры", SANCTIONS: "санкции", AGREEMENT: "соглашение",
  FUNDING: "финансирование", INVESTMENT: "инвестиции", TRADE: "торговля", VISIT: "визит",
  EXECUTION: "исполнение", EXPERTISE: "экспертиза", REPORTING: "сообщает",
  BUSINESS_ACTIVITY: "деятельность", APPROVAL: "одобрение", ANALYSIS: "анализ",
  OFFICIAL_STATEMENT: "заявление", INDICATOR: "показатель",
};

export function kindLabel(r: Pick<Relation, "kind" | "attrs">): string {
  const orig = typeof r.attrs?.kind_original === "string" ? r.attrs.kind_original : "";
  if (!orig) return r.kind;
  const up = orig.trim().toUpperCase().replace(/\s+/g, "_");
  return KIND_RU[up] ?? orig.toLowerCase().replace(/_/g, " ");
}

export const toneOf = (type: string): Tone =>
  TECH.has(type) ? "tech" : type === "event" ? "event" : "entity";

const MAX_LABEL = 30;
const short = (s: string) => (s.length > MAX_LABEL ? `${s.slice(0, MAX_LABEL - 1)}…` : s);

export function toView(st: BoardState, mentions: string[], latestRun?: string): BoardView {
  const visible = st.objects.filter((o) => !o.hidden);
  const keys = new Set(visible.map((o) => o.key));
  const degree = new Map<string, number>();
  for (const r of st.relations) {
    if (!keys.has(r.from_key) || !keys.has(r.to_key)) continue;
    degree.set(r.from_key, (degree.get(r.from_key) ?? 0) + 1);
    degree.set(r.to_key, (degree.get(r.to_key) ?? 0) + 1);
  }
  return {
    nodes: visible.map((o) => {
      const date = o.type === "event" && typeof o.attrs?.date === "string" ? `\n${o.attrs.date}` : "";
      const src = (o.sources ?? []).map((s) => `${s.server}.${s.tool} ${s.call_id}`);
      return {
        key: o.key,
        label: `${ICON[o.type] ?? "•"} ${short(o.label)}${date}`,
        type: o.type,
        tone: toneOf(o.type),
        color: TYPE_COLOR[o.type] ?? TYPE_COLOR.other,
        degree: degree.get(o.key) ?? 0,
        selected: mentions.includes(o.key),
        fresh: !!latestRun && o.inputs.includes(latestRun),
        pin: o.pin,
        title: [o.label, TYPE_NAME[o.type] ?? o.type, o.description ?? "", ...src]
          .filter(Boolean).join("\n"),
      };
    }),
    edges: st.relations
      .filter((r) => keys.has(r.from_key) && keys.has(r.to_key))
      .map((r) => ({ key: r.key, from: r.from_key, to: r.to_key, label: kindLabel(r) })),
  };
}
