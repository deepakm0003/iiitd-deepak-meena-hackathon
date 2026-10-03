import type { ReactNode } from "react";
import { motion } from "framer-motion";

const ease = [0.22, 1, 0.36, 1] as const;

/** Inner-page hero: eyebrow, large brass headline revealed line by line, lede, then a hairline rule. */
export function PageHero({ eyebrow, lines, lede, aside }: { eyebrow: string; lines: string[]; lede: string; aside?: ReactNode }) {
  return (
    <section className="relative overflow-hidden pt-36 sm:pt-44">
      <div className="container-x grid items-end gap-12 pb-16 lg:grid-cols-[1.2fr_1fr] lg:pb-20">
        <div>
          <motion.p
            className="eyebrow text-mute"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease }}
          >
            {eyebrow}
          </motion.p>
          <h1 className="mt-6 text-[48px] leading-[1.0] font-light tracking-[-0.025em] text-gold sm:text-7xl lg:text-[88px]">
            {lines.map((line, i) => (
              <span key={line} className="block overflow-hidden pb-1.5">
                <motion.span
                  className="block"
                  initial={{ y: "105%" }}
                  animate={{ y: 0 }}
                  transition={{ duration: 0.9, delay: 0.1 + i * 0.12, ease }}
                >
                  {line}
                </motion.span>
              </span>
            ))}
          </h1>
          <motion.p
            className="mt-8 max-w-[520px] text-[17px] leading-relaxed text-mute"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.8, delay: 0.5 }}
          >
            {lede}
          </motion.p>
        </div>
        {aside && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.9, delay: 0.35, ease }}
          >
            {aside}
          </motion.div>
        )}
      </div>
      <motion.div
        className="container-x"
        initial={{ scaleX: 0 }}
        animate={{ scaleX: 1 }}
        transition={{ duration: 1.2, delay: 0.4, ease }}
        style={{ originX: 0 }}
      >
        <div className="h-px bg-line" />
      </motion.div>
    </section>
  );
}

/** Closing call-to-action row used at the end of inner pages. */
export function ClosingCta({ lines, children }: { lines: string[]; children: ReactNode }) {
  return (
    <section className="container-x border-t border-line py-24 md:py-28">
      <div className="flex flex-col gap-10 md:flex-row md:items-center md:justify-between">
        <h2 className="text-4xl font-light leading-[1.08] tracking-tight text-bone sm:text-[52px]">
          {lines.map((l) => (
            <span key={l} className="block">
              {l}
            </span>
          ))}
        </h2>
        <div className="flex flex-wrap gap-4">{children}</div>
      </div>
    </section>
  );
}
