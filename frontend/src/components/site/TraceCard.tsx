import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Building2, Check, FileText, Gauge, Landmark, Tag } from "lucide-react";
import { WAL, fmtMoney, fmtPct } from "../../lib/caseStudy";

// Horizontal pipeline: the stage nodes run left to right and the detail panel underneath has a fixed height,
// so nothing on the page moves while the animation plays.
const STAGES = [
  { icon: FileText, label: "Source", title: "Source detected", main: WAL.filing, sub: `${WAL.date} · 14:58 UTC · sec.gov` },
  { icon: Tag, label: "Event", title: "Event classified", main: `${WAL.eventType} · ${WAL.subtype}`, sub: `${WAL.method} · ${WAL.factuality}` },
  { icon: Building2, label: "Entity", title: "Entity resolved", main: `${WAL.ticker} · Western Alliance`, sub: "Financials · CIK 1212545" },
  { icon: Gauge, label: "Impact", title: "Impact scored", main: `${WAL.impact.toFixed(1)} / 10`, sub: `${Math.round(WAL.percentile)}th percentile of all signals` },
  { icon: Landmark, label: "Stress", title: "Stress tested", main: `${WAL.positions} positions repriced`, sub: "P&L → ECL → RWA → CET1" },
];

const STEP_MS = 3200;
const HOLD_MS = 6500;

