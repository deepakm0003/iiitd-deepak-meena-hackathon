import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowRight, BarChart3, Building2, FileText, Gauge, Landmark, Layers, ShieldCheck, Zap, type LucideIcon } from "lucide-react";
import { ClosingCta, PageHero } from "../components/site/PageHero";
import { Reveal } from "../components/site/Reveal";
import { ContributionBars, DecisionLayers, PnlBars } from "../components/site/Charts";
import { WAL, fmtMoney, fmtPct } from "../lib/caseStudy";

const STEPS: { icon: LucideIcon; title: string; body: string; wal: string }[] = [
  { icon: FileText, title: "Source", body: "Ingest filings, news and market data.", wal: `${WAL.filing}, filed ${WAL.date} 14:58 UTC` },
  { icon: Building2, title: "Entity", body: "Resolve the company, borrower or issuer.", wal: "WAL · Western Alliance Bancorporation · CIK 1212545" },
  { icon: Zap, title: "Event", body: "Classify the event and extract evidence.", wal: `${WAL.eventType} / ${WAL.subtype}: “${WAL.evidence}”` },
  { icon: Gauge, title: "Impact", body: "Estimate likely market and credit severity.", wal: `Impact ${WAL.impact.toFixed(2)}, ${Math.round(WAL.percentile)}th percentile` },
  { icon: Layers, title: "Exposure", body: "Map direct, sector and factor exposures.", wal: `${WAL.positions} positions in the book linked` },
  { icon: BarChart3, title: "Stress", body: "Apply transparent, sourced shocks.", wal: "Spread, equity and rating shocks, severity k = 0.50" },
  { icon: Landmark, title: "Capital", body: "Calculate P&L, ECL, RWA and CET1.", wal: `${fmtMoney(WAL.pnl)} · CET1 ${fmtPct(WAL.cet1Before)} → ${fmtPct(WAL.cet1After)}` },
];

