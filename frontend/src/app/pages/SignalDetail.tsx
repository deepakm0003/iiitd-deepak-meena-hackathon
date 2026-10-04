import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, Check, ExternalLink, Loader2, Play, X } from "lucide-react";
import { api, useApi, type Signal, type StressRun, type StressRunSummary, type Trace } from "../api";
import {
  ASSET_LABEL,
  FACTOR_LABEL,
  SOURCE_LABEL,
  dateTime,
  money,
  pct,
  signed,
  signedMoney,
  timeAgo,
} from "../format";
import { Bar, ErrorNote, ImpactRing, Loading, ProvTag, RiskChip, Tag, TypeChip } from "../ui";

const CHECK_LABEL: Record<string, string> = {
  stress_mappable: "Class has a shock definition",
  factual: "A fact, not talk",
  adverse: "Adverse",
  severe_enough: "Impact clears the exposure bar",
};

export default function SignalDetail() {
  const { id = "" } = useParams();
  const trace = useApi<Trace>(`/signals/${id}/trace`);
  const signal = useApi<Signal>(`/signals/${id}`);
  const runs = useApi<StressRunSummary[]>(`/stress-runs?event_id=${id}&limit=1`);
  const [run, setRun] = useState<StressRun>();
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string>();

  // load the latest stress run for this event, if one exists
  useEffect(() => {
    const latest = runs.data?.[0];
    if (!latest) return;
    api<StressRun>(`/stress-test/${latest.run_id}`).then(setRun).catch((e: Error) => setRunError(e.message));
  }, [runs.data]);

  const runNow = async () => {
    setRunning(true);
    setRunError(undefined);
    try {
      setRun(await api<StressRun>("/stress-test", { method: "POST", body: JSON.stringify({ event_id: id }) }));
    } catch (e) {
      setRunError((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  if (trace.error) return <ErrorNote error={trace.error} onRetry={trace.reload} />;
  if (!trace.data) return <Loading label="Loading the reasoning trace" />;

  return (
    <>
      <Link to="/app" className="inline-flex items-center gap-1.5 text-sm text-mute hover:text-gold">
        <ArrowLeft className="h-4 w-4" /> Back to live signals
      </Link>

      <TraceView trace={trace.data} signal={signal.data} run={run} onRun={runNow} running={running}
                 runError={runError} runsLoading={runs.loading} />
    </>
  );
}

/** The full reasoning trace for one signal: used for stored signals and for uploaded documents (Analyse). */
export function TraceView({ trace, signal, run, onRun, running = false, runError, runsLoading = false, aside }: {
  trace: Trace;
  signal?: Signal;
  run?: StressRun;
  onRun?: () => void;
  running?: boolean;
  runError?: string;
  runsLoading?: boolean;
  aside?: ReactNode;
}) {
  const w = trace.what_happened;
  const h = trace.how_important;
  const d = trace.why_it_matters_to_this_book;
  const s = signal;

  return (
    <>
      <header className="mt-5 grid gap-6 rounded-xl border border-line bg-ink-2 p-6 lg:grid-cols-[1fr_auto]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-xs text-mute">
            <RiskChip level={h.risk_level} />
            <span>{dateTime(w.first_seen_at)}</span>
            <TypeChip type={w.event_type} />
            {s?.alert_tier === "confirmed" && <Tag tone="sage">confirmed tier</Tag>}
          </div>
          <h1 className="mt-3 font-serif text-3xl leading-tight text-bone sm:text-[38px]">{w.headline}</h1>
          <p className="mt-3 flex flex-wrap items-center gap-2 text-sm text-bone/80">
            {w.company ? (
              <>
                {w.company.name} <Tag>{w.company.ticker}</Tag>
                {w.company.sector && <span className="text-mute">{w.company.sector}</span>}
              </>
            ) : (
              <span>{w.entity === "MACRO" ? "Economy / markets" : w.entity}</span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-6 border-t border-line pt-5 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-6">
          <div className="flex items-center gap-3">
            <ImpactRing value={h.impact_score} size={72} />
            <div className="text-xs text-mute">
              Impact score
              <div className="text-bone">{Math.round(h.percentile)}th percentile</div>
            </div>
          </div>
          <Metric label="P(large move)" value={pct(h.p_large_move, 0)} />
          <Metric label="Confidence" value={pct(h.confidence, 0)} />
        </div>
      </header>

      <div className="mt-8 grid gap-8 xl:grid-cols-[1fr_320px]">
        <div>
          <h2 className="mb-5 flex items-center gap-3 text-xl font-light text-bone">
            Why this signal matters <Tag>Full reasoning trace</Tag>
          </h2>
          <ol className="relative space-y-4">
            <div className="absolute top-4 bottom-4 left-[15px] w-px bg-line" aria-hidden />

            <Step n={1} tag="Source">
              <ul className="space-y-2">
                {w.documents.slice(0, 4).map((doc, i) => (
                  <li key={i} className="flex items-start justify-between gap-4 text-sm">
                    <span className="min-w-0">
                      <span className="text-bone">{SOURCE_LABEL[doc.source] ?? doc.source}</span>
                      <span className="ml-2 text-mute">{timeAgo(doc.published_at)}</span>
                      <span className="block truncate text-xs text-mute">{doc.title}</span>
                    </span>
                    {doc.url && (
                      <a href={doc.url} target="_blank" rel="noreferrer" className="inline-flex shrink-0 items-center gap-1 text-xs text-gold hover:underline">
                        Open source <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </li>
                ))}
              </ul>
              {w.evidence[0] && (
                <blockquote className="mt-3 border-l-2 border-gold/60 pl-3 text-sm leading-relaxed text-mute">“{w.evidence[0].text}”</blockquote>
              )}
            </Step>

            <Step n={2} tag="Entity">
              {w.company ? (
                <div className="flex items-center gap-3">
                  <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-ink-3 font-mono text-xs text-gold">
                    {w.company.ticker.slice(0, 3)}
                  </span>
                  <div>
                    <div className="text-bone">{w.company.name}</div>
                    <div className="text-xs text-mute">
                      {w.company.ticker}
                      {w.company.cik ? ` · CIK ${w.company.cik}` : ""}
                      {w.company.sector ? ` · ${w.company.sector}` : ""}
                    </div>
                  </div>
                </div>
              ) : (
                <p className="text-sm text-bone">Market-wide: no single company. Sectors: {s?.affected_sectors?.join(", ") || "n/a"}</p>
              )}
            </Step>

            <Step n={3} tag="Event" chip={<Tag tone="gold">{w.event_method}</Tag>}>
              <p className="text-sm text-mute">Classified as</p>
              <p className="text-lg text-bone">
                {w.event_type}
                {w.event_subtype && <span className="text-mute"> / {w.event_subtype.replace(/_/g, " ")}</span>}
              </p>
              {w.event_evidence?.context && (
                <p className="mt-2 text-sm leading-relaxed text-mute">
                  Matched evidence: <Highlight text={w.event_evidence.context} phrase={w.event_evidence.phrase} />
                </p>
              )}
              <p className="mt-2 text-xs text-mute">Factuality: <span className="text-bone">{w.factuality}</span></p>
            </Step>

            <Step n={4} tag="Sentiment">
              <div className="flex items-baseline gap-3">
                <span className={`font-mono text-2xl ${w.sentiment_score > 0.05 ? "text-sage" : w.sentiment_score < -0.05 ? "text-ember-bright" : "text-bone"}`}>
                  {signed(w.sentiment_score)}
                </span>
                <span className="text-sm text-mute">{w.direction ?? s?.sentiment_label}</span>
              </div>
              {w.event_subtype && w.sentiment_score > 0.3 && d?.checks.adverse?.ok && (
                <p className="mt-2 text-sm text-mute">
                  The text reads positive, but the event is adverse by nature ({w.event_subtype.replace(/_/g, " ")}): nature beats tone.
                </p>
              )}
            </Step>

            <Step n={5} tag="Impact" chip={<Tag>formula + measured calibration</Tag>}>
              <p className="text-sm text-mute">{h.explanation}</p>
              <ul className="mt-4 space-y-2.5">
                {Object.entries(h.contributions)
                  .sort((a, b) => b[1] - a[1])
                  .map(([k, v], i) => (
                    <li key={k} className="grid grid-cols-[150px_1fr_52px_auto] items-center gap-3 text-xs">
                      <span className="text-bone/80">{FACTOR_LABEL[k] ?? k}</span>
                      <Bar value={v} max={Math.max(...Object.values(h.contributions))} delay={i * 0.05} />
                      <span className="text-right font-mono text-mute">{v.toFixed(3)}</span>
                      {h.provenance?.factors?.[k] ? <ProvTag source={h.provenance.factors[k]} /> : <span />}
                    </li>
                  ))}
              </ul>
            </Step>

            {d && (
              <Step n={6} tag="Exposure">
                <div className="grid gap-3 sm:grid-cols-3">
                  <Exposure label="Direct (this name)" share={d.exposure.direct} book={d.exposure.book_exposure} />
                  <Exposure label="Sector peers" share={d.exposure.sector} book={d.exposure.book_exposure} />
                  <Exposure label="Geography (SMEs)" share={d.exposure.geography} book={d.exposure.book_exposure} />
                </div>
              </Step>
            )}

            {d && (
              <Step n={7} tag="Stress decision" chip={<Tag tone={d.trigger ? "ember" : "mute"}>{d.trigger ? "stress test triggered" : "no stress test"}</Tag>}>
                <ul className="space-y-2">
                  {Object.entries(d.checks).map(([k, c]) => (
                    <li key={k} className="flex items-start gap-3 text-sm">
                      <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${c.ok ? "bg-sage/20 text-sage" : "bg-ember/20 text-ember-bright"}`}>
                        {c.ok ? <Check className="h-3 w-3" strokeWidth={3} /> : <X className="h-3 w-3" strokeWidth={3} />}
                      </span>
                      <span>
                        <span className="text-bone">{CHECK_LABEL[k] ?? k}</span>
                        <span className="block font-mono text-[11px] text-mute">{c.detail}</span>
                      </span>
                    </li>
                  ))}
                </ul>
              </Step>
            )}

            {run ? (
              <RunSteps run={run} />
            ) : (
              trace.stress_available && onRun && (
                <Step n={8} tag="Stress test">
                  <p className="text-sm text-mute">
                    {d?.trigger
                      ? "This signal qualifies for a stress test. Run it to see shocks, losses and capital."
                      : "This signal did not trigger an automatic stress test. You can still run one manually."}
                  </p>
                  <button
                    onClick={onRun}
                    disabled={running || runsLoading}
                    className="mt-4 inline-flex items-center gap-2 rounded-md bg-ember px-4 py-2 text-sm text-cream transition-colors hover:bg-ember-bright disabled:opacity-60"
                  >
                    {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                    {running ? "Running…" : "Run stress test"}
                  </button>
                  {runError && <p className="mt-2 font-mono text-xs text-ember-bright">{runError}</p>}
                </Step>
              )
            )}
          </ol>
        </div>

        <aside className="space-y-4 xl:sticky xl:top-24 xl:self-start">
          {aside}
          <div className="rounded-xl border border-line bg-ink-2 p-5">
            <h3 className="text-[15px] font-medium text-bone">Signal summary</h3>
            <dl className="mt-4 space-y-3 text-sm">
              <Row k="Event ID" v={<span className="font-mono text-xs">{trace.event_id}</span>} />
              <Row k="First seen" v={timeAgo(w.first_seen_at)} />
              <Row k="Sources" v={`${w.corroboration.n_articles} article${w.corroboration.n_articles === 1 ? "" : "s"} · ${w.corroboration.n_publishers} publisher${w.corroboration.n_publishers === 1 ? "" : "s"}`} />
              <Row k="Alert tier" v={s?.alert_tier ?? "…"} />
              {d && <Row k="Book exposure" v={money(d.exposure.book_exposure)} />}
              {run && <Row k="Stress run" v={<span className="font-mono text-xs">{run.run_id}</span>} />}
            </dl>
          </div>
          <div className="rounded-xl border border-line bg-ink-2 p-5 text-xs leading-relaxed text-mute">
            <p className="text-sm text-bone">Provenance</p>
            <p className="mt-2">
              <Tag tone="sage">measured</Tag> comes from market data or a historical analog. <Tag tone="gold">assumption</Tag> points to the
              assumptions register. Hover a tag for its full source.
            </p>
          </div>
        </aside>
      </div>
    </>
  );
}

function RunSteps({ run }: { run: StressRun }) {
  const [scenario, setScenario] = useState<"mild" | "base" | "severe">("base");
  const sens = run.sensitivity?.[scenario];
  const cet1After = sens?.cet1_ratio_after ?? run.capital.cet1_ratio_after;
  const pnl = sens?.pnl_total ?? run.pnl_total;
  const unaffected = Object.entries(run.unaffected_by_reason ?? {});
  const assets = Object.entries(run.pnl_by_asset_class).filter(([, v]) => v !== 0);
  const maxAsset = Math.max(1, ...assets.map(([, v]) => Math.abs(v)));

  return (
    <>
      <Step n={8} tag="Shocks" chip={<Tag>severity k = {run.scenario.k.toFixed(2)}</Tag>}>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-mute">
              <tr>
                <th className="pb-2 font-normal">Layer</th>
                <th className="pb-2 font-normal">Risk factor</th>
                <th className="pb-2 font-normal">Shock</th>
                <th className="pb-2 font-normal">Provenance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {Object.entries(run.scenario.layers).flatMap(([layer, shocks]) =>
                Object.entries(shocks).map(([factor, sh]) => (
                  <tr key={layer + factor}>
                    <td className="py-2 text-mute capitalize">{layer}</td>
                    <td className="py-2 text-bone">{factor.replace(/_/g, " ")}</td>
                    <td className="py-2 font-mono text-bone">{fmtShock(factor, sh.value)}</td>
                    <td className="py-2">
                      <ProvTag source={sh.source} />
                    </td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
      </Step>

      <Step n={9} tag="Loss" chip={<Tag tone="ember">{run.n_positions_affected} positions hit</Tag>}>
        <div className="flex items-baseline gap-3">
          <span className="text-sm text-mute">Estimated total P&amp;L</span>
          <span className={`font-mono text-2xl ${run.pnl_total < 0 ? "text-ember-bright" : "text-sage"}`}>{signedMoney(run.pnl_total)}</span>
        </div>
        <ul className="mt-4 space-y-2.5">
          {assets.map(([k, v], i) => (
            <li key={k} className="grid grid-cols-[130px_1fr_80px] items-center gap-3 text-xs">
              <span className="text-bone/80">{ASSET_LABEL[k] ?? k}</span>
              <Bar value={Math.abs(v)} max={maxAsset} color={v < 0 ? "var(--color-ember-bright)" : "var(--color-sage)"} delay={i * 0.05} />
              <span className={`text-right font-mono ${v < 0 ? "text-ember-bright" : "text-sage"}`}>{signedMoney(v)}</span>
            </li>
          ))}
        </ul>
        <p className="mt-5 text-xs text-mute">Largest contributors</p>
        <ul className="mt-2 divide-y divide-line">
          {run.top_contributors.slice(0, 5).map((c) => (
            <li key={c.id} className="py-2 text-sm">
              <div className="flex justify-between gap-3">
                <span className="text-bone">
                  {c.name} <span className="text-xs text-mute">{c.type.replace(/_/g, " ")}</span>
                </span>
                <span className={`font-mono ${c.dv < 0 ? "text-ember-bright" : "text-sage"}`}>{signedMoney(c.dv)}</span>
              </div>
              {c.paths[0] && <p className="mt-0.5 text-xs text-mute">{c.paths.map((p) => p.reason).join(" · ")}</p>}
            </li>
          ))}
        </ul>
        {unaffected.length > 0 && (
          <details className="mt-3 text-xs text-mute">
            <summary className="cursor-pointer text-gold">Why weren't the other {unaffected.reduce((a, [, n]) => a + n, 0)} positions hit?</summary>
            <ul className="mt-2 space-y-1.5">
              {unaffected.map(([reason, n]) => (
                <li key={reason}>
                  <span className="font-mono text-bone">{n}</span> · {reason}
                </li>
              ))}
            </ul>
          </details>
        )}
      </Step>

      <Step n={10} tag="Capital">
        {run.sensitivity && (
          <div className="mb-4 inline-flex rounded-md border border-line p-0.5 text-xs">
            {(["mild", "base", "severe"] as const).map((k) => (
              <button
                key={k}
                onClick={() => setScenario(k)}
                className={`rounded px-3 py-1 capitalize transition-colors ${scenario === k ? "bg-gold text-ink" : "text-mute hover:text-bone"}`}
              >
                {k}
              </button>
            ))}
          </div>
        )}
        <div className="grid gap-4 sm:grid-cols-3">
          <Metric label="CET1 before" value={pct(run.capital.cet1_ratio_before)} />
          <Metric label="CET1 after stress" value={pct(cet1After)} tone="gold" />
          <Metric label={`P&L (${scenario})`} value={signedMoney(pnl)} tone={pnl < 0 ? "ember" : undefined} />
        </div>
        <CapitalScale before={run.capital.cet1_ratio_before} after={cet1After} floors={run.capital.floors} />
        <div className="mt-4 grid gap-2 text-xs text-mute sm:grid-cols-2">
          <span>
            RWA <span className="font-mono text-bone">{money(run.capital.rwa_before)} → {money(run.capital.rwa_after)}</span>
          </span>
          <span>
            ECL change <span className="font-mono text-bone">{signedMoney(sens?.ecl_change ?? run.ecl_change)}</span>
          </span>
        </div>
        {run.reverse_stress && (
          <ul className="mt-4 space-y-1 rounded-lg bg-ink-3 px-4 py-3 text-xs text-mute">
            {Object.entries(run.reverse_stress).map(([k, r]) => (
              <li key={k}>
                <span className="text-bone uppercase">{k}</span> · {r.note}
              </li>
            ))}
          </ul>
        )}
        {run.sensitivity?.note && <p className="mt-2 text-[11px] text-mute/80">{run.sensitivity.note}</p>}
      </Step>
    </>
  );
}

function CapitalScale({ before, after, floors }: { before: number; after: number; floors: { basel: number; rbi: number } }) {
  const lo = 0.06;
  const hi = Math.max(0.13, before + 0.01);
  const pos = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  return (
    <div className="relative mt-8 h-1.5 rounded-full bg-line">
      {[
        [floors.basel, "Basel"],
        [floors.rbi, "RBI"],
      ].map(([v, l]) => (
        <div key={l} className="absolute -top-5 flex -translate-x-1/2 flex-col items-center" style={{ left: pos(v as number) }}>
          <span className="text-[10px] text-mute">
            {l} {pct(v as number, 0)}
          </span>
          <span className="mt-0.5 h-4 w-px bg-mute/60" />
        </div>
      ))}
      <div className="absolute top-1/2 h-3 w-px -translate-y-1/2 bg-bone/40" style={{ left: pos(before) }} />
      <motion.div
        className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-ink bg-gold"
        initial={{ left: pos(before) }}
        animate={{ left: pos(after) }}
        transition={{ duration: 1.1, ease: "easeInOut" }}
      />
    </div>
  );
}

function fmtShock(factor: string, v: number) {
  if (factor.endsWith("_bp")) return `${v > 0 ? "+" : ""}${v.toFixed(0)} bp`;
  if (factor === "pd_mult") return `×${v.toFixed(2)}`;
  if (factor === "vol_pts") return `${v > 0 ? "+" : ""}${v.toFixed(1)} pts`;
  return `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
}

function Step({ n, tag, chip, children }: { n: number; tag: string; chip?: ReactNode; children: ReactNode }) {
  return (
    <motion.li
      className="relative grid grid-cols-[32px_1fr] gap-4"
      initial={{ opacity: 0, x: 12 }}
      whileInView={{ opacity: 1, x: 0 }}
      viewport={{ once: true, margin: "-40px" }}
      transition={{ duration: 0.45 }}
    >
      <span className="relative z-10 flex h-8 w-8 items-center justify-center rounded-full border border-gold/60 bg-[#0e0e0e] font-mono text-xs text-gold">
        {n}
      </span>
      <div className="rounded-xl border border-line bg-ink-2 p-5">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className="eyebrow text-mute">{tag}</span>
          {chip}
        </div>
        {children}
      </div>
    </motion.li>
  );
}

function Highlight({ text, phrase }: { text: string; phrase: string }) {
  const i = phrase ? text.toLowerCase().indexOf(phrase.toLowerCase()) : -1;
  if (i < 0) return <span className="text-bone">“{text}”</span>;
  return (
    <span>
      “{text.slice(0, i)}
      <mark className="rounded-sm bg-gold/25 px-0.5 text-bone">{text.slice(i, i + phrase.length)}</mark>
      {text.slice(i + phrase.length)}”
    </span>
  );
}

function Exposure({ label, share, book }: { label: string; share: number; book: number }) {
  return (
    <div className="rounded-lg bg-ink-3 p-3">
      <div className="text-xs text-mute">{label}</div>
      <div className="mt-1 font-mono text-lg text-bone">{money(share * book)}</div>
      <div className="text-[11px] text-mute">{pct(share)} of the book</div>
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "gold" | "ember" }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-mute">{label}</div>
      <div className={`mt-1 font-mono text-lg ${tone === "gold" ? "text-gold" : tone === "ember" ? "text-ember-bright" : "text-bone"}`}>{value}</div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-mute">{k}</dt>
      <dd className="text-right text-bone">{v}</dd>
    </div>
  );
}
