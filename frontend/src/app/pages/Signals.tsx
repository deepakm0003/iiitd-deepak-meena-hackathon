import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Activity, ArrowRight, BarChart3, Download, Layers, ShieldAlert } from "lucide-react";
import { useApi, type OpsStatus, type Signal, type SignalStats, type StressRunSummary, type Watchlist } from "../api";
import { EVENT_TYPES, RISK_STYLE, nowMs, SHORT_TYPE, SOURCE_LABEL, TYPE_COLOR, money, signed, timeAgo } from "../format";
import { ErrorNote, ImpactRing, Kpi, PageHeader, Panel, RiskChip, Skeleton, Tag, TypeChip } from "../ui";

const RISK_FILTERS = ["All", "High+", "Medium+"] as const;

export default function Signals() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q")?.trim() ?? "";
  const [type, setType] = useState<string | null>(null);
  const [risk, setRisk] = useState<(typeof RISK_FILTERS)[number]>("All");
  const [confirmedOnly, setConfirmedOnly] = useState(false);
  const [limit, setLimit] = useState(120);

  const tickerLike = /^[A-Za-z.]{1,6}$/.test(q);
  const path = tickerLike
    ? `/signals?entity=${encodeURIComponent(q.toUpperCase())}&limit=200`
    : `/signals?exclude_other=true&limit=${q ? 1000 : limit}${type ? `&event_type=${encodeURIComponent(type)}` : ""}`;
  const feed = useApi<Signal[]>(path, 60_000);
  const day = useApi<SignalStats>("/signals/stats?days=1", 60_000);
  const week = useApi<SignalStats>("/signals/stats?days=7", 120_000);
  const runs = useApi<StressRunSummary[]>("/stress-runs?limit=500", 60_000);
  const watch = useApi<Watchlist>("/watchlist?limit=1", 120_000);
  const ops = useApi<OpsStatus>("/ops/status", 60_000);

  const runEvents = useMemo(() => new Set((runs.data ?? []).map((r) => r.event_id)), [runs.data]);

  const signals = useMemo(() => {
    let list = feed.data ?? [];
    if (q && !tickerLike) {
      const words = q.toLowerCase().split(/\s+/);
      list = list.filter((s) => words.every((w) => s.headline.toLowerCase().includes(w)));
    }
    if (tickerLike && type) list = list.filter((s) => s.event_type === type);
    if (risk === "High+") list = list.filter((s) => s.risk_level === "High" || s.risk_level === "Critical");
    if (risk === "Medium+") list = list.filter((s) => s.risk_level !== "Low");
    if (confirmedOnly) list = list.filter((s) => s.alert_tier === "confirmed");
    return list;
  }, [feed.data, q, tickerLike, type, risk, confirmedOnly]);

  const weekRuns = (runs.data ?? []).filter((r) => nowMs() - new Date(r.created_at).getTime() < 7 * 86400e3);
  const autoRuns = weekRuns.filter((r) => r.trigger === "auto").length;
  const dayRisk = day.data ? day.data.total - (day.data.by_type.Other ?? 0) : null;
  const highWeek = week.data ? (week.data.by_risk.High ?? 0) + (week.data.by_risk.Critical ?? 0) : null;

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(signals, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `tripwire-signals-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <>
      <PageHeader
        eyebrow={!ops.data ? "Monitoring" : ops.data.store.documents ? `Monitoring ${ops.data.store.documents.toLocaleString()} documents · ${ops.data.store.signals.toLocaleString()} signals` : `Demo snapshot · ${ops.data.store.signals.toLocaleString()} recorded signals`}
        title="Live signals"
        right={
          <button
            onClick={exportJson}
            disabled={!signals.length}
            className="inline-flex items-center gap-2 rounded-md border border-line px-4 py-2 text-sm text-bone transition-colors hover:border-gold hover:text-gold disabled:opacity-40"
          >
            Export JSON <Download className="h-4 w-4" />
          </button>
        }
      />

      <div className="grid divide-y divide-line overflow-hidden rounded-xl border border-line bg-ink-2 sm:grid-cols-2 xl:grid-cols-4 xl:divide-x xl:divide-y-0">
        <Kpi icon={<Layers className="h-4 w-4" />} value={day.data?.total ?? "—"} label="Signals, last 24 h" sub={dayRisk !== null ? `${dayRisk} classified as risk events` : undefined} />
        <Kpi icon={<Activity className="h-4 w-4" />} value={highWeek ?? "—"} label="High / critical, 7 days" sub={week.data ? `${(week.data.by_risk.Medium ?? 0)} medium` : undefined} tone="ember" />
        <Kpi icon={<BarChart3 className="h-4 w-4" />} value={runs.data ? weekRuns.length : "—"} label="Stress tests, 7 days" sub={runs.data ? `${autoRuns} auto · ${weekRuns.length - autoRuns} manual / what-if` : undefined} />
        <Kpi icon={<ShieldAlert className="h-4 w-4" />} value={watch.data?.counts.Red ?? "—"} label="Names on red watchlist" sub={watch.data ? `${money(watch.data.exposure_by_status.Red)} exposure` : undefined} tone="ember" />
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-2">
        <FilterChip on={!type} onClick={() => setType(null)}>All events</FilterChip>
        {EVENT_TYPES.map((t) => (
          <FilterChip key={t} on={type === t} onClick={() => setType(type === t ? null : t)} dot={TYPE_COLOR[t]}>
            {SHORT_TYPE[t] ?? t}
          </FilterChip>
        ))}
        <div className="ml-auto flex items-center gap-2">
          <select
            value={risk}
            onChange={(e) => setRisk(e.target.value as (typeof RISK_FILTERS)[number])}
            className="rounded-md border border-line bg-ink-2 px-3 py-1.5 text-sm text-bone focus:border-gold/50 focus:outline-none"
          >
            {RISK_FILTERS.map((r) => (
              <option key={r} value={r}>
                Risk: {r}
              </option>
            ))}
          </select>
          <label className="flex cursor-pointer items-center gap-2 rounded-md border border-line bg-ink-2 px-3 py-1.5 text-sm text-bone">
            <input type="checkbox" checked={confirmedOnly} onChange={(e) => setConfirmedOnly(e.target.checked)} className="accent-[#d9b46c]" />
            Confirmed only
          </label>
        </div>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[1fr_340px]">
        <div>
          <div className="mb-3 flex items-center justify-between text-sm">
            <span className="text-mute">
              {q ? (
                <>
                  Results for <span className="text-bone">“{q}”</span>{" "}
                  <button className="ml-2 text-gold hover:underline" onClick={() => setParams({})}>
                    clear
                  </button>
                </>
              ) : (
                "Newest first · risk events only"
              )}
            </span>
            <span className="font-mono text-xs text-gold">{signals.length} signals</span>
          </div>
          {feed.error && <ErrorNote error={feed.error} onRetry={feed.reload} />}
          {!feed.data && !feed.error && (
            <div className="space-y-3">
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-[132px]" />
              ))}
            </div>
          )}
          <motion.ul layout className="space-y-3">
            <AnimatePresence initial={false}>
              {signals.map((s, i) => (
                <motion.li
                  key={s.event_id}
                  layout
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.3, delay: Math.min(i, 8) * 0.03 }}
                >
                  <SignalCard s={s} stressed={runEvents.has(s.event_id)} />
                </motion.li>
              ))}
            </AnimatePresence>
          </motion.ul>
          {feed.data && !signals.length && <p className="py-10 text-center text-sm text-mute">No signals match these filters.</p>}
          {!q && feed.data && feed.data.length >= limit && limit < 1000 && (
            <button
              onClick={() => setLimit((l) => Math.min(1000, l + 120))}
              className="mt-4 w-full rounded-lg border border-line py-3 text-sm text-mute transition-colors hover:border-gold/50 hover:text-gold"
            >
              {feed.loading ? "Loading…" : "Load more"}
            </button>
          )}
        </div>

        <div className="space-y-6 xl:sticky xl:top-24 xl:self-start">
          <TypeChart stats={week.data} />
          <SourcesCard ops={ops.data} />
        </div>
      </div>
    </>
  );
}

function FilterChip({ on, onClick, children, dot }: { on: boolean; onClick: () => void; children: React.ReactNode; dot?: string }) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[13px] transition-colors ${
        on ? "border-gold bg-gold text-ink" : "border-line bg-ink-2 text-mute hover:border-gold/40 hover:text-bone"
      }`}
    >
      {dot && !on && <span className="h-1.5 w-1.5 rounded-full" style={{ background: dot }} />}
      {children}
    </button>
  );
}