export default function HowItWorks() {
  const reduce = useReducedMotion();
  const [active, setActive] = useState(0);
  const [paused, setPaused] = useState(false);

  // walk through the stages on a loop, like a trace being replayed; hovering a card takes over
  useEffect(() => {
    if (reduce || paused) return;
    const t = setInterval(() => setActive((a) => (a + 1) % STEPS.length), 3600);
    return () => clearInterval(t);
  }, [reduce, paused]);

  return (
    <>
      <PageHero
        eyebrow="How it works"
        lines={["From evidence", "to capital."]}
        lede="A complete, auditable reasoning path from a public source to the position and capital impact on the balance sheet."
      />

      <section className="container-x py-20 md:py-24">
        <Reveal className="mb-8 flex items-center justify-between">
          <p className="eyebrow text-mute">Seven stages · replaying Western Alliance, {WAL.date}</p>
          <span className="hidden font-mono text-xs text-gold sm:block">
            {String(active + 1).padStart(2, "0")} / {String(STEPS.length).padStart(2, "0")}
          </span>
        </Reveal>
        <div
          className="grid border-t border-l border-line sm:grid-cols-2 lg:grid-cols-4"
          onMouseLeave={() => setPaused(false)}
        >
          {STEPS.map((s, i) => {
            const Icon = s.icon;
            const on = i === active;
            return (
              <Reveal key={s.title} delay={i * 0.06} className="border-r border-b border-line">
                <div
                  className={`relative flex h-full min-h-[230px] flex-col p-7 transition-colors duration-500 ${on ? "bg-ink-3" : "bg-ink-2/40"}`}
                  onMouseEnter={() => {
                    setPaused(true);
                    setActive(i);
                  }}
                >
                  {on && (
                    <motion.span
                      layoutId="step-bar"
                      className="absolute inset-x-0 top-0 h-0.5 bg-gold"
                      transition={{ type: "spring", stiffness: 300, damping: 30 }}
                    />
                  )}
                  <span className={`font-mono text-xs ${on ? "text-gold" : "text-mute"}`}>{String(i + 1).padStart(2, "0")}</span>
                  <h3 className="mt-10 flex items-center gap-2.5 text-2xl font-light text-bone">
                    <Icon className={`h-5 w-5 ${on ? "text-gold" : "text-mute"}`} strokeWidth={1.5} />
                    {s.title}
                  </h3>
                  <p className="mt-3 text-sm text-mute">{s.body}</p>
                  <AnimatePresence>
                    {on && (
                      <motion.p
                        className="mt-auto pt-5 font-mono text-[11px] leading-relaxed text-gold/90"
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0 }}
                      >
                        {s.wal}
                      </motion.p>
                    )}
                  </AnimatePresence>
                </div>
              </Reveal>
            );
          })}
          <Reveal delay={0.45} className="hidden border-r border-b border-line lg:block">
            <Link
              to={`/app/signals/${WAL.eventId}`}
              className="group flex h-full min-h-[230px] flex-col justify-end bg-ember p-7 text-cream transition-colors hover:bg-ember-bright"
            >
              <ShieldCheck className="mb-auto h-6 w-6" strokeWidth={1.5} />
              <span className="text-xl font-light">Open the full trace</span>
              <span className="mt-2 inline-flex items-center gap-1.5 text-sm text-cream/80">
                {WAL.eventId} <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
              </span>
            </Link>
          </Reveal>
        </div>
      </section>

      <section className="container-x grid gap-14 py-20 md:grid-cols-2 md:items-center md:py-28">
        <Reveal>
          <p className="eyebrow text-mute">Event · three layers</p>
          <h2 className="mt-5 text-4xl font-light leading-[1.1] tracking-tight text-gold sm:text-5xl">
            Strongest evidence decides first.
          </h2>
          <p className="mt-6 max-w-md leading-relaxed text-mute">
            When a filer declares an 8-K item, that is the answer. Precise rules come next. Only what both miss goes to the
            model, and the model's answer has to survive an independent verifier. Every alert records which layer decided
            it; 8-K items and the most precise rules are marked as the confirmed tier.
          </p>
        </Reveal>
        <DecisionLayers />
      </section>

      <section className="container-x grid gap-14 py-20 md:grid-cols-2 md:items-center md:py-28">
        <Reveal className="md:order-2">
          <p className="eyebrow text-mute">Impact · seven factors</p>
          <h2 className="mt-5 text-4xl font-light leading-[1.1] tracking-tight text-gold sm:text-5xl">
            A score you can take apart.
          </h2>
          <p className="mt-6 max-w-md leading-relaxed text-mute">
            Severity, sentiment magnitude, entity importance, novelty, corroboration, source credibility and the
            historical market reaction to similar events. Each contribution is shown, along with a calibrated probability
            of a large price move.
          </p>
        </Reveal>
        <Reveal delay={0.1} className="md:order-1">
          <ContributionBars />
        </Reveal>
      </section>

      <section className="container-x grid gap-14 py-20 md:grid-cols-2 md:items-center md:py-28">
        <Reveal>
          <p className="eyebrow text-mute">Capital · reconciled</p>
          <h2 className="mt-5 text-4xl font-light leading-[1.1] tracking-tight text-gold sm:text-5xl">
            Down to the CET1 ratio.
          </h2>
          <p className="mt-6 max-w-md leading-relaxed text-mute">
            Shocks reprice every linked position. Losses reduce CET1 net of 25% tax, rating migration moves RWA, and the
            result is checked against the 7% Basel and 8% RBI floors. Hedges show up as gains, not hidden netting.
          </p>
        </Reveal>
        <Reveal delay={0.1}>
          <PnlBars />
        </Reveal>
      </section>

      <ClosingCta lines={["No black box.", "Every step stays visible."]}>
        <Link
          to={`/app/signals/${WAL.eventId}`}
          className="group inline-flex items-center gap-2 rounded-md bg-ember px-5 py-3 text-sm text-cream transition-colors hover:bg-ember-bright"
        >
          View the reasoning trace <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
        </Link>
      </ClosingCta>
    </>
  );
}
