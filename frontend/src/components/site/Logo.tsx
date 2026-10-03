import { motion } from "framer-motion";

export function Logo({ dark = true }: { dark?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <svg viewBox="0 0 32 20" className="h-5 w-8" aria-hidden>
        <motion.path
          d="M1 11h7l3-8 5 15 3-7h12"
          fill="none"
          stroke="var(--color-gold)"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          initial={{ pathLength: 0 }}
          animate={{ pathLength: 1 }}
          transition={{ duration: 1.2, ease: "easeInOut" }}
        />
      </svg>
      <span className={`text-[15px] font-semibold tracking-[0.22em] ${dark ? "text-bone" : "text-ink"}`}>
        TRIPWIRE
      </span>
    </span>
  );
}
