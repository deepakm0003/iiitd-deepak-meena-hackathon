export const money = (v: number, digits = 1) => {
  const a = Math.abs(v);
  const sign = v < 0 ? "−" : "";
  if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(digits)}B`;
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(digits)}M`;
  if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(digits)}K`;
  return `${sign}$${a.toFixed(0)}`;
};

export const signedMoney = (v: number) => (v > 0 ? `+${money(v, 2)}` : money(v, 2));
export const pct = (v: number, digits = 2) => `${(v * 100).toFixed(digits)}%`;
export const signed = (v: number, digits = 2) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(digits)}`;

export function timeAgo(iso: string) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)} d ago`;
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export const dateTime = (iso: string) =>
  new Date(iso).toLocaleString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }) + " UTC";

export const EVENT_TYPES = [
  "Credit Event",
  "Geopolitical",
  "Macroeconomic",
  "Regulatory/Legal",
  "Cyber/Operational",
  "Natural Disaster/Supply Chain",
  "Earnings",
  "Merger/Acquisition",
  "Management Change",
  "Product Launch",
];

// The six classes Module B can translate into shocks (config/shocks.yaml).
export const STRESS_TYPES = EVENT_TYPES.slice(0, 6);

export const TYPE_COLOR: Record<string, string> = {
  "Credit Event": "#d0663f",
  Geopolitical: "#d9b46c",
  Macroeconomic: "#7fa287",
  "Regulatory/Legal": "#8f9bd0",
  "Cyber/Operational": "#b083c4",
  "Natural Disaster/Supply Chain": "#c98282",
  Earnings: "#e8d3a2",
  "Merger/Acquisition": "#6fb3b8",
  "Management Change": "#9a958b",
  "Product Launch": "#93c06f",
  Other: "#4a4a4a",
};

export const SHORT_TYPE: Record<string, string> = {
  "Regulatory/Legal": "Regulatory",
  "Cyber/Operational": "Cyber / Ops",
  "Natural Disaster/Supply Chain": "Disaster / Supply",
  "Merger/Acquisition": "M&A",
  "Management Change": "Management",
};

export const RISK_STYLE: Record<string, { bar: string; chip: string }> = {
  Critical: { bar: "bg-[#e5484d]", chip: "border-[#e5484d]/50 bg-[#e5484d]/10 text-[#ff7b7f]" },
  High: { bar: "bg-ember-bright", chip: "border-ember-bright/50 bg-ember/15 text-ember-bright" },
  Medium: { bar: "bg-gold", chip: "border-gold/40 bg-gold/10 text-gold" },
  Low: { bar: "bg-line", chip: "border-line bg-ink-3 text-mute" },
};

export const FACTOR_LABEL: Record<string, string> = {
  S_severity: "Severity",
  M_sentiment_magnitude: "Sentiment magnitude",
  E_entity_importance: "Entity importance",
  N_novelty: "Novelty",
  V_volume_corroboration: "Corroboration",
  Q_source_credibility: "Source credibility",
  H_historical_reaction: "Historical reaction",
};

export const ASSET_LABEL: Record<string, string> = {
  sme_loan: "SME loans",
  bond: "Bonds",
  corporate_loan: "Corporate loans",
  equity: "Equity",
  swap: "Swaps",
  index_put: "Index puts (hedge)",
};

export const SOURCE_LABEL: Record<string, string> = {
  edgar: "SEC EDGAR",
  gdelt: "GDELT",
  finnhub: "Finnhub",
  fed: "Federal Reserve",
  rbi: "RBI",
  bluesky: "Bluesky",
  rss: "RSS",
};

/** "MEASURED analog: ..." / "assumption A-15 (...)" -> a short provenance tag. */
export function provenanceTag(source: string): { tag: string; tone: "measured" | "assumption" | "model" } {
  const s = source.toLowerCase();
  if (s.startsWith("measured") || s.startsWith("observed")) return { tag: "MEASURED", tone: "measured" };
  if (s.includes("assumption")) {
    const id = source.match(/A-\d+/)?.[0];
    return { tag: id ? `ASSUMPTION ${id}` : "ASSUMPTION", tone: "assumption" };
  }
  return { tag: source.split(" ")[0].toUpperCase(), tone: "model" };
}
