import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowRight,
  ArrowUpRight,
  Quote,
  ShieldCheck,
  BookOpenCheck,
  Lock,
  Landmark,
  Code2,
  type LucideIcon,
} from "lucide-react";
import { Reveal } from "./Reveal";
import { Logo } from "./Logo";
import { DecisionArt, EvolveArt, SignalsArt } from "../art/Wireframes";
import { WAL, fmtMoney, fmtPct } from "../../lib/caseStudy";

export const REPO = "https://github.com/deepakm0003/iiitd-deepak-meena-hackathon";

export function CaseBand() {
  return (
    <section className="container-x -mt-4 pb-24">
      <Reveal>
        <Link
          to={`/app/signals/${WAL.eventId}`}
          className="group relative grid overflow-hidden rounded-2xl bg-ember p-8 sm:p-12 md:grid-cols-[1fr_auto] md:items-end"
        >
          <motion.div
            aria-hidden
            className="absolute -right-20 -top-20 h-72 w-72 rounded-full border border-cream/20"
            animate={{ scale: [1, 1.08, 1] }}
            transition={{ duration: 6, repeat: Infinity }}
          />
          <div className="relative">
            <p className="eyebrow text-cream/80">Replay · Western Alliance · {WAL.date}</p>
            <h2 className="mt-4 max-w-xl text-3xl font-light leading-tight text-cream sm:text-[42px]">
              From evidence to capital impact.
            </h2>
            <p className="mt-4 max-w-lg text-cream/80">
              One 8-K line, "{WAL.evidence}", becomes a Credit Event (liquidity stress), an Impact of {WAL.impact.toFixed(1)}, a{" "}
              {fmtMoney(WAL.pnl)} stress loss and CET1 moving from {fmtPct(WAL.cet1Before)} to {fmtPct(WAL.cet1After)}.
            </p>
          </div>
          <span className="relative mt-8 inline-flex items-center gap-2 text-sm font-medium text-cream md:mt-0">
            Open the reasoning trace
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
          </span>
        </Link>
      </Reveal>
    </section>
  );
}

export function Mission() {
  return (
    <section className="bg-gold text-ink">
      <div className="container-x grid gap-10 py-24 md:grid-cols-[220px_1fr] md:py-32">
        <Reveal>
          <p className="eyebrow">01 / Our mission</p>
        </Reveal>
        <Reveal delay={0.1}>
          <h2 className="text-4xl font-light leading-[1.08] tracking-tight sm:text-6xl">
            Where trust meets
            <br />
            transformation.
          </h2>
          <p className="mt-8 max-w-2xl text-lg leading-relaxed text-ink/75">
            Risk teams don't need more headlines. They need to know which event is real, which exposure it touches
            and what it does to capital, with the evidence to defend that answer to a model-risk reviewer.
          </p>
        </Reveal>
      </div>
    </section>
  );
}

const FEATURES = [
  {
    no: "02",
    tag: "Signals, not noise",
    title: "Trusted intelligence for every risk workflow.",
    body: "SEC filings, news, central-bank releases and social posts flow into one governed layer. Each item is classified into an event, tied to a company and kept with the exact sentence that triggered it.",
    art: SignalsArt,
    to: "/product",
  },
  {
    no: "03",
    tag: "Decision engineering",
    title: "AI designed for banking and capital decisions.",
    body: "An Impact score built from seven named factors, then Module B: spread, equity and rating shocks translated into P&L, ECL, RWA and CET1, with every input and assumption labelled.",
    art: DecisionArt,
    to: "/how-it-works",
  },
  {
    no: "04",
    tag: "Built to evolve",
    title: "Staying ahead of what's next in risk.",
    body: "Historical analogues calibrate how markets reacted before. New labels and new evidence retrain the models, measured against a locked test set, without losing the audit trail.",
    art: EvolveArt,
    to: "/model-trust",
  },
];

