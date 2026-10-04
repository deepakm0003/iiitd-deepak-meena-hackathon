import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, useApi, type Signal, type StressRun, type StressRunSummary, type Trace } from "../app/api";
import { ASSET_LABEL, FACTOR_LABEL, SOURCE_LABEL } from "../app/format";

// Everything the public pages show about "a real trace" comes from the engine's API at page load: the most
// severe automatic stress test of the last 7 days (or, if there is none, the Western Alliance 8-K of 2023),
// its reasoning trace and its stress run. Nothing here is hard-coded.
const FALLBACK_EVENT = "evt_600c4206f3fa";
const KEY_FACTORS = ["S_severity", "M_sentiment_magnitude", "Q_source_credibility", "H_historical_reaction"];

export interface CaseData {
  eventId: string;
  runId: string;
  live: boolean; // true: picked from this week's automatic runs; false: the fallback filing
  ticker: string;
  company: string;
  sector: string;
  cik: number | null;
  firstSeen: string;
  date: string;
  time: string;
  filing: string;
  sourceUrl: string | null;
  headline: string;
  method: string;
  eventType: string;
  subtype: string;
  evidence: string;
  evidencePhrase: string;
  tier: string;
  factuality: string;
  sentiment: number;
  impact: number;
  percentile: number;
  pLargeMove: number;
  factors: { key: string; label: string; value: number }[];
  contributions: { label: string; value: number }[];
  pnlByAsset: { label: string; value: number }[];
  positions: number;
  pnl: number;
  ecl: number;
  cet1Before: number;
  cet1After: number;
  floors: { basel: number; rbi: number };
  k: number;
  trigger: boolean;
  checks: { key: string; ok: boolean; detail: string }[];
}

interface CaseState {
  data?: CaseData;
  error?: string;
}

const CaseContext = createContext<CaseState>({});

const titleCase = (s: string) =>
  s === s.toUpperCase() ? s.toLowerCase().replace(/\b[a-z]/g, (c) => c.toUpperCase()) : s;

function evidenceSentence(context: string, phrase: string) {
  const sentences = context.split(/(?<=[.!?])\s+/);
  const hit = sentences.find((x) => x.toLowerCase().includes(phrase.toLowerCase())) ?? phrase;
  const clean = hit.replace(/^[^A-Za-z0-9“"]+/, "").replace(/[.\s]+$/, "");
  return clean.length > 110 ? `${clean.slice(0, 107)}…` : clean;
}

function toCase(trace: Trace, signal: Signal, run: StressRun, live: boolean): CaseData {
  const w = trace.what_happened;
  const h = trace.how_important;
  const doc = w.documents[0];
  const item = doc?.title.match(/Item (\d+\.\d+)/)?.[1];
  const filing = doc?.source === "edgar" && item ? `SEC 8-K · Item ${item}` : `${SOURCE_LABEL[doc?.source ?? ""] ?? doc?.source ?? "Source"} article`;
  const seen = new Date(w.first_seen_at);
  const decision = run.decision ?? trace.why_it_matters_to_this_book;
  return {
    eventId: trace.event_id,
    runId: run.run_id,
    live,
    ticker: w.company?.ticker ?? "MACRO",
    company: w.company ? titleCase(w.company.name) : "Economy / markets",
    sector: w.company?.sector ?? "Market-wide",
    cik: w.company?.cik ?? null,
    firstSeen: w.first_seen_at,
    date: seen.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }),
    time: seen.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC",
    filing,
    sourceUrl: doc?.url ?? null,
    headline: w.headline,
    method: w.event_method.replace(":", ": "),
    eventType: w.event_type,
    subtype: (w.event_subtype ?? "").replace(/_/g, " "),
    evidence: w.event_evidence?.context
      ? evidenceSentence(w.event_evidence.context, w.event_evidence.phrase)
      : (w.evidence[0]?.text ?? w.headline).slice(0, 110),
    evidencePhrase: w.event_evidence?.phrase ?? "",
    tier: signal.alert_tier,
    factuality: w.factuality,
    sentiment: w.sentiment_score,
    impact: h.impact_score,
    percentile: h.percentile,
    pLargeMove: h.p_large_move,
    factors: KEY_FACTORS.map((k) => ({ key: k[0], label: FACTOR_LABEL[k], value: h.factors[k] ?? 0 })),
    contributions: Object.entries(h.contributions)
      .sort((a, b) => b[1] - a[1])
      .map(([k, v]) => ({ label: FACTOR_LABEL[k] ?? k, value: v })),
    pnlByAsset: Object.entries(run.pnl_by_asset_class)
      .filter(([, v]) => v !== 0)
      .sort((a, b) => a[1] - b[1])
      .map(([k, v]) => ({ label: ASSET_LABEL[k] ?? k, value: v })),
    positions: run.n_positions_affected,
    pnl: run.pnl_total,
    ecl: run.ecl_change,
    cet1Before: run.capital.cet1_ratio_before,
    cet1After: run.capital.cet1_ratio_after,
    floors: run.capital.floors,
    k: run.scenario.k,
    trigger: decision?.trigger ?? false,
    checks: Object.entries(decision?.checks ?? {}).map(([key, c]) => ({ key, ok: c.ok, detail: c.detail })),
  };
}

