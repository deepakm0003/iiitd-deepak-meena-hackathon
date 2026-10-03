import { motion } from "framer-motion";
import { ArrowUpRight } from "lucide-react";
import { ClosingCta, PageHero } from "../components/site/PageHero";
import { Reveal } from "../components/site/Reveal";
import { CountUp, REPO } from "../components/site/Sections";

// Every number on this page comes from docs/results/*.json and docs/IMPROVEMENT_LOG.md in the repository.
export const STATS = [
  { value: 296, decimals: 0, label: "Human-labelled events" },
  { value: 0.73, decimals: 2, label: "Out-of-time Impact AUC" },
  { value: 0.138, decimals: 3, label: "Brier score vs 0.155 base rate" },
  { value: 11, decimals: 0, label: "Event classes" },
];

export const CARDS = [
  {
    tag: "Validation 01",
    title: "Locked human test",
    body: "On a 212-item test set labelled by a person and evaluated once, event accuracy rose from 61.8% to 66.0% and macro-F1 from 0.59 to 0.64. Company resolution: 75.9%.",
  },
  {
    tag: "Validation 02",
    title: "Out-of-time Impact",
    body: "1,003 SEC 8-K filings published after the training window: AUC 0.73 for large price moves, Spearman 0.33, Brier 0.138 against a 0.155 no-skill baseline.",
  },
  {
    tag: "Validation 03",
    title: "Label agreement",
    body: "LLM silver labels were checked against human labels: Cohen's kappa 0.67 for event class and 0.71 for the company. Only human labels are used to report accuracy.",
  },
  {
    tag: "Limitation 01",
    title: "Credit recall is the weak spot",
    body: "On the locked test, Credit Event recall from the model fell to 0.38. Credit alerts from 8-K items and rules are marked confirmed; model-only credit alerts are not.",
  },
  {
    tag: "Limitation 02",
    title: "Impact is validated on filings",
    body: "The Impact model was validated only on firm-specific 8-K events with exact timestamps. Macro, geopolitical and social-only events have no single stock to test against.",
  },
  {
    tag: "Limitation 03",
    title: "Novel events are harder",
    body: "Events without strong historical analogues can be under-scored. Analysts always see the contributing factors and the evidence, not just the score.",
  },
];

export const REJECTED = [
  ["DeBERTa-v3-large verifier", "Development accuracy fell from 69% to 63% and macro-F1 from 0.60 to 0.55."],
  ["Zero-shot rescue of abstentions", "Lower accuracy at every threshold tried; false alarms rose up to fivefold."],
  ["Fitted Impact weights", "Severity is not identifiable from the few severe events, so expert weights were kept."],
  ["MiniLM event head", "Macro-F1 0.58 against 0.63 for bge-base on the same human labels."],
];

export default function ModelTrust() {
  return (
    <>
      <PageHero
        eyebrow="Model trust"
        lines={["Measured,", "not marketed."]}
        lede="We publish realistic validation, limitations and assumptions so risk teams can judge the model, not just trust the interface."
        aside={<Glow />}
      />

      <section className="container-x">
        <div className="grid border-b border-line sm:grid-cols-2 lg:grid-cols-4">
          {STATS.map((s, i) => (
            <Reveal key={s.label} delay={i * 0.08} className="border-line px-2 py-10 sm:px-8 lg:border-l lg:first:border-l-0">
              <div className="text-gold">
                <CountUp value={s.value} decimals={s.decimals} className="text-5xl font-light sm:text-6xl" />
              </div>
              <p className="mt-4 text-sm text-mute">{s.label}</p>
            </Reveal>
          ))}
        </div>
      </section>

      <section className="container-x py-20 md:py-28">
        <div className="grid gap-px overflow-hidden rounded-xl border border-line bg-line md:grid-cols-3">
          {CARDS.map((c, i) => (
            <Reveal key={c.title} delay={(i % 3) * 0.08} className="bg-ink-2">
              <div className="group flex h-full min-h-[260px] flex-col p-8 transition-colors hover:bg-ink-3">
                <p className={`eyebrow ${c.tag.startsWith("Limit") ? "text-ember-bright" : "text-gold"}`}>{c.tag}</p>
                <h3 className="mt-10 text-2xl font-light text-bone">{c.title}</h3>
                <p className="mt-4 text-sm leading-relaxed text-mute">{c.body}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      <section className="container-x grid gap-12 pb-24 md:grid-cols-[1fr_1.4fr] md:pb-32">
        <Reveal>
          <p className="eyebrow text-mute">Negative results</p>
          <h2 className="mt-5 text-4xl font-light leading-[1.1] tracking-tight text-gold sm:text-5xl">
            What we tried and left out.
          </h2>
          <p className="mt-6 max-w-sm leading-relaxed text-mute">
            Failed experiments are published next to the ones that worked, with their numbers.
          </p>
        </Reveal>
        <ul className="divide-y divide-line border-y border-line">
          {REJECTED.map(([t, why], i) => (
            <Reveal key={t} delay={i * 0.08}>
              <li className="grid gap-2 py-6 sm:grid-cols-[1fr_1.3fr] sm:gap-8">
                <span className="text-bone">{t}</span>
                <span className="text-sm text-mute">{why}</span>
              </li>
            </Reveal>
          ))}
        </ul>
      </section>

      <ClosingCta lines={["Trust is an", "interface requirement."]}>
        <a
          href={`${REPO}/blob/main/docs/IMPROVEMENT_LOG.md`}
          target="_blank"
          rel="noreferrer"
          className="group inline-flex items-center gap-2 rounded-md bg-ember px-5 py-3 text-sm text-cream transition-colors hover:bg-ember-bright"
        >
          Open the improvement log <ArrowUpRight className="h-4 w-4" />
        </a>
        <a
          href={`${REPO}/tree/main/docs/results`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-2 rounded-md border border-line px-5 py-3 text-sm text-bone transition-colors hover:border-gold hover:text-gold"
        >
          Raw results <ArrowUpRight className="h-4 w-4" />
        </a>
      </ClosingCta>
    </>
  );
}

function Glow() {
  return (
    <div className="relative hidden h-[300px] lg:block" aria-hidden>
      <motion.div
        className="absolute inset-0 rounded-full"
        style={{ background: "radial-gradient(circle at 50% 50%, rgba(217,180,108,0.22), rgba(181,82,58,0.08) 40%, transparent 70%)" }}
        animate={{ scale: [1, 1.08, 1], opacity: [0.8, 1, 0.8] }}
        transition={{ duration: 7, repeat: Infinity, ease: "easeInOut" }}
      />
      <svg viewBox="0 0 300 300" className="absolute inset-0 m-auto h-full">
        {[60, 95, 130].map((r, i) => (
          <motion.circle
            key={r}
            cx="150"
            cy="150"
            r={r}
            fill="none"
            stroke="var(--color-gold)"
            strokeOpacity={0.25 - i * 0.05}
            strokeDasharray="2 6"
            animate={{ rotate: i % 2 ? -360 : 360 }}
            transition={{ duration: 60 + i * 20, repeat: Infinity, ease: "linear" }}
            style={{ originX: "150px", originY: "150px" }}
          />
        ))}
      </svg>
    </div>
  );
}