export function Features() {
  return (
    <section className="py-16 md:py-24">
      {FEATURES.map((f, i) => {
        const Art = f.art;
        return (
          <div key={f.no} className="container-x grid items-center gap-12 py-16 md:grid-cols-2 md:py-24">
            <Reveal className={`flex justify-center ${i % 2 ? "md:order-2" : ""}`}>
              <Art />
            </Reveal>
            <Reveal delay={0.1} className={i % 2 ? "md:order-1" : ""}>
              <p className="eyebrow text-mute">
                {f.no} / {f.tag}
              </p>
              <h3 className="mt-5 max-w-md text-4xl font-light leading-[1.1] tracking-tight text-gold sm:text-5xl">
                {f.title}
              </h3>
              <p className="mt-6 max-w-md leading-relaxed text-mute">{f.body}</p>
              <Link
                to={f.to}
                className="group mt-8 inline-flex items-center gap-2 rounded-md bg-ember px-4 py-2 text-sm text-cream transition-colors hover:bg-ember-bright"
              >
                Explore <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
              </Link>
            </Reveal>
          </div>
        );
      })}
    </section>
  );
}

const STEPS = [
  ["Collect", "SEC EDGAR 8-Ks, GDELT, Finnhub, Fed and RBI releases polled every 10–30 minutes, Bluesky streamed. Deduplicated."],
  ["Understand", "8-K item map, context rules, a fine-tuned classifier and a zero-shot verifier. Evidence span kept."],
  ["Score", "Impact 1–10 from severity, sentiment, entity, novelty, corroboration, credibility and history."],
  ["Map", "Linked to the book by name, sector and geography. Early-warning watchlist: Green, Amber, Red."],
  ["Stress", "Shocks priced through P&L, ECL, RWA and CET1, with reverse stress and the reason for every step."],
];

