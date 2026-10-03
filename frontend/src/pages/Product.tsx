import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowRight,
  Bell,
  Building2,
  Check,
  Gauge,
  Landmark,
  LineChart,
  MessageSquareQuote,
  Radar,
  RotateCcw,
  ShieldAlert,
  SlidersHorizontal,
  Tag,
  type LucideIcon,
} from "lucide-react";
import { ClosingCta, PageHero } from "../components/site/PageHero";
import { Reveal } from "../components/site/Reveal";
import { PnlBars } from "../components/site/Charts";
import { WAL } from "../lib/caseStudy";

const MODULE_A: [LucideIcon, string, string][] = [
  [Tag, "Event classification", "11 classes. 8-K items, context rules, then a classifier checked by a verifier."],
  [MessageSquareQuote, "Sentiment and factuality", "FinBERT fine-tuned per company (macro-F1 0.89 vs 0.66 plain FinBERT), plus whether it is confirmed, rumour or opinion."],
  [Building2, "Entity resolution", "Names resolved to tickers and CIKs with GLiNER and the SEC company list."],
  [Gauge, "Impact score", "1–10 from seven named factors, with a calibrated probability of a large move."],
];

const MODULE_B: [LucideIcon, string, string][] = [
  [ShieldAlert, "Stress trigger", "Every check shown, pass or fail, including why a signal did not launch a test."],
  [Landmark, "Capital impact", "P&L, ECL stage moves, RWA and CET1, reconciled line by line."],
  [Bell, "Early-warning watchlist", "Green, Amber, Red per name from the three strongest recent signals."],
  [SlidersHorizontal, "What-if scenarios", "Pick an event type, Impact and target and run the same engine."],
  [RotateCcw, "Reverse stress", "How large a shock would push CET1 to the regulatory floor."],
  [LineChart, "Mild, base, severe", "Every run shows a range, not a single point estimate."],
];

const SCREENS = [
  ["Live signals", "Ranked feed with filters by class, Impact and company.", "/app"],
  ["Reasoning trace", "Source to capital for one signal, every step sourced.", `/app/signals/${WAL.eventId}`],
  ["Portfolio", "Exposure by type, sector, grade and state.", "/app/portfolio"],
  ["Stress tests", "Automatic, manual and what-if runs.", "/app/stress"],
];

