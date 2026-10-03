import type { ReactNode } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, Loader2 } from "lucide-react";
import { RISK_STYLE, TYPE_COLOR, SHORT_TYPE, provenanceTag } from "./format";

export function Panel({ title, sub, right, children, className = "" }: {
  title?: ReactNode;
  sub?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-line bg-ink-2 ${className}`}>
      {(title || right) && (
        <header className="flex items-start justify-between gap-4 px-5 pt-5">
          <div>
            {title && <h2 className="text-[15px] font-medium text-bone">{title}</h2>}
            {sub && <p className="mt-0.5 text-xs text-mute">{sub}</p>}
          </div>
          {right}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

export function PageHeader({ eyebrow, title, right }: { eyebrow: string; title: string; right?: ReactNode }) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
      <div>
        <p className="eyebrow text-gold">{eyebrow}</p>
        <h1 className="mt-2 text-[34px] font-light tracking-tight text-bone">{title}</h1>
      </div>
      {right}
    </div>
  );
}

export function Kpi({ icon, value, label, sub, tone }: {
  icon: ReactNode;
  value: ReactNode;
  label: string;
  sub?: ReactNode;
  tone?: "ember" | "sage" | "mute";
}) {
  const subColor = tone === "ember" ? "text-ember-bright" : tone === "sage" ? "text-sage" : "text-mute";
  return (
    <div className="flex gap-4 px-5 py-5">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-line bg-ink-3 text-gold">
        {icon}
      </span>
      <div className="min-w-0">
        <div className="font-serif text-[30px] leading-none text-bone">{value}</div>
        <div className="mt-2 text-sm text-bone/80">{label}</div>
        {sub && <div className={`mt-0.5 truncate text-xs ${subColor}`}>{sub}</div>}
      </div>
    </div>
  );
}

export function RiskChip({ level }: { level: string }) {
  const s = RISK_STYLE[level] ?? RISK_STYLE.Low;
  return (
    <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wider ${s.chip}`}>
      {level}
    </span>
  );
}

export function TypeChip({ type }: { type: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded border border-line bg-ink-3 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-bone/75">
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: TYPE_COLOR[type] ?? "#666" }} />
      {SHORT_TYPE[type] ?? type}
    </span>
  );
}

export function Tag({ children, tone = "mute" }: { children: ReactNode; tone?: "mute" | "gold" | "sage" | "ember" }) {
  const cls = {
    mute: "border-line text-mute",
    gold: "border-gold/40 text-gold",
    sage: "border-sage/40 text-sage",
    ember: "border-ember-bright/40 text-ember-bright",
  }[tone];
  return <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ${cls}`}>{children}</span>;
}

export function ProvTag({ source }: { source: string }) {
  const { tag, tone } = provenanceTag(source);
  return (
    <span title={source}>
      <Tag tone={tone === "measured" ? "sage" : tone === "assumption" ? "gold" : "mute"}>{tag}</Tag>
    </span>
  );
}

export function ImpactRing({ value, size = 56 }: { value: number; size?: number }) {
  const r = 22;
  const c = 2 * Math.PI * r;
  const color = value >= 7 ? "var(--color-ember-bright)" : value >= 5 ? "var(--color-gold)" : "var(--color-mute)";
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg viewBox="0 0 56 56" className="h-full w-full -rotate-90">
        <circle cx="28" cy="28" r={r} fill="none" stroke="var(--color-line)" strokeWidth="4" />
        <motion.circle
          cx="28"
          cy="28"
          r={r}
          fill="none"
          stroke={color}
          strokeWidth="4"
          strokeLinecap="round"
          strokeDasharray={c}
          initial={{ strokeDashoffset: c }}
          animate={{ strokeDashoffset: c * (1 - value / 10) }}
          transition={{ duration: 0.9, ease: "easeOut" }}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center font-mono text-sm text-bone">{value.toFixed(1)}</span>
    </div>
  );
}

export function Bar({ value, max = 1, color = "var(--color-gold)", delay = 0 }: { value: number; max?: number; color?: string; delay?: number }) {
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-line">
      <motion.div
        className="h-full rounded-full"
        style={{ background: color }}
        initial={{ width: 0 }}
        animate={{ width: `${Math.max(0, Math.min(1, value / max)) * 100}%` }}
        transition={{ duration: 0.8, delay, ease: "easeOut" }}
      />
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-10 text-sm text-mute">
      <Loader2 className="h-4 w-4 animate-spin" /> {label}…
    </div>
  );
}

export function ErrorNote({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-ember/40 bg-ember/10 px-4 py-3 text-sm">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-ember-bright" />
      <div>
        <p className="text-bone">Could not reach the Tripwire API.</p>
        <p className="mt-0.5 font-mono text-xs text-mute">{error}</p>
        {onRetry && (
          <button onClick={onRetry} className="mt-2 text-xs text-gold hover:underline">
            Retry
          </button>
        )}
      </div>
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-ink-3 ${className}`} />;
}