export function HowItWorks() {
  return (
    <section className="bg-cream text-ink">
      <div className="container-x py-24 md:py-32">
        <Reveal>
          <p className="eyebrow text-ink/60">05 / How it works</p>
          <h2 className="mt-5 max-w-3xl text-4xl font-light leading-[1.08] tracking-tight sm:text-[54px]">
            Five stages, one trace.
          </h2>
          <Link to="/how-it-works" className="mt-5 inline-flex items-center gap-1.5 text-sm text-ember hover:underline">
            See every step <ArrowRight className="h-4 w-4" />
          </Link>
        </Reveal>
        <div className="relative mt-16">
          <motion.div
            aria-hidden
            className="absolute top-[18px] right-0 left-0 hidden h-px origin-left bg-ember md:block"
            initial={{ scaleX: 0 }}
            whileInView={{ scaleX: 1 }}
            viewport={{ once: true, margin: "-100px" }}
            transition={{ duration: 1.8, ease: "easeInOut" }}
          />
          <ol className="grid gap-10 md:grid-cols-5 md:gap-6">
            {STEPS.map(([title, body], i) => (
              <Reveal key={title} delay={0.2 + i * 0.15}>
                <li className="relative">
                  <span className="relative z-10 flex h-9 w-9 items-center justify-center rounded-full border border-ember bg-cream font-mono text-xs text-ember">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <h3 className="mt-5 text-xl font-medium">{title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-ink/65">{body}</p>
                </li>
              </Reveal>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}

export function Proof() {
  return (
    <section className="bg-paper text-ink">
      <div className="container-x grid gap-12 py-24 md:grid-cols-[1fr_1.3fr] md:py-32">
        <Reveal>
          <p className="eyebrow text-ink/60">06 / Proven impact</p>
          <h2 className="mt-5 text-4xl font-light leading-[1.08] tracking-tight sm:text-[52px]">
            Measured, not
            <br />
            claimed.
          </h2>
          <p className="mt-6 max-w-sm leading-relaxed text-ink/65">
            Every figure comes from a published evaluation, and that includes the experiments that failed.
          </p>
          <Link to="/model-trust" className="mt-6 inline-flex items-center gap-1.5 text-sm text-ember hover:underline">
            See the full validation <ArrowUpRight className="h-4 w-4" />
          </Link>
        </Reveal>
        <div className="grid gap-5 sm:grid-cols-2">
          <StatCard value={296} label="Human-labelled events used to validate the event classifier." tone="ember" />
          <StatCard
            value={0.73}
            decimals={2}
            label="Impact model AUC for large price moves, on an out-of-time sample."
            tone="gold"
          />
        </div>
      </div>
    </section>
  );
}

function StatCard({ value, decimals = 0, label, tone }: { value: number; decimals?: number; label: string; tone: "ember" | "gold" }) {
  return (
    <Reveal delay={tone === "gold" ? 0.15 : 0}>
      <div
        className={`flex h-full min-h-[240px] flex-col justify-between rounded-2xl p-8 ${
          tone === "ember" ? "bg-ember text-cream" : "bg-gold text-ink"
        }`}
      >
        <CountUp value={value} decimals={decimals} />
        <p className={`max-w-[240px] text-sm ${tone === "ember" ? "text-cream/80" : "text-ink/70"}`}>{label}</p>
      </div>
    </Reveal>
  );
}

export function CountUp({ value, decimals, className = "text-7xl font-light tracking-tight sm:text-8xl" }: { value: number; decimals: number; className?: string }) {
  return (
    <motion.span
      className={className}
      initial={{ opacity: 0 }}
      whileInView={{ opacity: 1 }}
      viewport={{ once: true }}
      onViewportEnter={(e) => {
        const el = e?.target as HTMLElement | undefined;
        if (!el || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
        const start = performance.now();
        const tick = (now: number) => {
          const t = Math.min(1, (now - start) / 1400);
          el.textContent = (value * (1 - Math.pow(1 - t, 3))).toFixed(decimals);
          if (t < 1) requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      }}
    >
      {value.toFixed(decimals)}
    </motion.span>
  );
}

const SOURCES = ["SEC EDGAR", "GDELT", "Finnhub", "Federal Reserve", "Reserve Bank of India", "Bluesky"];

export function Sources() {
  return (
    <section className="border-t border-ink/10 bg-paper text-ink">
      <div className="container-x grid gap-12 py-20 md:grid-cols-[1fr_1.3fr] md:items-center md:py-24">
        <Reveal>
          <p className="eyebrow text-ink/60">07 / Data</p>
          <h2 className="mt-5 text-4xl font-light leading-[1.08] tracking-tight sm:text-[48px]">
            Built on public,
            <br />
            traceable sources.
          </h2>
          <p className="mt-6 max-w-sm text-sm leading-relaxed text-ink/60">
            Public feeds only. Every signal links back to the filing, release or article it came from.
          </p>
        </Reveal>
        <div className="grid grid-cols-2 gap-x-6 gap-y-8 sm:grid-cols-3">
          {SOURCES.map((s, i) => (
            <Reveal key={s} delay={i * 0.06}>
              <div className="text-center text-lg font-medium text-ink/75 transition-colors hover:text-ember">{s}</div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

const TRUST: [LucideIcon, string, string][] = [
  [Quote, "Evidence on every alert", "The exact sentence that triggered a classification is stored and shown."],
  [ShieldCheck, "Confirmed alert tier", "Alerts from 8-K items and the most precise rules are marked separately from model guesses."],
  [BookOpenCheck, "Assumptions register", "28 documented assumptions, each with its rationale and where it is used."],
  [Lock, "Locked test sets", "Final accuracy measured once on held-out data. Never used for tuning."],
  [Landmark, "Basel III capital maths", "CET1 net of tax, RWA from rating migration, 7% Basel and 8% RBI floors."],
  [Code2, "Open source, MIT", "Code, configs, evaluations and failed experiments are all in the repository."],
];

export function Trust() {
  return (
    <section className="py-24 md:py-32">
      <div className="container-x">
        <Reveal className="text-center">
          <p className="eyebrow text-ember-bright">Governance</p>
          <h2 className="mx-auto mt-5 max-w-3xl font-serif text-5xl leading-[1.05] text-bone sm:text-6xl">
            Built for model-risk review.
          </h2>
          <p className="mx-auto mt-5 max-w-xl text-sm text-mute">
            Explainability is part of the architecture, not a report written afterwards.
          </p>
        </Reveal>
        <div className="mt-16 grid border-t border-l border-line sm:grid-cols-2 lg:grid-cols-3">
          {TRUST.map(([Icon, title, body], i) => (
            <Reveal key={title} delay={i * 0.06} className="border-r border-b border-line">
              <div className="group flex h-full flex-col items-center px-8 py-12 text-center">
                <span className="flex h-14 w-14 items-center justify-center rounded-full border border-line bg-ink-2 text-gold transition-colors group-hover:border-gold">
                  <Icon className="h-5 w-5" strokeWidth={1.5} />
                </span>
                <h3 className="mt-6 text-[15px] text-bone">{title}</h3>
                <p className="mt-2 max-w-[260px] text-sm leading-relaxed text-mute">{body}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

export function Footer() {
  const cols: [string, [string, string][]][] = [
    ["Platform", [["Product", "/product"], ["How it works", "/how-it-works"], ["Live demo", "/app"]]],
    ["Trust", [["Model trust", "/model-trust"], ["Assumptions register", `${REPO}/blob/main/config/assumptions_register.yaml`], ["Improvement log", `${REPO}/blob/main/docs/IMPROVEMENT_LOG.md`]]],
    ["Resources", [["Resources", "/resources"], ["Module B method", `${REPO}/blob/main/docs/module_b.md`], ["AI usage", `${REPO}/blob/main/docs/ai_usage.md`]]],
    ["Data", [["SEC EDGAR", "https://www.sec.gov/edgar"], ["GDELT", "https://www.gdeltproject.org"], ["Finnhub", "https://finnhub.io"]]],
  ];
  return (
    <footer className="border-t border-line">
      <div className="container-x grid gap-12 py-16 md:grid-cols-[1.4fr_repeat(4,1fr)]">
        <div>
          <Logo />
          <p className="mt-4 max-w-xs text-sm text-mute">Decision-grade financial risk intelligence for banks.</p>
        </div>
        {cols.map(([head, links]) => (
          <div key={head}>
            <p className="text-sm text-bone">{head}</p>
            <ul className="mt-4 space-y-2.5">
              {links.map(([label, href]) => (
                <li key={label}>
                  {href.startsWith("/") ? (
                    <Link to={href} className="text-sm text-mute hover:text-gold">
                      {label}
                    </Link>
                  ) : (
                    <a href={href} target="_blank" rel="noreferrer" className="text-sm text-mute hover:text-gold">
                      {label}
                    </a>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <Wordmark />
      <div className="container-x flex flex-col gap-3 border-t border-line py-6 text-xs text-mute sm:flex-row sm:items-center sm:justify-between">
        <span>© 2026 Tripwire · Built for S&amp;P Global × CRISIL Code to Connect · MIT licence</span>
        <a href={REPO} target="_blank" rel="noreferrer" className="hover:text-gold">
          Source code on GitHub
        </a>
      </div>
    </footer>
  );
}

/** Oversized "tripwire" wordmark closing every page: letters rise in, then a slow brass sheen passes over. */
function Wordmark() {
  const letters = "tripwire".split("");
  return (
    <div className="container-x overflow-hidden border-t border-line pt-8 pb-6" aria-hidden>
      <motion.div
        className="relative flex select-none justify-center font-sans text-[25vw] leading-[0.95] font-bold tracking-[-0.06em] xl:text-[300px]"
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, margin: "-40px" }}
        variants={{ show: { transition: { staggerChildren: 0.06 } } }}
      >
        {letters.map((ch, i) => (
          <motion.span
            key={i}
            className="wordmark-letter"
            variants={{ hidden: { y: "60%", opacity: 0 }, show: { y: 0, opacity: 1 } }}
            transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
          >
            {ch}
          </motion.span>
        ))}
      </motion.div>
    </div>
  );
}