export function TraceCard() {
  const reduce = useReducedMotion();
  const [step, setStep] = useState(reduce ? STAGES.length : 0);

  useEffect(() => {
    if (reduce) return;
    const t = setTimeout(
      () => setStep((s) => (s >= STAGES.length ? 0 : s + 1)),
      step >= STAGES.length ? HOLD_MS : step === 0 ? 1500 : STEP_MS,
    );
    return () => clearTimeout(t);
  }, [step, reduce]);

  const done = step >= STAGES.length;
  const shown = Math.min(step, STAGES.length - 1); // the stage whose detail is on screen
  const stage = STAGES[shown];
  const progress = Math.min(step, STAGES.length - 1) / (STAGES.length - 1);

  return (
    <div className="relative w-full max-w-[520px] overflow-hidden rounded-2xl border border-line bg-ink-2/95 shadow-[0_40px_120px_-40px_rgba(0,0,0,0.9)] backdrop-blur">
      {/* vertical scan line sweeping left to right */}
      {!reduce && (
        <motion.div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 w-24 bg-gradient-to-r from-transparent via-gold/[0.07] to-transparent"
          animate={{ left: ["-20%", "110%"] }}
          transition={{ duration: 6.5, repeat: Infinity, ease: "linear" }}
        />
      )}

      <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-ember-bright opacity-70" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-ember-bright" />
          </span>
          <span className="eyebrow text-bone">Risk trace · replay</span>
        </div>
        <span className="font-mono text-[11px] text-mute">{WAL.eventId}</span>
      </div>

      {/* stepper */}
      <div className="relative px-6 pt-6">
        <div className="absolute top-[40px] right-[48px] left-[48px] h-px bg-line" aria-hidden />
        <motion.div
          aria-hidden
          className="absolute top-[40px] left-[48px] h-px origin-left bg-gold"
          style={{ width: "calc(100% - 96px)" }}
          animate={{ scaleX: progress }}
          transition={{ duration: 1.4, ease: "easeInOut" }}
        />
        {/* data packet travelling along the line to the active node */}
        {!reduce && !done && (
          <motion.span
            aria-hidden
            className="absolute top-[37px] h-[7px] w-[7px] rounded-full bg-gold shadow-[0_0_12px_2px_rgba(217,180,108,0.6)]"
            animate={{ left: `calc(48px + (100% - 96px) * ${progress} - 3px)` }}
            transition={{ duration: 1.4, ease: "easeInOut" }}
          />
        )}
        <ol className="relative flex justify-between">
          {STAGES.map((s, i) => {
            const state = i < step ? "done" : i === step ? "active" : "pending";
            const Icon = s.icon;
            return (
              <li key={s.label} className="flex w-12 flex-col items-center gap-2">
                <div
                  className={`relative flex h-8 w-8 items-center justify-center rounded-full border transition-colors duration-500 ${
                    state === "done"
                      ? "border-gold bg-gold text-ink"
                      : state === "active"
                        ? "border-gold bg-ink-2 text-gold"
                        : "border-line bg-ink-2 text-mute/60"
                  }`}
                >
                  {state === "done" ? <Check className="h-4 w-4" strokeWidth={2.5} /> : <Icon className="h-3.5 w-3.5" />}
                  {state === "active" && (
                    <motion.span
                      className="absolute inset-0 rounded-full border border-gold"
                      animate={{ scale: [1, 1.7], opacity: [0.8, 0] }}
                      transition={{ duration: 1.8, repeat: Infinity }}
                    />
                  )}
                </div>
                <span
                  className={`font-mono text-[10px] uppercase tracking-wider transition-colors ${
                    state === "pending" ? "text-mute/50" : state === "active" ? "text-gold" : "text-bone/80"
                  }`}
                >
                  {s.label}
                </span>
              </li>
            );
          })}
        </ol>
      </div>

      {/* detail panel: fixed height, content slides in horizontally */}
      <div className="relative mx-5 mt-5 mb-5 h-[132px] overflow-hidden rounded-xl border border-line bg-ink/60">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={done ? "done" : shown}
            className="absolute inset-0 p-4"
            initial={{ x: 40, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: -40, opacity: 0 }}
            transition={{ duration: 0.6, ease: "easeOut" }}
          >
            {done ? (
              <div className="flex h-full flex-col justify-between">
                <div className="flex items-center justify-between">
                  <span className="text-[13px] text-bone">Trace complete</span>
                  <span className="font-mono text-[10px] uppercase tracking-wider text-sage">5 / 5 ok</span>
                </div>
                <p className="text-[12px] leading-relaxed text-mute">
                  One 8-K sentence, <span className="text-bone">“{WAL.evidence}”</span>, reached the capital line with
                  every step sourced.
                </p>
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-[13px] text-bone">{stage.title}</span>
                  <span className="font-mono text-[10px] uppercase tracking-wider text-mute">
                    {String(shown + 1).padStart(2, "0")} / 05 · {step > shown ? "ok" : "running"}
                  </span>
                </div>
                <div className="mt-1.5 truncate text-[15px] font-medium text-gold">{stage.main}</div>
                <div className="truncate text-[11px] text-mute">{stage.sub}</div>
                {shown === 3 && <FactorBars />}
                {shown === 4 && <AssetStrip />}
              </>
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      <div className="grid grid-cols-3 border-t border-line">
        <ImpactRing show={step > 3} />
        <Metric label="Stress P&L" value={fmtMoney(WAL.pnl)} show={done} tone="ember" />
        <Metric label="CET1 ratio" value={`${fmtPct(WAL.cet1Before)} → ${fmtPct(WAL.cet1After)}`} show={done} />
      </div>
    </div>
  );
}

function FactorBars() {
  return (
    <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5">
      {WAL.factors.map((f, i) => (
        <div key={f.key}>
          <div className="flex justify-between text-[10px] text-mute">
            <span>{f.label}</span>
            <span className="font-mono">{f.value.toFixed(2)}</span>
          </div>
          <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-line">
            <motion.div
              className="h-full rounded-full bg-gold"
              initial={{ width: 0 }}
              animate={{ width: `${f.value * 100}%` }}
              transition={{ duration: 1.3, delay: 0.25 + 0.15 * i, ease: "easeOut" }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

/** Stress P&L by asset class as one horizontal strip: losses fill from the left, hedges show as gains. */
function AssetStrip() {
  const max = Math.max(...WAL.pnlByAsset.map((p) => Math.abs(p.value)));
  return (
    <div className="mt-3 grid grid-cols-5 gap-2">
      {WAL.pnlByAsset.map((p, i) => (
        <div key={p.label}>
          <div className="h-1 overflow-hidden rounded-full bg-line">
            <motion.div
              className={`h-full rounded-full ${p.value < 0 ? "bg-ember-bright" : "bg-sage"}`}
              initial={{ width: 0 }}
              animate={{ width: `${Math.max(6, (Math.abs(p.value) / max) * 100)}%` }}
              transition={{ duration: 1.2, delay: 0.25 + 0.12 * i }}
            />
          </div>
          <div className="mt-1 truncate text-[9px] text-mute">{p.label.replace(" (hedge)", "")}</div>
        </div>
      ))}
    </div>
  );
}

function ImpactRing({ show }: { show: boolean }) {
  const r = 17;
  const c = 2 * Math.PI * r;
  return (
    <div className="flex items-center gap-2.5 px-4 py-3.5">
      <svg viewBox="0 0 44 44" className="h-11 w-11 -rotate-90">
        <circle cx="22" cy="22" r={r} fill="none" stroke="var(--color-line)" strokeWidth="4" />
        <motion.circle
          cx="22"
          cy="22"
          r={r}
          fill="none"
          stroke="var(--color-gold)"
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={c}
          animate={{ strokeDashoffset: show ? c * (1 - WAL.impact / 10) : c }}
          transition={{ duration: 1.6, ease: "easeOut" }}
        />
      </svg>
      <div>
        <div className="text-[10px] uppercase tracking-wider text-mute">Impact</div>
        <div className="font-mono text-sm text-bone">{show ? WAL.impact.toFixed(1) : "—"}</div>
      </div>
    </div>
  );
}

function Metric({ label, value, show, tone }: { label: string; value: string; show: boolean; tone?: "ember" }) {
  return (
    <div className="border-l border-line px-4 py-3.5">
      <div className="text-[10px] uppercase tracking-wider text-mute">{label}</div>
      <motion.div
        className={`mt-1 whitespace-nowrap font-mono text-[13px] ${tone === "ember" ? "text-ember-bright" : "text-bone"}`}
        animate={{ opacity: show ? 1 : 0.25 }}
      >
        {show ? value : "—"}
      </motion.div>
    </div>
  );
}
