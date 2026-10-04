import { motion } from "framer-motion";
import { fmtMoney, fmtPct, useCase, type CaseData } from "../../lib/live";

/** Placeholder with the chart's footprint while the engine's API answers. */
function Pending({ h = 300 }: { h?: number }) {
  const { error } = useCase();
  return (
    <div className="flex items-center justify-center rounded-xl border border-line bg-ink-2 p-6 text-sm text-mute" style={{ height: h }}>
      {error ? "The live engine is not reachable right now." : "Loading live data…"}
    </div>
  );
}

const inView = { once: true, margin: "-60px" } as const;

/** Impact = sum of weighted factor contributions, then a calibrated 1-10 scale (live signal from the API). */
export function ContributionBars() {
  const { data: WAL } = useCase();
  if (!WAL) return <Pending h={340} />;
  const max = Math.max(...WAL.contributions.map((c) => c.value));
  const raw = WAL.contributions.reduce((a, c) => a + c.value, 0);
  return (
    <div className="rounded-xl border border-line bg-ink-2 p-6">
      <div className="flex items-baseline justify-between">
        <p className="eyebrow text-mute">Impact contributions · {WAL.ticker}</p>
        <p className="font-mono text-xs text-mute">raw {raw.toFixed(3)}</p>
      </div>
      <ul className="mt-5 space-y-3">
        {WAL.contributions.map((c, i) => (
          <li key={c.label} className="grid grid-cols-[132px_1fr_48px] items-center gap-3 text-xs">
            <span className="text-bone/80">{c.label}</span>
            <div className="h-2 overflow-hidden rounded-full bg-line">
              <motion.div
                className="h-full rounded-full bg-gold"
                initial={{ width: 0 }}
                whileInView={{ width: `${(c.value / max) * 100}%` }}
                viewport={inView}
                transition={{ duration: 0.9, delay: i * 0.08, ease: "easeOut" }}
              />
            </div>
            <span className="text-right font-mono text-mute">{c.value.toFixed(3)}</span>
          </li>
        ))}
      </ul>
      <div className="mt-6 flex items-end justify-between border-t border-line pt-4">
        <span className="text-xs text-mute">
          P(large price move) <span className="font-mono text-bone">{Math.round(WAL.pLargeMove * 100)}%</span>
        </span>
        <span className="text-3xl font-light text-gold">
          {WAL.impact.toFixed(2)}
          <span className="text-base text-mute"> / 10</span>
        </span>
      </div>
    </div>
  );
}

/** Stress P&L by asset class, losses left (ember), gains right (sage), then the CET1 move against the floors. */
export function PnlBars() {
  const { data: WAL } = useCase();
  if (!WAL) return <Pending h={360} />;
  const max = Math.max(...WAL.pnlByAsset.map((p) => Math.abs(p.value)));
  return (
    <div className="rounded-xl border border-line bg-ink-2 p-6">
      <div className="flex items-baseline justify-between">
        <p className="eyebrow text-mute">Stress P&amp;L by asset class</p>
        <p className="font-mono text-xs text-ember-bright">{fmtMoney(WAL.pnl)}</p>
      </div>
      <ul className="mt-5 space-y-3">
        {WAL.pnlByAsset.map((p, i) => {
          const w = `${(Math.abs(p.value) / max) * 50}%`;
          const neg = p.value < 0;
          return (
            <li key={p.label} className="grid grid-cols-[120px_1fr_64px] items-center gap-3 text-xs">
              <span className="text-bone/80">{p.label}</span>
              <div className="relative h-2">
                <div className="absolute inset-y-[-4px] left-1/2 w-px bg-line" />
                <motion.div
                  className={`absolute top-0 h-full rounded-full ${neg ? "right-1/2 bg-ember-bright" : "left-1/2 bg-sage"}`}
                  initial={{ width: 0 }}
                  whileInView={{ width: w }}
                  viewport={inView}
                  transition={{ duration: 0.9, delay: i * 0.08, ease: "easeOut" }}
                />
              </div>
              <span className={`text-right font-mono ${neg ? "text-ember-bright" : "text-sage"}`}>{fmtMoney(p.value)}</span>
            </li>
          );
        })}
      </ul>
      <CapitalScale WAL={WAL} />
    </div>
  );
}

function CapitalScale({ WAL }: { WAL: CaseData }) {
  const lo = 0.06;
  const hi = 0.13;
  const pos = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  return (
    <div className="mt-6 border-t border-line pt-5">
      <div className="flex justify-between text-xs">
        <span className="text-mute">CET1 ratio</span>
        <span className="font-mono text-bone">
          {fmtPct(WAL.cet1Before)} → {fmtPct(WAL.cet1After)}{" "}
          <span className="text-ember-bright">(−{Math.round((WAL.cet1Before - WAL.cet1After) * 10000)} bp)</span>
        </span>
      </div>
      <div className="relative mt-6 h-1.5 rounded-full bg-line">
        {[
          [WAL.floors.basel, `Basel ${Math.round(WAL.floors.basel * 100)}%`],
          [WAL.floors.rbi, `RBI ${Math.round(WAL.floors.rbi * 100)}%`],
        ].map(([v, l]) => (
          <div key={l} className="absolute -top-4 flex -translate-x-1/2 flex-col items-center" style={{ left: pos(v as number) }}>
            <span className="text-[10px] text-mute">{l}</span>
            <span className="mt-0.5 h-4 w-px bg-mute/60" />
          </div>
        ))}
        <motion.div
          className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-ink bg-gold"
          initial={{ left: pos(WAL.cet1Before) }}
          whileInView={{ left: pos(WAL.cet1After) }}
          viewport={inView}
          transition={{ duration: 1.4, delay: 0.6, ease: "easeInOut" }}
        />
        <div className="absolute top-1/2 h-3 w-px -translate-y-1/2 bg-bone/40" style={{ left: pos(WAL.cet1Before) }} />
      </div>
    </div>
  );
}

/** The three layers that decide an event class, strongest evidence first. */
export function DecisionLayers() {
  const layers = [
    ["8-K item map", "The filer declares the item (e.g. 1.03 bankruptcy).", "0.95"],
    ["Context rules", "High-precision phrases that need context, e.g. an actual deposit run.", "0.90"],
    ["ML head + verifier", "e5-large classifier, checked by a DeBERTa zero-shot verifier.", "p ≥ 0.30"],
  ];
  return (
    <div className="space-y-3">
      {layers.map(([t, d, c], i) => (
        <motion.div
          key={t}
          className="flex items-center gap-5 rounded-xl border border-line bg-ink-2 p-5"
          initial={{ opacity: 0, x: 24 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={inView}
          transition={{ duration: 0.6, delay: i * 0.15 }}
          style={{ marginLeft: `${i * 6}%` }}
        >
          <span className="font-mono text-xs text-gold">L{i + 1}</span>
          <div className="flex-1">
            <p className="text-sm text-bone">{t}</p>
            <p className="mt-0.5 text-xs text-mute">{d}</p>
          </div>
          <span className="rounded-full border border-gold/40 px-2.5 py-1 font-mono text-[11px] text-gold">{c}</span>
        </motion.div>
      ))}
    </div>
  );
}