function SignalCard({ s, stressed }: { s: Signal; stressed: boolean }) {
  const style = RISK_STYLE[s.risk_level] ?? RISK_STYLE.Low;
  const sent = s.sentiment_score;
  return (
    <Link
      to={`/app/signals/${s.event_id}`}
      className="group relative grid overflow-hidden rounded-xl border border-line bg-ink-2 transition-colors hover:border-gold/40 sm:grid-cols-[1fr_96px]"
    >
      <span className={`absolute inset-y-0 left-0 w-[3px] ${style.bar}`} />
      <div className="min-w-0 py-4 pr-4 pl-6">
        <div className="flex flex-wrap items-center gap-2 text-xs text-mute">
          <RiskChip level={s.risk_level} />
          <span>{timeAgo(s.first_seen_at)}</span>
          <span>·</span>
          <span>
            {s.corroboration.n_publishers} source{s.corroboration.n_publishers === 1 ? "" : "s"} ·{" "}
            {s.corroboration.sources.map((x) => SOURCE_LABEL[x] ?? x).join(", ")}
          </span>
          {s.alert_tier === "confirmed" && <Tag tone="sage">confirmed</Tag>}
          {stressed && <Tag tone="gold">stress test run</Tag>}
        </div>
        <h3 className="mt-2 line-clamp-2 text-[15px] leading-snug font-medium text-bone group-hover:text-gold">{s.headline}</h3>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
          <span className="text-bone/80">{s.company?.name ?? (s.primary_entity === "MACRO" ? "Economy / markets" : s.primary_entity)}</span>
          {s.company && <Tag>{s.company.ticker}</Tag>}
          <TypeChip type={s.event_type} />
        </div>
        <div className="mt-3 grid max-w-[560px] grid-cols-3 gap-4 border-t border-line pt-3 text-xs">
          <div>
            <div className="flex justify-between text-mute">
              Sentiment <span className={`font-mono ${sent > 0.05 ? "text-sage" : sent < -0.05 ? "text-ember-bright" : "text-bone"}`}>{signed(sent)}</span>
            </div>
            <div className="relative mt-1.5 h-1 rounded-full bg-line">
              <span className="absolute top-[-2px] left-1/2 h-[8px] w-px bg-mute/60" />
              <span
                className={`absolute top-0 h-1 rounded-full ${sent >= 0 ? "left-1/2 bg-sage" : "right-1/2 bg-ember-bright"}`}
                style={{ width: `${Math.abs(sent) * 50}%` }}
              />
            </div>
          </div>
          <div className="text-mute">
            Confidence <span className="ml-1 font-mono text-bone">{Math.round(s.confidence * 100)}%</span>
          </div>
          <div className="text-mute">
            P(large move) <span className="ml-1 font-mono text-bone">{Math.round(s.p_large_move * 100)}%</span>
          </div>
        </div>
      </div>
      <div className="hidden flex-col items-center justify-center gap-1 border-l border-line sm:flex">
        <ImpactRing value={s.impact_score} />
        <span className="text-[10px] uppercase tracking-wider text-mute">Impact</span>
        <ArrowRight className="mt-1 h-4 w-4 text-mute transition-transform group-hover:translate-x-1 group-hover:text-gold" />
      </div>
    </Link>
  );
}

