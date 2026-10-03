import { motion, useReducedMotion } from "framer-motion";

// Isometric line drawings for the feature rows. Paths draw in when scrolled into view, then drift slowly.
const K = 0.866;

function cube(cx: number, cy: number, s: number) {
  const p = {
    t: [cx, cy - s],
    rt: [cx + K * s, cy - s / 2],
    rb: [cx + K * s, cy + s / 2],
    b: [cx, cy + s],
    lb: [cx - K * s, cy + s / 2],
    lt: [cx - K * s, cy - s / 2],
    c: [cx, cy],
  };
  const P = (k: keyof typeof p) => p[k].join(",");
  return {
    outline: `M${P("t")}L${P("rt")}L${P("rb")}L${P("b")}L${P("lb")}L${P("lt")}Z`,
    inner: `M${P("lt")}L${P("c")}L${P("rt")}M${P("c")}L${P("b")}`,
    top: `M${P("t")}L${P("rt")}L${P("c")}L${P("lt")}Z`,
    points: Object.values(p),
  };
}

function rhombus(cx: number, cy: number, s: number) {
  return `M${cx},${cy - s / 2}L${cx + K * s},${cy}L${cx},${cy + s / 2}L${cx - K * s},${cy}Z`;
}

function hexagon(cx: number, cy: number, r: number) {
  const pts = Array.from({ length: 6 }, (_, i) => {
    const a = (Math.PI / 3) * i + Math.PI / 6;
    return `${(cx + r * Math.cos(a)).toFixed(1)},${(cy + r * Math.sin(a)).toFixed(1)}`;
  });
  return `M${pts.join("L")}Z`;
}

const draw = (delay = 0) => ({
  initial: { pathLength: 0, opacity: 0 },
  whileInView: { pathLength: 1, opacity: 1 },
  viewport: { once: true, margin: "-80px" },
  transition: { pathLength: { duration: 1.6, delay, ease: "easeInOut" as const }, opacity: { duration: 0.2, delay } },
});

const GOLD = "var(--color-gold)";
const EMBER = "var(--color-ember-bright)";

export function SignalsArt() {
  const reduce = useReducedMotion();
  const outer = cube(200, 200, 150);
  const mid = cube(200, 200, 100);
  const core = cube(200, 205, 52);
  return (
    <svg viewBox="0 0 400 400" className="h-auto w-full max-w-[420px]" aria-hidden>
      <motion.path d={outer.outline} stroke={GOLD} strokeOpacity={0.45} fill="none" strokeWidth={1} {...draw(0)} />
      <motion.path d={outer.inner} stroke={GOLD} strokeOpacity={0.25} fill="none" strokeWidth={1} {...draw(0.3)} />
      <motion.path d={mid.outline} stroke={GOLD} strokeOpacity={0.6} fill="none" strokeWidth={1} {...draw(0.5)} />
      <motion.g
        animate={reduce ? undefined : { y: [0, -8, 0] }}
        transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
      >
        <motion.path d={core.outline} fill={EMBER} fillOpacity={0.14} stroke={EMBER} strokeWidth={1.4} {...draw(0.9)} />
        <motion.path d={core.inner} stroke={EMBER} fill="none" strokeWidth={1.2} {...draw(1.2)} />
        <motion.path d={core.top} fill={GOLD} fillOpacity={0.12} stroke="none" {...draw(1.4)} />
      </motion.g>
      {mid.points.slice(0, 6).map(([x, y], i) => (
        <motion.circle
          key={i}
          cx={x}
          cy={y}
          r={3}
          fill="var(--color-ink)"
          stroke={GOLD}
          initial={{ scale: 0 }}
          whileInView={{ scale: 1 }}
          viewport={{ once: true }}
          transition={{ delay: 1.4 + i * 0.08 }}
        />
      ))}
      {/* signal ticks travelling toward the core */}
      {!reduce &&
        [outer.points[1], outer.points[4]].map(([x, y], i) => (
          <motion.circle
            key={`tick${i}`}
            r={2.5}
            fill={EMBER}
            animate={{ cx: [x, 200], cy: [y, 205], opacity: [0, 1, 0] }}
            transition={{ duration: 2.4, repeat: Infinity, delay: i * 1.2, ease: "easeIn" }}
          />
        ))}
    </svg>
  );
}

export function DecisionArt() {
  const reduce = useReducedMotion();
  const outer = cube(200, 200, 160);
  const layers = [120, 165, 210, 255];
  return (
    <svg viewBox="0 0 400 400" className="h-auto w-full max-w-[420px]" aria-hidden>
      <motion.path d={outer.outline} stroke={GOLD} strokeOpacity={0.4} fill="none" {...draw(0)} />
      <motion.path d={`M200,40 L200,360`} stroke={GOLD} strokeOpacity={0.2} strokeDasharray="3 5" {...draw(0.4)} />
      {layers.map((y, i) => (
        <motion.g
          key={y}
          animate={reduce ? undefined : { y: [0, -6, 0] }}
          transition={{ duration: 4, repeat: Infinity, delay: i * 0.35, ease: "easeInOut" }}
        >
          <motion.path
            d={rhombus(200, y, 90)}
            fill={i === 3 ? GOLD : EMBER}
            fillOpacity={i === 3 ? 0.18 : 0.08 + i * 0.03}
            stroke={i === 3 ? GOLD : EMBER}
            strokeWidth={1.3}
            {...draw(0.5 + i * 0.25)}
          />
          {[-1, 1].map((d) => (
            <motion.circle
              key={d}
              cx={200 + d * K * 90}
              cy={y}
              r={3}
              fill="var(--color-ink)"
              stroke={GOLD}
              initial={{ scale: 0 }}
              whileInView={{ scale: 1 }}
              viewport={{ once: true }}
              transition={{ delay: 1.2 + i * 0.2 }}
            />
          ))}
        </motion.g>
      ))}
    </svg>
  );
}

export function EvolveArt() {
  const reduce = useReducedMotion();
  const outer = cube(200, 205, 155);
  const cells = [
    [170, 150, EMBER],
    [235, 175, EMBER],
    [150, 215, GOLD],
    [215, 240, GOLD],
    [182, 290, GOLD],
  ] as const;
  return (
    <svg viewBox="0 0 400 400" className="h-auto w-full max-w-[420px]" aria-hidden>
      <motion.path d={outer.outline} stroke={GOLD} strokeOpacity={0.45} fill="none" {...draw(0)} />
      <motion.path d={outer.inner} stroke={GOLD} strokeOpacity={0.3} fill="none" {...draw(0.3)} />
      {cells.map(([x, y, c], i) => (
        <motion.path
          key={i}
          d={hexagon(x, y, 34)}
          fill={c}
          fillOpacity={0.12}
          stroke={c}
          strokeWidth={1.4}
          initial={{ pathLength: 0, opacity: 0 }}
          whileInView={{ pathLength: 1, opacity: 1 }}
          viewport={{ once: true, margin: "-80px" }}
          // fill pulses in sequence: new evidence lighting up cells of the model
          animate={reduce ? undefined : { fillOpacity: [0.08, 0.32, 0.08] }}
          transition={{
            pathLength: { duration: 1.4, delay: 0.6 + i * 0.2 },
            opacity: { duration: 0.2, delay: 0.6 + i * 0.2 },
            fillOpacity: { duration: 3, repeat: Infinity, delay: i * 0.6 },
          }}
        />
      ))}
    </svg>
  );
}
