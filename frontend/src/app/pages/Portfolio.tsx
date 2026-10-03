import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { Loader2, Play } from "lucide-react";
import { api, useApi, type Portfolio as PortfolioT, type StressRun, type StressRunSummary } from "../api";
import { ASSET_LABEL, STRESS_TYPES, money, pct, signedMoney, timeAgo } from "../format";
import { Bar, ErrorNote, Loading, PageHeader, Panel, Tag, TypeChip } from "../ui";

const DONUT_COLORS = ["#d9b46c", "#7fa287", "#d0663f", "#8f9bd0", "#b083c4", "#6fb3b8"];

export default function Portfolio() {
  const pf = useApi<PortfolioT>("/portfolio");
  const runs = useApi<StressRunSummary[]>("/stress-runs?limit=12", 60_000);

  useEffect(() => {
    if (window.location.hash === "#what-if" && pf.data) {
      document.getElementById("what-if")?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [pf.data]);

  if (pf.error) return <ErrorNote error={pf.error} onRetry={pf.reload} />;
  if (!pf.data) return <Loading label="Loading the book" />;
  const p = pf.data;
  const total = p.totals.tranche1_ead + p.totals.tranche2_exposure;

  return (
    <>
      <PageHeader
        eyebrow={`Book as of ${p.as_of}`}
        title="Portfolio & stress"
        right={
          <a href="#what-if" className="rounded-md bg-gold px-4 py-2 text-sm font-medium text-ink transition-colors hover:bg-bone">
            New what-if
          </a>
        }
      />

      <div className="grid gap-4 md:grid-cols-3">
        <Stat label="Total exposure" value={money(total)} sub={<>SME {money(p.totals.tranche1_ead, 0)} <Tag>synthetic</Tag> · Corporate {money(p.totals.tranche2_exposure, 0)}</>} />
        <Stat label="Risk-weighted assets" value={money(p.capital.rwa)} sub={`${pct(p.capital.rwa / total, 1)} risk density · ${p.n_positions.tranche1 + p.n_positions.tranche2} positions`} />
        <Stat
          label="CET1 capital"
          value={<>{money(p.capital.cet1)} <span className="ml-2 text-lg text-sage">{pct(p.capital.cet1_ratio, 1)}</span></>}
          sub={`Basel floor ${pct(p.capital.floors.basel, 0)} · RBI floor ${pct(p.capital.floors.rbi, 0)}`}
        />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_1.4fr]">
        <Panel title="Exposure by asset class" sub="On-balance-sheet exposure / EAD">
          <Donut data={p.exposure_by_type} total={total} />
        </Panel>
        <Panel title="Exposure by sector" sub="All positions, $M">
          <ul className="space-y-3">
            {Object.entries(p.exposure_by_sector)
              .filter(([k]) => k !== "n/a")
              .sort((a, b) => b[1] - a[1])
              .map(([k, v], i, arr) => (
                <li key={k} className="grid grid-cols-[170px_1fr_48px] items-center gap-3 text-xs">
                  <span className="truncate text-bone/80">{k}</span>
                  <Bar value={v} max={arr[0][1]} delay={i * 0.04} />
                  <span className="text-right font-mono text-mute">{(v / 1e6).toFixed(0)}</span>
                </li>
              ))}
          </ul>
        </Panel>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Panel title="SME exposure by state" sub={`United States · ${money(p.totals.tranche1_ead, 0)} across ${p.n_positions.tranche1} SME loans`}>
          <StateMap data={p.tranche1_exposure_by_state} />
        </Panel>
        <Panel title="Exposure by rating grade" sub="Internal grade (SMEs) and assumed ratings (corporates)">
          <ul className="space-y-3">
            {["AA", "A", "BBB", "BB", "B", "CCC"].filter((g) => p.exposure_by_grade[g]).map((g, i) => (
              <li key={g} className="grid grid-cols-[48px_1fr_64px] items-center gap-3 text-xs">
                <span className="font-mono text-bone">{g}</span>
                <Bar value={p.exposure_by_grade[g]} max={Math.max(...Object.values(p.exposure_by_grade))} color={i > 3 ? "var(--color-ember-bright)" : "var(--color-gold)"} delay={i * 0.05} />
                <span className="text-right font-mono text-mute">{money(p.exposure_by_grade[g], 0)}</span>
              </li>
            ))}
          </ul>
          <p className="mt-5 text-[11px] leading-relaxed text-mute">{p.pd_basis}</p>
        </Panel>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_1.4fr]" id="what-if">
        <WhatIf sectors={Object.keys(p.exposure_by_sector).filter((s) => s !== "n/a")} onDone={runs.reload} />
        <Panel title="Stress run history" sub="Automatic triggers, manual runs and what-ifs">
          {runs.error && <ErrorNote error={runs.error} />}
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-mute">
                <tr>
                  <th className="pb-2 font-normal">When</th>
                  <th className="pb-2 font-normal">Scenario</th>
                  <th className="pb-2 font-normal">Trigger</th>
                  <th className="pb-2 text-right font-normal">P&amp;L</th>
                  <th className="pb-2 text-right font-normal">CET1 after</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {(runs.data ?? []).map((r) => (
                  <tr key={r.run_id} className="align-top">
                    <td className="py-2.5 pr-3 whitespace-nowrap text-xs text-mute">{timeAgo(r.created_at)}</td>
                    <td className="py-2.5 pr-3">
                      {r.event_id ? (
                        <Link to={`/app/signals/${r.event_id}`} className="line-clamp-2 text-bone hover:text-gold">
                          {r.scenario_name}
                        </Link>
                      ) : (
                        <span className="line-clamp-2 text-bone">{r.scenario_name}</span>
                      )}
                    </td>
                    <td className="py-2.5 pr-3">
                      <Tag tone={r.trigger === "auto" ? "gold" : "mute"}>{r.trigger}</Tag>
                    </td>
                    <td className={`py-2.5 text-right font-mono whitespace-nowrap ${r.pnl_total < 0 ? "text-ember-bright" : "text-bone"}`}>{signedMoney(r.pnl_total)}</td>
                    <td className="py-2.5 text-right font-mono text-bone">{pct(r.cet1_ratio_after)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </>
  );
}

function Stat({ label, value, sub }: { label: string; value: React.ReactNode; sub: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-ink-2 p-5">
      <div className="text-sm text-mute">{label}</div>
      <div className="mt-2 text-[32px] font-light text-bone">{value}</div>
      <div className="mt-1 text-xs text-mute">{sub}</div>
    </div>
  );
}

function Donut({ data, total }: { data: Record<string, number>; total: number }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const r = 60;
  const c = 2 * Math.PI * r;
  let acc = 0;
  return (
    <div className="flex flex-col items-center gap-6 sm:flex-row">
      <div className="relative h-44 w-44 shrink-0">
        <svg viewBox="0 0 160 160" className="h-full w-full -rotate-90">
          <circle cx="80" cy="80" r={r} fill="none" stroke="var(--color-line)" strokeWidth="18" />
          {entries.map(([k, v], i) => {
            const len = (v / total) * c;
            const off = acc;
            acc += len;
            return (
              <motion.circle
                key={k}
                cx="80"
                cy="80"
                r={r}
                fill="none"
                stroke={DONUT_COLORS[i % DONUT_COLORS.length]}
                strokeWidth="18"
                strokeDasharray={`${len} ${c - len}`}
                initial={{ strokeDashoffset: -off + len }}
                animate={{ strokeDashoffset: -off }}
                transition={{ duration: 0.8, delay: i * 0.1 }}
              />
            );
          })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-xl text-bone">{money(total, 0)}</span>
          <span className="text-[11px] text-mute">total</span>
        </div>
      </div>
      <ul className="w-full space-y-2 text-sm">
        {entries.map(([k, v], i) => (
          <li key={k} className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-2 text-bone/80">
              <span className="h-2 w-2 rounded-full" style={{ background: DONUT_COLORS[i % DONUT_COLORS.length] }} />
              {ASSET_LABEL[k] ?? k}
            </span>
            <span className="font-mono text-xs text-mute">{pct(v / total, 1)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Tile-grid map of the US: one equal square per state, so small states stay readable.
const TILES: Record<string, [number, number]> = {
  AK: [0, 0], ME: [10, 0], VT: [9, 1], NH: [10, 1],
  WA: [0, 2], ID: [1, 2], MT: [2, 2], ND: [3, 2], MN: [4, 2], IL: [5, 2], WI: [6, 2], MI: [7, 2], NY: [8, 2], RI: [9, 2], MA: [10, 2],
  OR: [0, 3], NV: [1, 3], WY: [2, 3], SD: [3, 3], IA: [4, 3], IN: [5, 3], OH: [6, 3], PA: [7, 3], NJ: [8, 3], CT: [9, 3],
  CA: [0, 4], UT: [1, 4], CO: [2, 4], NE: [3, 4], MO: [4, 4], KY: [5, 4], WV: [6, 4], VA: [7, 4], MD: [8, 4], DE: [9, 4],
  AZ: [1, 5], NM: [2, 5], KS: [3, 5], AR: [4, 5], TN: [5, 5], NC: [6, 5], SC: [7, 5], DC: [8, 5],
  OK: [3, 6], LA: [4, 6], MS: [5, 6], AL: [6, 6], GA: [7, 6],
  HI: [0, 7], TX: [3, 7], FL: [8, 7],
};

function StateMap({ data }: { data: Record<string, number> }) {
  const [hover, setHover] = useState<string>();
  const max = Math.max(...Object.entries(data).filter(([k]) => k in TILES).map(([, v]) => v));
  const other = Object.entries(data).filter(([k]) => !(k in TILES));
  const top = Object.entries(data).filter(([k]) => k in TILES).sort((a, b) => b[1] - a[1]).slice(0, 3);
  return (
    <div>
      <div className="relative grid grid-cols-11 gap-1">
        {Object.entries(TILES).map(([st, [x, y]]) => {
          const v = data[st] ?? 0;
          // log scale: CA is ~100x the median state
          const t = v ? Math.log10(1 + v) / Math.log10(1 + max) : 0;
          return (
            <motion.div
              key={st}
              onMouseEnter={() => setHover(st)}
              onMouseLeave={() => setHover(undefined)}
              className="flex aspect-square items-center justify-center rounded text-[10px] font-medium"
              style={{
                gridColumn: x + 1,
                gridRow: y + 1,
                background: v ? `rgba(217,180,108,${0.12 + t * 0.78})` : "var(--color-ink-3)",
                color: t > 0.6 ? "var(--color-ink)" : "var(--color-mute)",
              }}
              initial={{ opacity: 0, scale: 0.6 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ delay: (x + y) * 0.03 }}
            >
              {st}
            </motion.div>
          );
        })}
      </div>
      <div className="mt-4 flex min-h-[20px] flex-wrap items-center gap-x-5 gap-y-1 text-xs text-mute">
        {hover ? (
          <span>
            <span className="text-bone">{hover}</span> · {money(data[hover] ?? 0)}
          </span>
        ) : (
          top.map(([k, v]) => (
            <span key={k}>
              <span className="text-bone">{k}</span> {money(v, 0)}
            </span>
          ))
        )}
        {other.length > 0 && <span className="ml-auto">Not mapped: {other.map(([k, v]) => `${k} ${money(v, 0)}`).join(" · ")}</span>}
      </div>
    </div>
  );
}

function WhatIf({ sectors, onDone }: { sectors: string[]; onDone: () => void }) {
  const [eventType, setEventType] = useState(STRESS_TYPES[0]);
  const [impact, setImpact] = useState(7.5);
  const [entity, setEntity] = useState("");
  const [sector, setSector] = useState("");
  const [states, setStates] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();
  const [result, setResult] = useState<StressRun>();

  const stateList = useMemo(() => states.split(/[\s,]+/).map((s) => s.trim().toUpperCase()).filter(Boolean), [states]);

  const run = async () => {
    setBusy(true);
    setErr(undefined);
    try {
      const body = { event_type: eventType, impact, entity: entity.trim() || null, sector: sector || null, states: stateList };
      setResult(await api<StressRun>("/stress-test", { method: "POST", body: JSON.stringify(body) }));
      onDone();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const field = "w-full rounded-md border border-line bg-ink-3 px-3 py-2 text-sm text-bone focus:border-gold/50 focus:outline-none";
  return (
    <Panel title="Run a what-if" sub="A hypothetical event through the same engine" right={<Tag tone="gold">assumption</Tag>}>
      <div className="space-y-4">
        <label className="block text-xs text-mute">
          Event type
          <select className={`${field} mt-1`} value={eventType} onChange={(e) => setEventType(e.target.value)}>
            {STRESS_TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-xs text-mute">
            Company ticker (optional)
            <input className={`${field} mt-1 uppercase`} value={entity} onChange={(e) => setEntity(e.target.value)} placeholder="e.g. JPM" />
          </label>
          <label className="block text-xs text-mute">
            Sector (optional)
            <select className={`${field} mt-1`} value={sector} onChange={(e) => setSector(e.target.value)}>
              <option value="">Any</option>
              {sectors.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
        </div>
        <label className="block text-xs text-mute">
          US states (optional, for disasters)
          <input className={`${field} mt-1`} value={states} onChange={(e) => setStates(e.target.value)} placeholder="e.g. CA, TX" />
        </label>
        <label className="block text-xs text-mute">
          <span className="flex justify-between">
            Severity <span className="font-mono text-gold">Impact {impact.toFixed(1)}</span>
          </span>
          <input type="range" min={1} max={10} step={0.1} value={impact} onChange={(e) => setImpact(Number(e.target.value))} className="mt-2 w-full accent-[#d9b46c]" />
        </label>
        <button
          onClick={run}
          disabled={busy}
          className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-ember px-4 py-2.5 text-sm text-cream transition-colors hover:bg-ember-bright disabled:opacity-60"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
          {busy ? "Running…" : "Run what-if"}
        </button>
        {err && <p className="font-mono text-xs text-ember-bright">{err}</p>}
        <AnimatePresence>
          {result && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              className="overflow-hidden rounded-lg border border-line bg-ink-3 p-4 text-sm"
            >
              <div className="flex items-center justify-between">
                <TypeChip type={result.scenario.event_type} />
                <span className="font-mono text-[11px] text-mute">{result.run_id}</span>
              </div>
              <div className="mt-3 grid grid-cols-3 gap-3">
                <Mini label="P&L" value={signedMoney(result.pnl_total)} tone={result.pnl_total < 0 ? "ember" : undefined} />
                <Mini label="CET1 after" value={pct(result.capital.cet1_ratio_after)} />
                <Mini label="Positions hit" value={String(result.n_positions_affected)} />
              </div>
              {result.top_contributors[0] && (
                <p className="mt-3 text-xs text-mute">
                  Largest hit: <span className="text-bone">{result.top_contributors[0].name}</span> {signedMoney(result.top_contributors[0].dv)}
                </p>
              )}
              {result.reverse_stress?.rbi && <p className="mt-1 text-xs text-mute">{result.reverse_stress.rbi.note}</p>}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </Panel>
  );
}

function Mini({ label, value, tone }: { label: string; value: string; tone?: "ember" }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-mute">{label}</div>
      <div className={`mt-0.5 font-mono ${tone === "ember" ? "text-ember-bright" : "text-bone"}`}>{value}</div>
    </div>
  );
}
