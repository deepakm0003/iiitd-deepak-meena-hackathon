import { useCallback, useEffect, useState } from "react";

// Dev: Vite proxies /api to the FastAPI engine. Production builds can point elsewhere with VITE_API_URL.
export const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "/api";

export type RiskLevel = "Critical" | "High" | "Medium" | "Low";

export interface Signal {
  event_id: string;
  first_seen_at: string;
  headline: string;
  primary_entity: string;
  company: { ticker: string; name: string; cik?: number; sector?: string } | null;
  affected_sectors?: string[];
  event_type: string;
  event_subtype: string | null;
  event_method: string;
  alert_tier: "confirmed" | "standard" | "none";
  sentiment_score: number;
  sentiment_label: string;
  factuality: string;
  direction?: string;
  event_evidence?: { source: string; phrase: string; context: string };
  corroboration: { n_articles: number; n_publishers: number; sources: string[]; score: number };
  impact_score: number;
  impact_breakdown: {
    percentile: number;
    factors: Record<string, number>;
    contributions: Record<string, number>;
    p_large_move: number;
  };
  p_large_move: number;
  confidence: number;
  risk_level: RiskLevel;
  explanation: string;
  evidence: { text: string; score: number; location: string }[];
  documents: { source: string; title: string; url: string | null; published_at: string }[];
  provenance?: { factors?: Record<string, string> };
}

export interface SignalStats {
  days: number;
  total: number;
  by_type: Record<string, number>;
  by_risk: Record<string, number>;
  by_day: { date: string; total: number; by_type: Record<string, number> }[];
}

export interface Check {
  ok: boolean;
  detail: string;
}

export interface Decision {
  event_id?: string;
  trigger: boolean;
  threshold: number | null;
  exposure: { direct: number; sector: number; geography: number; book_exposure: number };
  states: string[];
  hard_flags: string[];
  checks: Record<string, Check>;
}

export interface Trace {
  event_id: string;
  what_happened: {
    headline: string;
    first_seen_at: string;
    entity: string;
    company: Signal["company"];
    event_type: string;
    event_subtype: string | null;
    event_method: string;
    factuality: string;
    sentiment_score: number;
    direction?: string;
    corroboration: Signal["corroboration"];
    documents: Signal["documents"];
    evidence: Signal["evidence"];
    event_evidence?: Signal["event_evidence"];
  };
  how_important: {
    impact_score: number;
    p_large_move: number;
    confidence: number;
    risk_level: RiskLevel;
    percentile: number;
    factors: Record<string, number>;
    contributions: Record<string, number>;
    explanation: string;
    provenance?: { factors?: Record<string, string> };
  };
  why_it_matters_to_this_book: Decision | null;
  stress_available: boolean;
}

export interface Shock {
  value: number;
  source: string;
}

export interface Contributor {
  id: string;
  type: string;
  name: string;
  sector: string | null;
  exposure: number;
  dv: number;
  capital_impact: number;
  paths: { channel: string; reason: string; factor: string; shock: number; unit: string; source: string }[];
}

export interface StressRun {
  run_id: string;
  trigger: string;
  event_id: string | null;
  created_at: string;
  decision?: Decision;
  scenario: {
    name: string;
    event_type: string;
    subtype?: string | null;
    entity: string | null;
    sector: string | null;
    impact: number;
    k: number;
    layers: Record<string, Record<string, Shock>>;
  };
  pnl_total: number;
  pnl_by_asset_class: Record<string, number>;
  ecl_change: number;
  stage_migrations: unknown[];
  capital: {
    cet1_before: number;
    cet1_after: number;
    rwa_before: number;
    rwa_after: number;
    cet1_ratio_before: number;
    cet1_ratio_after: number;
    floors: { basel: number; rbi: number };
    reconciliation?: Record<string, string | number>;
  };
  n_positions_affected: number;
  unaffected_by_reason: Record<string, number>;
  top_contributors: Contributor[];
  reverse_stress?: Record<string, { floor: number; breaks_at_k: number | null; note: string }>;
  sensitivity?: Record<
    string,
    { k: number; pnl_total: number; ecl_change: number; cet1_ratio_after: number; stage_migrations: number }
  > & { note?: string };
}

export interface StressRunSummary {
  run_id: string;
  event_id: string | null;
  trigger: string;
  created_at: string;
  event_type: string;
  impact: number;
  pnl_total: number;
  cet1_ratio_after: number;
  scenario_name: string;
}

export interface Portfolio {
  as_of: string;
  description: string;
  totals: { tranche1_ead: number; tranche2_exposure: number };
  capital: { rwa: number; cet1: number; cet1_ratio: number; floors: { basel: number; rbi: number }; tax_rate: number };
  n_positions: { tranche1: number; tranche2: number };
  exposure_by_type: Record<string, number>;
  exposure_by_sector: Record<string, number>;
  exposure_by_grade: Record<string, number>;
  tranche1_exposure_by_state: Record<string, number>;
  pd_basis: string;
}

export interface WatchName {
  name: string;
  tranche: number;
  positions: string[];
  sector: string | null;
  exposure: number;
  score: number;
  status: "Red" | "Amber" | "Green";
  hard_flags: string[];
  drivers: { event_id: string; headline: string; event_type: string; impact: number; weight: number; age_days: number }[];
}

export interface Watchlist {
  as_of: string;
  lookback_days: number;
  counts: Record<"Red" | "Amber" | "Green", number>;
  exposure_by_status: Record<"Red" | "Amber" | "Green", number>;
  names: WatchName[];
}

export interface OpsStatus {
  collectors: {
    updated_at: string;
    sources: Record<
      string,
      {
        interval_minutes: number;
        runs: number;
        inserted_total: number;
        last_run: string | null;
        last_status: string;
        last_error: string | null;
        consecutive_failures: number;
        paused_until: string | null;
      }
    >;
  } | null;
  store: { ok: boolean; documents: number; signals: number; events: number };
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API_BASE + path, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.text();
    let detail = body.slice(0, 200);
    try {
      detail = JSON.parse(body).detail ?? detail;
    } catch {
      /* not JSON */
    }
    throw new Error(`${res.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  }
  return res.json() as Promise<T>;
}

// Tiny stale-while-revalidate cache so moving between pages is instant after the first load.
const cache = new Map<string, unknown>();

export function useApi<T>(path: string | null, refreshMs?: number) {
  const [data, setData] = useState<T | undefined>(() => (path ? (cache.get(path) as T | undefined) : undefined));
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(Boolean(path));
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!path) return;
    let alive = true;
    const cached = cache.get(path) as T | undefined;
    if (cached !== undefined) setData(cached);
    setLoading(true);
    api<T>(path)
      .then((d) => {
        cache.set(path, d);
        if (alive) {
          setData(d);
          setError(undefined);
        }
      })
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [path, tick]);

  useEffect(() => {
    if (!refreshMs) return;
    const t = setInterval(() => setTick((x) => x + 1), refreshMs);
    return () => clearInterval(t);
  }, [refreshMs]);

  const reload = useCallback(() => setTick((x) => x + 1), []);
  return { data, error, loading, reload };
}