export default function Product() {
  return (
    <>
      <PageHero
        eyebrow="Product"
        lines={["One engine.", "Signal to capital."]}
        lede="Module A turns public information into structured, scored risk signals. Module B turns those signals into stress tests on a bank's book."
      />

      <ModuleRow
        no="Module A"
        title="Risk engine"
        body="Reads SEC filings, news, central-bank releases and social posts every few minutes and produces one signal per real event, with the evidence attached."
        items={MODULE_A}
        visual={<SignalCard />}
      />
      <ModuleRow
        no="Module B"
        title="Stress testing"
        body="Decides which signals deserve a stress test, applies sourced shocks to a synthetic wholesale book and shows exactly what moves capital."
        items={MODULE_B}
        visual={
          <div className="space-y-4">
            <TriggerChecks />
            <PnlBars />
          </div>
        }
        flip
      />

      <section className="bg-cream text-ink">
        <div className="container-x py-24 md:py-28">
          <Reveal>
            <p className="eyebrow text-ink/60">The dashboard</p>
            <h2 className="mt-5 text-4xl font-light leading-[1.08] tracking-tight sm:text-[52px]">Four views, one API.</h2>
          </Reveal>
          <div className="mt-14 grid gap-px overflow-hidden rounded-xl border border-ink/10 bg-ink/10 sm:grid-cols-2 lg:grid-cols-4">
            {SCREENS.map(([t, d, to], i) => (
              <Reveal key={t} delay={i * 0.08} className="bg-cream">
                <Link to={to} className="group flex h-full min-h-[200px] flex-col p-7 transition-colors hover:bg-paper">
                  <span className="font-mono text-xs text-ember">{String(i + 1).padStart(2, "0")}</span>
                  <h3 className="mt-auto text-xl font-medium">{t}</h3>
                  <p className="mt-2 text-sm text-ink/60">{d}</p>
                  <span className="mt-4 inline-flex items-center gap-1 text-sm text-ember">
                    Open <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
                  </span>
                </Link>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <ClosingCta lines={["See it on a", "real filing."]}>
        <Link
          to="/app"
          className="group inline-flex items-center gap-2 rounded-md bg-gold px-5 py-3 text-sm font-medium text-ink transition-colors hover:bg-bone"
        >
          View live demo <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
        </Link>
        <Link
          to="/how-it-works"
          className="inline-flex items-center gap-2 rounded-md border border-line px-5 py-3 text-sm text-bone transition-colors hover:border-gold hover:text-gold"
        >
          How it works
        </Link>
      </ClosingCta>
    </>
  );
}

function ModuleRow({
  no,
  title,
  body,
  items,
  visual,
  flip,
}: {
  no: string;
  title: string;
  body: string;
  items: [LucideIcon, string, string][];
  visual: React.ReactNode;
  flip?: boolean;
}) {
  return (
    <section className="container-x grid gap-14 py-20 md:py-28 lg:grid-cols-2 lg:items-start">
      <div className={flip ? "lg:order-2" : ""}>
        <Reveal>
          <p className="eyebrow text-mute">{no}</p>
          <h2 className="mt-5 text-4xl font-light leading-[1.1] tracking-tight text-gold sm:text-[56px]">{title}</h2>
          <p className="mt-6 max-w-md leading-relaxed text-mute">{body}</p>
        </Reveal>
        <div className="mt-10 grid gap-x-8 gap-y-7 sm:grid-cols-2">
          {items.map(([Icon, t, d], i) => (
            <Reveal key={t} delay={0.1 + i * 0.06}>
              <Icon className="h-5 w-5 text-gold" strokeWidth={1.5} />
              <h3 className="mt-3 text-[15px] text-bone">{t}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-mute">{d}</p>
            </Reveal>
          ))}
        </div>
      </div>
      <Reveal delay={0.15} className={`lg:sticky lg:top-24 ${flip ? "lg:order-1" : ""}`}>
        {visual}
      </Reveal>
    </section>
  );
}

/** The WAL signal as the risk engine emitted it. */
function SignalCard() {
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-ink-2">
      <div className="flex items-center justify-between border-b border-line px-6 py-4">
        <span className="flex items-center gap-2 font-mono text-xs text-mute">
          <Radar className="h-4 w-4 text-gold" /> {WAL.eventId}
        </span>
        <span className="rounded-full border border-gold/40 px-2.5 py-0.5 text-[11px] text-gold">standard tier · {WAL.method}</span>
      </div>
      <div className="p-6">
        <p className="text-xs text-mute">
          {WAL.filing} · {WAL.date}
        </p>
        <h3 className="mt-2 text-lg leading-snug text-bone">Western Alliance Bancorporation files 8-K: Regulation FD Disclosure</h3>
        <div className="mt-4 flex flex-wrap gap-2 text-[11px]">
          {[WAL.eventType, WAL.subtype, WAL.factuality, "sentiment +0.86"].map((c) => (
            <span key={c} className="rounded-full bg-ink-3 px-2.5 py-1 text-bone/80">
              {c}
            </span>
          ))}
        </div>
        <blockquote className="mt-5 border-l-2 border-gold pl-4 text-sm leading-relaxed text-mute">
          “…cash reserves exceed $25 billion and are growing, while{" "}
          <motion.mark
            className="rounded-sm bg-transparent px-0.5 text-bone"
            initial={{ backgroundColor: "rgba(217,180,108,0)" }}
            whileInView={{ backgroundColor: "rgba(217,180,108,0.28)" }}
            viewport={{ once: true }}
            transition={{ duration: 1, delay: 0.6 }}
          >
            {WAL.evidence}
          </motion.mark>
          .”
        </blockquote>
        <p className="mt-2 font-mono text-[11px] text-mute">evidence · {WAL.method}</p>
      </div>
      <div className="grid grid-cols-3 border-t border-line text-center">
        {[
          ["Impact", WAL.impact.toFixed(2)],
          ["Percentile", `${Math.round(WAL.percentile)}th`],
          ["P(large move)", `${Math.round(WAL.pLargeMove * 100)}%`],
        ].map(([l, v], i) => (
          <div key={l} className={`py-4 ${i ? "border-l border-line" : ""}`}>
            <div className="text-[10px] uppercase tracking-wider text-mute">{l}</div>
            <div className="mt-1 font-mono text-bone">{v}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Module B's trigger checks for WAL. Note check 3: the bank's own reassuring tone (+0.86) does not hide a run. */
function TriggerChecks() {
  const checks = [
    ["Class has a shock definition", "Credit Event"],
    ["A fact, not talk", "factuality: confirmed"],
    ["Adverse by nature", "liquidity_stress, despite sentiment +0.86"],
    ["Impact clears the exposure bar", "7.48 ≥ 6.0 (direct exposure 0.88% of the book)"],
  ];
  return (
    <div className="rounded-xl border border-line bg-ink-2 p-6">
      <p className="eyebrow text-mute">Stress trigger · WAL</p>
      <ul className="mt-4 space-y-3">
        {checks.map(([t, d], i) => (
          <motion.li
            key={t}
            className="flex items-start gap-3"
            initial={{ opacity: 0, x: -10 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            transition={{ delay: 0.2 + i * 0.25 }}
          >
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-sage/20 text-sage">
              <Check className="h-3 w-3" strokeWidth={3} />
            </span>
            <span className="text-sm">
              <span className="text-bone">{t}</span>
              <span className="block font-mono text-[11px] text-mute">{d}</span>
            </span>
          </motion.li>
        ))}
      </ul>
      <motion.p
        className="mt-5 rounded-md bg-ember/15 px-4 py-2.5 text-sm text-ember-bright"
        initial={{ opacity: 0 }}
        whileInView={{ opacity: 1 }}
        viewport={{ once: true }}
        transition={{ delay: 1.3 }}
      >
        Stress test launched · {WAL.positions} positions repriced
      </motion.p>
    </div>
  );
}
