import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowRight, ArrowUpRight } from "lucide-react";
import { TraceCard } from "./TraceCard";
import { WAL } from "../../lib/caseStudy";

const ease = [0.22, 1, 0.36, 1] as const;

export function Hero() {
  return (
    <section className="relative overflow-hidden pt-28 pb-20 sm:pt-36 lg:pb-28">
      {/* faint grid */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.06]"
        style={{
          backgroundImage:
            "linear-gradient(var(--color-bone) 1px, transparent 1px), linear-gradient(90deg, var(--color-bone) 1px, transparent 1px)",
          backgroundSize: "64px 64px",
          maskImage: "radial-gradient(ellipse at 30% 30%, black 20%, transparent 70%)",
        }}
      />
      <div className="container-x relative grid items-center gap-16 lg:grid-cols-[1.05fr_1fr]">
        <div>
          <motion.p
            className="eyebrow text-gold"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease }}
          >
            The intelligence engine for financial risk
          </motion.p>
          <h1 className="mt-6 text-[44px] leading-[1.02] font-light tracking-[-0.02em] sm:text-6xl lg:text-[76px]">
            {["Engineering", "the clarity", "to act."].map((line, i) => (
              <span key={line} className="block overflow-hidden pb-1">
                <motion.span
                  className={`block ${i === 2 ? "text-gold" : "text-bone"}`}
                  initial={{ y: "105%" }}
                  animate={{ y: 0 }}
                  transition={{ duration: 0.9, delay: 0.15 + i * 0.12, ease }}
                >
                  {line}
                </motion.span>
              </span>
            ))}
          </h1>
          <motion.p
            className="mt-7 max-w-[480px] text-[17px] leading-relaxed text-mute"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.8, delay: 0.6 }}
          >
            Tripwire reads filings, news and market data, decides what actually happened, scores how much it
            matters and shows what it does to a bank's P&amp;L, ECL and CET1. Every number is traceable to its source.
          </motion.p>
          <motion.div
            className="mt-10 flex flex-wrap items-center gap-4"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.75, ease }}
          >
            <Link
              to="/product"
              className="group inline-flex items-center gap-2 rounded-md bg-gold px-6 py-3 text-sm font-medium text-ink transition-colors hover:bg-bone"
            >
              Explore the platform
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
            <Link
              to={`/app/signals/${WAL.eventId}`}
              className="inline-flex items-center gap-1.5 px-2 py-3 text-sm text-bone/80 transition-colors hover:text-gold"
            >
              See a real trace <ArrowUpRight className="h-4 w-4" />
            </Link>
          </motion.div>
        </div>

        <div className="relative flex justify-center lg:justify-end">
          {/* cream arc behind the card */}
          <motion.div
            aria-hidden
            className="absolute -right-24 top-1/2 h-[560px] w-[560px] -translate-y-1/2 rounded-full border-[56px] border-cream/90"
            initial={{ opacity: 0, scale: 0.85, rotate: -20 }}
            animate={{ opacity: 1, scale: 1, rotate: 0 }}
            transition={{ duration: 1.4, delay: 0.2, ease }}
            style={{ clipPath: "inset(0 0 0 45%)" }}
          />
          <motion.div
            className="relative w-full max-w-[460px]"
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.9, delay: 0.35, ease }}
          >
            <TraceCard />
          </motion.div>
        </div>
      </div>
    </section>
  );
}
