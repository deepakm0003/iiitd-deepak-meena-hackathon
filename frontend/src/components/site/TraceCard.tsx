import { useEffect, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Check, FileText, Tag, Building2, Gauge, Landmark } from "lucide-react";
import { WAL, fmtMoney, fmtPct } from "../../lib/caseStudy";

const STAGES = [
  { icon: FileText, title: "Source detected", main: WAL.filing, sub: `${WAL.date} · 14:58 UTC` },
  { icon: Tag, title: "Event classified", main: `${WAL.eventType} · ${WAL.subtype}`, sub: `${WAL.method} · ${WAL.factuality}` },
  { icon: Building2, title: "Entity resolved", main: `${WAL.ticker} · Western Alliance`, sub: "Financials · CIK 1212545" },
  { icon: Gauge, title: "Impact scored", main: `${WAL.impact.toFixed(1)} / 10`, sub: `${Math.round(WAL.percentile)}th percentile of all signals` },
  { icon: Landmark, title: "Stress tested", main: `${WAL.positions} positions repriced`, sub: "P&L → ECL → RWA → CET1" },
];

const STEP_MS = 1300;
const HOLD_MS = 5200;

export function TraceCard() {
  const reduce = useReducedMotion();
  const [step, setStep] = useState(reduce ? STAGES.length : 0);

  useEffect(() => {
    if (reduce) return;
    const t = setTimeout(
      () => setStep((s) => (s >= STAGES.length ? 0 : s + 1)),
      step >= STAGES.length ? HOLD_MS : step === 0 ? 700 : STEP_MS,
    );
    return () => clearTimeout(t);
  }, [step, reduce]);

  const done = step >= STAGES.length;

  return (
    <div className="relative w-full max-w-[460px] overflow-hidden rounded-2xl border border-line bg-ink-2/95 shadow-[0_40px_120px_-40px_rgba(0,0,0,0.9)] backdrop-blur">
      {/* scanning line */}
      {!reduce && (
        <motion.div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 h-24 bg-gradient-to-b from-transparent via-gold/[0.07] to-transparent"
          animate={{ top: ["-20%", "110%"] }}
          transition={{ duration: 3.6, repeat: Infinity, ease: "linear" }}
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

      <ol className="relative px-5 pt-4 pb-2">
        {/* connector */}
        <div className="absolute top-7 bottom-9 left-[37px] w-px bg-line" aria-hidden />
        <motion.div
          aria-hidden
          className="absolute top-7 left-[37px] w-px origin-top bg-gold"
          style={{ bottom: 36 }}
          animate={{ scaleY: Math.min(step, STAGES.length - 1) / (STAGES.length - 1) }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
        {STAGES.map((s, i) => {
          const state = i < step ? "done" : i === step ? "active" : "pending";
          const Icon = s.icon;
          return (
            <li key={s.title} className="relative flex gap-4 py-2.5">
              <div
                className={`relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border transition-colors duration-500 ${
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
                    animate={{ scale: [1, 1.6], opacity: [0.8, 0] }}
                    transition={{ duration: 1.1, repeat: Infinity }}
                  />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-3">
                  <span className={`text-[13px] transition-colors ${state === "pending" ? "text-mute/60" : "text-bone"}`}>
                    {s.title}
                  </span>
                  <span className="font-mono text-[10px] uppercase tracking-wider text-mute">
                    {state === "done" ? "ok" : state === "active" ? "running" : ""}
                  </span>
                </div>
                <AnimatePresence initial={false}>
                  {state !== "pending" && (
                    <motion.div
                      initial={{ opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                      transition={{ duration: 0.35 }}
                    >
                      <div className="truncate text-[13px] font-medium text-gold">{s.main}</div>
                      <div className="truncate text-[11px] text-mute">{s.sub}</div>
                      {i === 3 && <FactorBars />}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </li>
          );
        })}
      </ol>

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
    <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5">
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
              transition={{ duration: 0.8, delay: 0.15 * i, ease: "easeOut" }}
            />
          </div>
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
          transition={{ duration: 1, ease: "easeOut" }}
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
        className={`mt-1 font-mono text-[13px] ${tone === "ember" ? "text-ember-bright" : "text-bone"}`}
        animate={{ opacity: show ? 1 : 0.25 }}
      >
        {show ? value : "—"}
      </motion.div>
    </div>
  );
}