function TypeChart({ stats }: { stats?: SignalStats }) {
  const days = stats?.by_day.slice(-7) ?? [];
  const types = Object.entries(stats?.by_type ?? {})
    .filter(([t]) => t !== "Other")
    .sort((a, b) => b[1] - a[1]);
  const top = types.slice(0, 5).map(([t]) => t);
  const max = Math.max(1, ...days.map((d) => Object.entries(d.by_type).filter(([t]) => t !== "Other").reduce((a, [, n]) => a + n, 0)));
  const total = types.reduce((a, [, n]) => a + n, 0);

  return (
    <Panel title="Risk events by type" sub="Last 7 days, excluding Other" right={<Tag>{total} total</Tag>}>
      {!stats ? (
        <Skeleton className="h-40" />
      ) : (
        <>
          <div className="flex h-40 items-end gap-2">
            {days.map((d, i) => {
              const parts = Object.entries(d.by_type).filter(([t]) => t !== "Other");
              const sum = parts.reduce((a, [, n]) => a + n, 0);
              return (
                <div key={d.date} className="flex h-full flex-1 flex-col items-center justify-end gap-1.5" title={`${d.date}: ${sum} risk events`}>
                  <motion.div
                    className="flex w-full flex-col-reverse overflow-hidden rounded-t"
                    initial={{ height: 0 }}
                    animate={{ height: `${(sum / max) * 100}%` }}
                    transition={{ duration: 0.7, delay: i * 0.05, ease: "easeOut" }}
                  >
                    {parts
                      .sort((a, b) => b[1] - a[1])
                      .map(([t, n]) => (
                        <div key={t} style={{ height: `${(n / sum) * 100}%`, background: TYPE_COLOR[t] ?? "#666" }} />
                      ))}
                  </motion.div>
                  <span className="text-[10px] text-mute">
                    {new Date(d.date + "T00:00:00Z").toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" })}
                  </span>
                </div>
              );
            })}
          </div>
          <ul className="mt-5 space-y-2 text-sm">
            {top.map((t) => (
              <li key={t} className="flex items-center justify-between">
                <span className="flex items-center gap-2 text-bone/80">
                  <span className="h-2 w-2 rounded-full" style={{ background: TYPE_COLOR[t] }} />
                  {SHORT_TYPE[t] ?? t}
                </span>
                <span className="font-mono text-bone">{stats.by_type[t]}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Panel>
  );
}

function SourcesCard({ ops }: { ops?: OpsStatus }) {
  const sources = Object.entries(ops?.collectors?.sources ?? {});
  return (
    <Panel title="Collectors" sub="Public sources, polled continuously" right={<Link to="/app/status" className="text-xs text-gold hover:underline">Details</Link>}>
      {!ops ? (
        <Skeleton className="h-28" />
      ) : (
        <ul className="space-y-2.5 text-sm">
          {sources.map(([name, s]) => {
            const ok = s.last_status === "ok" && !s.consecutive_failures;
            return (
              <li key={name} className="flex items-center justify-between">
                <span className="flex items-center gap-2 text-bone/85">
                  <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-sage" : "bg-ember-bright"}`} />
                  {SOURCE_LABEL[name] ?? name}
                </span>
                <span className="text-xs text-mute">{s.last_run ? timeAgo(s.last_run) : "never"}</span>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
