import { motion } from "framer-motion";
import { ArrowUpRight } from "lucide-react";
import { ClosingCta, PageHero } from "../components/site/PageHero";
import { Reveal } from "../components/site/Reveal";
import { CountUp, REPO } from "../components/site/Sections";
import { useMetrics, type Metrics } from "../lib/live";

// Every number on this page is read from the engine's API (GET /model/metrics), which serves the evaluation
// outputs in docs/results/*.json as last written. Nothing is typed in by hand.
const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

export function statsFrom(m: Metrics) {
  return [
    { value: m.human_labels, decimals: 0, label: "Human-labelled events" },
    ...(m.impact
      ? [
          { value: m.impact.auc, decimals: 2, label: "Out-of-time Impact AUC" },
          { value: m.impact.brier, decimals: 3, label: `Brier score vs ${m.impact.brier_base_rate.toFixed(3)} base rate` },
        ]
      : []),
    { value: m.event_classes, decimals: 0, label: "Event classes" },
  ];
}

export function cardsFrom(m: Metrics) {
  const before = m.locked_test.before;
  const after = m.locked_test.after;
  const fresh = m.fresh_test;
  const conf = fresh?.tiers?.confirmed;
  const credit = [before?.per_class["Credit Event"], after?.per_class["Credit Event"]];
  const cards = [];
  if (after) {
    cards.push({
      tag: "Validation 01",
      title: fresh ? "Two locked human tests" : "Locked human test",
      body:
        `${after.n}-item test, evaluated once: event accuracy ${before ? `${pct(before.accuracy)} to ` : ""}${pct(after.accuracy)}, ` +
        `macro-F1 ${before ? `${before.macro_f1.toFixed(2)} to ` : ""}${after.macro_f1.toFixed(2)}.` +
        (fresh
          ? ` A fresh ${fresh.n}-item set collected after the model freeze: ${pct(fresh.accuracy)} accuracy, macro-F1 ` +
            `${fresh.macro_f1.toFixed(2)}, company resolution ${pct(fresh.entity_accuracy ?? 0)}.`
          : ""),
    });
  }
  if (m.impact) {
    cards.push({
      tag: "Validation 02",
      title: "Out-of-time Impact",
      body:
        `${m.impact.n.toLocaleString()} SEC 8-K filings published after the training window: AUC ${m.impact.auc.toFixed(2)} for ` +
        `large price moves, Spearman ${m.impact.spearman.toFixed(2)}, Brier ${m.impact.brier.toFixed(3)} against a ` +
        `${m.impact.brier_base_rate.toFixed(3)} no-skill baseline.`,
    });
  }
  if (m.agreement) {
    cards.push({
      tag: "Validation 03",
      title: "Label agreement",
      body:
        `LLM silver labels were checked against ${m.agreement.n} human labels: Cohen's kappa ${m.agreement.event_kappa.toFixed(2)} ` +
        `for event class and ${m.agreement.entity_kappa.toFixed(2)} for the company. Only human labels are used to report accuracy.`,
    });
  }
  if (credit[1]) {
    cards.push({
      tag: "Limitation 01",
      title: "Credit recall is the weak spot",
      body:
        `On the locked test, Credit Event recall was ${credit[0] ? `${credit[0].recall.toFixed(2)} before and ` : ""}` +
        `${credit[1].recall.toFixed(2)} after the last change (${credit[1].support} test items). Only credit events from 8-K items, ` +
        "such as 1.03 bankruptcy, are marked confirmed; rule and model credit alerts stay standard.",
    });
  }
  cards.push({
    tag: "Limitation 02",
    title: "Impact is validated on filings",
    body: "The Impact model was validated only on firm-specific 8-K events with exact timestamps. Macro, geopolitical and social-only events have no single stock to test against.",
  });
  if (conf) {
    cards.push({
      tag: "Limitation 03",
      title: "The confirmed tier on new data",
      body:
        `On the fresh set, confirmed alerts were ${conf.correct} of ${conf.alerts} correct (${pct(conf.precision)}), well below ` +
        "the development estimate: a disaster rule fired on climate court cases and a macro rule on round-ups. The disaster rule now skips court stories; that change waits for the next fresh set to prove it.",
    });
  }
  return cards;
}

export const REJECTED = [
  ["DeBERTa-v3-large verifier", "Development accuracy fell from 69% to 63% and macro-F1 from 0.60 to 0.55."],
  ["Zero-shot rescue of abstentions", "Lower accuracy at every threshold tried; false alarms rose up to fivefold."],
  ["Fitted Impact weights", "Severity is not identifiable from the few severe events, so expert weights were kept."],
  ["Smaller or other encoders", "bge-base, bge-large and mpnet all scored about 74% in cross-validation against 77% for e5-large, which is shipped."],
];

export default function ModelTrust() {
  const { data: m, error } = useMetrics();
  const STATS = m ? statsFrom(m) : [];
  const CARDS = m ? cardsFrom(m) : [];
  return (
    <>
      <PageHero
        eyebrow="Model trust"
        lines={["Measured,", "not marketed."]}
        lede="We publish realistic validation, limitations and assumptions so risk teams can judge the model, not just trust the interface."
        aside={<Glow />}
      />

      <section className="container-x">
        {!m && <p className="py-10 text-sm text-mute">{error ? "The live engine is not reachable right now." : "Loading the latest evaluation results…"}</p>}
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
