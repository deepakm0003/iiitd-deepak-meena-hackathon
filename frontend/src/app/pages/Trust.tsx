import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowUpRight } from "lucide-react";
import { REJECTED, cardsFrom, statsFrom } from "../../pages/ModelTrust";
import { useMetrics } from "../../lib/live";
import { REPO } from "../../components/site/Sections";
import { ErrorNote, Loading, PageHeader, Panel } from "../ui";

// Validation numbers from GET /model/metrics (the evaluation outputs in docs/results), as on the public page.
export default function Trust() {
  const { data: m, error, reload } = useMetrics();
  if (error) return <ErrorNote error={error} onRetry={reload} />;
  if (!m) return <Loading label="Loading the latest evaluation results" />;
  const STATS = statsFrom(m);
  const CARDS = cardsFrom(m);
  return (
    <>
      <PageHeader
        eyebrow="Validation"
        title="Model trust"
        right={
          <a
            href={`${REPO}/blob/main/docs/IMPROVEMENT_LOG.md`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 rounded-md border border-line px-4 py-2 text-sm text-bone hover:border-gold hover:text-gold"
          >
            Improvement log <ArrowUpRight className="h-4 w-4" />
          </a>
        }
      />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {STATS.map((s, i) => (
          <motion.div
            key={s.label}
            className="rounded-xl border border-line bg-ink-2 p-5"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.06 }}
          >
            <div className="font-serif text-4xl text-gold">{s.value.toFixed(s.decimals)}</div>
            <div className="mt-2 text-sm text-mute">{s.label}</div>
          </motion.div>
        ))}
      </div>
      <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {CARDS.map((c) => (
          <div key={c.title} className="rounded-xl border border-line bg-ink-2 p-5">
            <p className={`eyebrow ${c.tag.startsWith("Limit") ? "text-ember-bright" : "text-gold"}`}>{c.tag}</p>
            <h3 className="mt-4 text-lg text-bone">{c.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-mute">{c.body}</p>
          </div>
        ))}
      </div>
      <Panel className="mt-6" title="Tried and left out" sub="Negative results, published with their numbers">
        <ul className="divide-y divide-line">
          {REJECTED.map(([t, why]) => (
            <li key={t} className="grid gap-1 py-3 text-sm sm:grid-cols-[260px_1fr]">
              <span className="text-bone">{t}</span>
              <span className="text-mute">{why}</span>
            </li>
          ))}
        </ul>
      </Panel>
      <p className="mt-6 text-sm text-mute">
        Longer version on the{" "}
        <Link to="/model-trust" className="text-gold hover:underline">
          public Model trust page
        </Link>
        .
      </p>
    </>
  );
}
