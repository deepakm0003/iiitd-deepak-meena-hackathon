import { useState } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown } from "lucide-react";
import { useApi, type WatchName, type Watchlist as WatchlistT } from "../api";
import { money } from "../format";
import { ErrorNote, Loading, PageHeader, Tag, TypeChip } from "../ui";

const COLS = [
  { key: "Red", dot: "bg-[#e5484d]", ring: "border-[#e5484d]/40", text: "text-[#ff7b7f]" },
  { key: "Amber", dot: "bg-gold", ring: "border-gold/40", text: "text-gold" },
  { key: "Green", dot: "bg-sage", ring: "border-sage/40", text: "text-sage" },
] as const;

export default function Watchlist() {
  const wl = useApi<WatchlistT>("/watchlist?limit=1000", 120_000);
  const [shown, setShown] = useState<Record<string, number>>({ Red: 12, Amber: 12, Green: 12 });

  if (wl.error) return <ErrorNote error={wl.error} onRetry={wl.reload} />;
  if (!wl.data) return <Loading label="Scoring the watchlist" />;
  const w = wl.data;
  const total = w.counts.Red + w.counts.Amber + w.counts.Green;
  const exposure = w.exposure_by_status.Red + w.exposure_by_status.Amber + w.exposure_by_status.Green;

  return (
    <>
      <PageHeader eyebrow="Early warning" title="Watchlist" />
      <div className="mb-6 flex flex-wrap gap-x-8 gap-y-2 text-sm text-mute">
        <span>
          <span className="text-bone">{total}</span> monitored names
        </span>
        <span>
          <span className="text-bone">{money(exposure, 0)}</span> total exposure
        </span>
        <span>
          Evidence window <span className="text-bone">{w.lookback_days} days</span>, half-life weighted
        </span>
        <span>
          <span className="text-bone">{w.names.filter((n) => n.hard_flags.length).length}</span> hard flags
        </span>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        {COLS.map((c, ci) => {
          const names = w.names.filter((n) => n.status === c.key);
          return (
            <motion.section
              key={c.key}
              className="rounded-xl border border-line bg-ink-2"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: ci * 0.08 }}
            >
              <header className="flex items-center justify-between border-b border-line px-5 py-4">
                <span className="flex items-center gap-2.5 text-bone">
                  <span className={`h-2.5 w-2.5 rounded-full ${c.dot}`} /> {c.key}
                  <span className="font-serif text-2xl">{w.counts[c.key]}</span>
                </span>
                <span className="text-xs text-mute">{money(w.exposure_by_status[c.key])} exposure</span>
              </header>
              <ul className="space-y-2 p-3">
                {names.slice(0, shown[c.key]).map((n) => (
                  <NameCard key={n.name} n={n} tone={c} />
                ))}
              </ul>
              {names.length > shown[c.key] && (
                <button
                  onClick={() => setShown((s) => ({ ...s, [c.key]: s[c.key] + 24 }))}
                  className="w-full border-t border-line py-3 text-xs text-mute hover:text-gold"
                >
                  Show more ({names.length - shown[c.key]} left)
                </button>
              )}
            </motion.section>
          );
        })}
      </div>
      <p className="mt-6 text-xs text-mute">
        Score: noisy-OR of the three strongest recent signals (probability of a large adverse move × factuality × source credibility × time
        decay). Listed issuers turn Amber at 25 and Red at 50; SMEs at 5 and 10, because their score is a proxy distress probability with a
        2% base rate. Thresholds and weights are assumption A-28 in the assumptions register.
      </p>
    </>
  );
}

function NameCard({ n, tone }: { n: WatchName; tone: (typeof COLS)[number] }) {
  const [open, setOpen] = useState(false);
  const top = n.drivers[0];
  return (
    <li className={`rounded-lg border bg-ink-3/60 ${open ? tone.ring : "border-line"}`}>
      <button className="w-full p-3.5 text-left" onClick={() => setOpen((o) => !o)}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="truncate text-sm text-bone">{n.name}</span>
              <Tag>{n.tranche === 2 ? "Corporate" : "SME"}</Tag>
            </div>
            <div className="mt-0.5 text-xs text-mute">
              {n.sector ?? "n/a"} · {money(n.exposure)}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-wider text-mute">Risk score</div>
            <div className={`font-mono text-lg ${tone.text}`}>{Math.round(n.score * 100)}</div>
          </div>
        </div>
        {n.hard_flags.length > 0 && (
          <div className="mt-2 flex gap-1.5">
            {n.hard_flags.map((f) => (
              <Tag key={f} tone="ember">
                hard flag {f}
              </Tag>
            ))}
          </div>
        )}
        {top && <p className="mt-2 line-clamp-2 text-xs text-bone/70">{top.headline}</p>}
        {n.drivers.length > 0 && (
          <span className="mt-2 inline-flex items-center gap-1 text-[11px] text-mute">
            {n.drivers.length} driver{n.drivers.length > 1 ? "s" : ""}
            <ChevronDown className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`} />
          </span>
        )}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.ul
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-t border-line"
          >
            {n.drivers.map((d) => (
              <li key={d.event_id} className="border-b border-line/60 px-3.5 py-2.5 last:border-0">
                <Link to={`/app/signals/${d.event_id}`} className="block text-xs text-bone hover:text-gold">
                  {d.headline}
                </Link>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-mute">
                  <TypeChip type={d.event_type} />
                  <span>Impact {d.impact.toFixed(1)}</span>
                  <span>weight {d.weight.toFixed(2)}</span>
                  <span>{d.age_days.toFixed(1)} d old</span>
                </div>
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </li>
  );
}