async function tryCase(run: StressRunSummary, live: boolean): Promise<CaseData | null> {
  const id = run.event_id;
  if (!id) return null;
  try {
    const [trace, signal, full] = await Promise.all([
      api<Trace>(`/signals/${id}/trace`),
      api<Signal>(`/signals/${id}`),
      api<StressRun>(`/stress-test/${run.run_id}`),
    ]);
    return toCase(trace, signal, full, live);
  } catch {
    // re-scoring re-clusters events: a run can outlive the signal it was made for
    return null;
  }
}

async function loadCase(): Promise<CaseData> {
  const runs = await api<StressRunSummary[]>("/stress-runs?limit=200");
  const weekAgo = Date.now() - 7 * 86400e3;
  const recent = runs
    .filter((r) => r.trigger === "auto" && r.event_id && r.signal_available !== false && r.pnl_total < 0 && new Date(r.created_at).getTime() > weekAgo)
    .sort((a, b) => a.pnl_total - b.pnl_total);
  for (const run of recent.slice(0, 8)) {
    const found = await tryCase(run, true);
    if (found) return found;
  }
  // no usable automatic run this week: the Western Alliance 8-K, run now if it has no stress run yet
  const [fallback] = await api<StressRunSummary[]>(`/stress-runs?event_id=${FALLBACK_EVENT}&limit=1`);
  const found = fallback ? await tryCase(fallback, false) : null;
  if (found) return found;
  const run = await api<StressRun>("/stress-test", { method: "POST", body: JSON.stringify({ event_id: FALLBACK_EVENT }) });
  const [trace, signal] = await Promise.all([
    api<Trace>(`/signals/${FALLBACK_EVENT}/trace`),
    api<Signal>(`/signals/${FALLBACK_EVENT}`),
  ]);
  return toCase(trace, signal, run, false);
}

export function CaseProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<CaseState>({});
  useEffect(() => {
    let alive = true;
    loadCase()
      .then((data) => alive && setState({ data }))
      .catch((e: Error) => alive && setState({ error: e.message }));
    return () => {
      alive = false;
    };
  }, []);
  return <CaseContext.Provider value={state}>{children}</CaseContext.Provider>;
}

export const useCase = () => useContext(CaseContext);

// ---- validation numbers, as last measured (GET /model/metrics reads docs/results/*.json)
export interface EventScores {
  n: number;
  accuracy: number;
  macro_f1: number;
  entity_accuracy: number | null;
  per_class: Record<string, { precision: number; recall: number; support: number }>;
}

export interface Metrics {
  human_labels: number;
  event_classes: number;
  assumptions: number;
  locked_test: { before: EventScores | null; after: EventScores | null };
  fresh_test: (EventScores & { tiers: Record<string, { alerts: number; correct: number; precision: number }> }) | null;
  impact: { n: number; auc: number; spearman: number; brier: number; brier_base_rate: number } | null;
  agreement: { event_kappa: number; entity_kappa: number; n: number } | null;
  sources: Record<string, { file: string; updated_at: string }>;
}

export const useMetrics = () => useApi<Metrics>("/model/metrics");

export const fmtMoney = (v: number) => `${v < 0 ? "−" : "+"}$${(Math.abs(v) / 1e6).toFixed(2)}M`;
export const fmtPct = (v: number) => `${(v * 100).toFixed(2)}%`;
