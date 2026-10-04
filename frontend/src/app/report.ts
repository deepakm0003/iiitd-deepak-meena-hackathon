import type { Decision, Signal, StressRun } from "./api";
import { ASSET_LABEL, FACTOR_LABEL } from "./format";

// PDF reports for the Analyse page, drawn in the browser from the API's answer, in the website's design
// (graphite pages, brass headings, ember for risk). Tripwire does not store uploads or their results, so this
// file is the only copy the user keeps.

export interface AnalyzeResult {
  analysed_at: string;
  stored: boolean;
  input: { title: string; lead_used: string; source_type: string; url: string | null };
  annotation: {
    primary: string;
    event_type: string;
    event_subtype: string | null;
    event_method: string;
    event_confidence: number;
    sentiment: number;
    sentiment_label: string;
    frame: { factuality?: string; places?: string[] } | null;
    event_evidence: { phrase?: string; context?: string; source?: string } | null;
    entities: { ticker: string; sector: string; link_confidence: number; relevance: number; method: string; in_title: boolean }[];
    model_versions: Record<string, string | null> | null;
  };
  signal: Signal | null;
  decision: Decision | null;
  stress: StressRun | null;
  reason_no_signal: string | null;
}

export interface BatchRow {
  row: number;
  title: string;
  subject: string;
  company: string | null;
  event_type: string;
  event_subtype: string | null;
  decided_by: string;
  alert_tier: string;
  evidence: string;
  sentiment: number;
  factuality: string | null;
  impact: number | null;
  p_large_move: number | null;
  risk_level: string | null;
  stress_trigger: boolean | null;
  note: string | null;
}

type RGB = [number, number, number];
const C = {
  bg: [17, 17, 17] as RGB,
  ink2: [23, 23, 23] as RGB,
  ink3: [31, 31, 31] as RGB,
  line: [43, 43, 43] as RGB,
  bone: [237, 233, 224] as RGB,
  mute: [154, 149, 139] as RGB,
  gold: [217, 180, 108] as RGB,
  goldDim: [56, 48, 33] as RGB,
  ember: [181, 82, 58] as RGB,
  emberBright: [208, 102, 63] as RGB,
  emberDim: [52, 30, 25] as RGB,
  sage: [127, 162, 135] as RGB,
  sageDim: [33, 44, 36] as RGB,
  wordmark: [29, 29, 29] as RGB,
};
const RISK: Record<string, RGB> = { Critical: [229, 72, 77], High: C.emberBright, Medium: C.gold, Low: C.mute };

const money = (v: number) => `${v < 0 ? "-" : "+"}$${(Math.abs(v) / 1e6).toFixed(2)}M`;
const pct = (v: number, d = 2) => `${(v * 100).toFixed(d)}%`;
const ascii = (t: string) =>
  t.replace(/[“”]/g, '"').replace(/[‘’]/g, "'").replace(/[–—]/g, "-").replace(/…/g, "...").replace(/→/g, "->")
    .replace(/−/g, "-").replace(/[^\x20-\x7E\n]/g, "");
const modelName = (v: string | null) => (v ? v.split(/[\\/]/).slice(-2).join("/") : "-");

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Pdf = any;

async function canvas(kind: string, analysedAt: string) {
  const { jsPDF } = await import("jspdf");
  const { default: autoTable } = await import("jspdf-autotable");
  const doc: Pdf = new jsPDF({ unit: "pt", format: "a4" });
  const W = doc.internal.pageSize.getWidth();
  const H = doc.internal.pageSize.getHeight();
  const M = 40;
  const CW = W - 2 * M;
  const st = { y: 0 };

  const paint = () => {
    doc.setFillColor(...C.bg).rect(0, 0, W, H, "F");
  };
  const font = (size: number, color: RGB, style: "normal" | "bold" = "normal", family = "helvetica") =>
    doc.setFont(family, style).setFontSize(size).setTextColor(...color);
  const eyebrow = (text: string, x: number, y: number, color: RGB = C.gold, opts: object = {}) => {
    font(7, color, "bold");
    doc.text(ascii(text).toUpperCase(), x, y, { charSpace: 1.4, ...opts });
  };
  const header = () => {
    // pulse logo + wordmark, as on the site
    doc.setDrawColor(...C.gold).setLineWidth(1.4);
    const px = M, py = 34;
    doc.lines([[7, 0], [3, -7], [5, 14], [3, -6], [10, 0]], px, py, [1, 1], "S", false);
    font(10, C.bone, "bold");
    doc.text("TRIPWIRE", px + 36, py + 3.5, { charSpace: 2.2 });
    eyebrow(kind, W - M, py - 2, C.mute, { align: "right" });
    font(7.5, C.mute);
    doc.text(`Analysed ${new Date(analysedAt).toUTCString()}`, W - M, py + 9, { align: "right" });
    doc.setDrawColor(...C.line).setLineWidth(0.6).line(M, 54, W - M, 54);
    st.y = 76;
  };
  const newPage = () => {
    doc.addPage();
    paint();
    header();
  };
  const ensure = (h: number) => {
    if (st.y + h > H - 56) newPage();
  };
  const panel = (x: number, y: number, w: number, h: number, fill: RGB = C.ink2, stroke: RGB = C.line) => {
    doc.setFillColor(...fill).setDrawColor(...stroke).setLineWidth(0.6).roundedRect(x, y, w, h, 6, 6, "FD");
  };
  const chip = (text: string, x: number, y: number, tone: RGB, fill: RGB) => {
    font(6.5, tone, "bold");
    const t = ascii(text).toUpperCase();
    const w = doc.getTextWidth(t) + t.length * 0.8 + 10;
    doc.setFillColor(...fill).setDrawColor(...tone).setLineWidth(0.4).roundedRect(x, y - 7.5, w, 11, 2, 2, "FD");
    doc.text(t, x + 5, y, { charSpace: 0.8 });
    return w;
  };
  const wrap = (text: string, width: number, size: number) => {
    font(size, C.bone);
    return doc.splitTextToSize(ascii(text), width) as string[];
  };
  /** A heading never ends a page alone: it reserves room for `need` points of the content that follows. */
  const section = (no: string, title: string, need = 110) => {
    ensure(40 + need);
    st.y += 6;
    eyebrow(`${no} /`, M, st.y);
    font(15, C.bone);
    doc.text(ascii(title), M, st.y + 20);
    st.y += 34;
  };
  const para = (text: string, size = 9, color: RGB = C.mute) => {
    const lines = wrap(text, CW, size);
    ensure(lines.length * (size + 3.5) + 6);
    font(size, color);
    doc.text(lines, M, st.y + size);
    st.y += lines.length * (size + 3.5) + 8;
  };
  /** Label / value rows inside one panel. */
  const keyValues = (rows: [string, string][]) => {
    const lw = 118;
    const vw = CW - lw - 28;
    const heights = rows.map(([, v]) => Math.max(1, wrap(v, vw, 9).length) * 12.5 + 10);
    const h = heights.reduce((a, b) => a + b, 0) + 10;
    ensure(h);
    panel(M, st.y, CW, h);
    let y = st.y + 8;
    rows.forEach(([k, v], i) => {
      eyebrow(k, M + 14, y + 11, C.mute);
      font(9, C.bone);
      doc.text(wrap(v, vw, 9), M + 14 + lw, y + 11);
      y += heights[i];
      if (i < rows.length - 1) doc.setDrawColor(...C.line).setLineWidth(0.4).line(M + 14, y - 1, M + CW - 14, y - 1);
    });
    st.y += h + 14;
  };
  const table = (head: string[], body: (string | number)[][], widths?: Record<number, number>) => {
    ensure(40);
    autoTable(doc, {
      startY: st.y,
      head: [head.map((h) => h.toUpperCase())],
      body: body.map((r) => r.map((c) => ascii(String(c)))),
      margin: { left: M, right: M, top: 76, bottom: 56 },
      theme: "plain",
      styles: { font: "helvetica", fontSize: 8, cellPadding: { top: 5, bottom: 5, left: 8, right: 8 }, textColor: C.bone, fillColor: C.ink2, lineColor: C.line, lineWidth: { bottom: 0.4 } },
      headStyles: { textColor: C.gold, fillColor: C.ink3, fontStyle: "bold", fontSize: 6.5, lineWidth: 0 },
      columnStyles: Object.fromEntries(Object.entries(widths ?? {}).map(([k, w]) => [k, { cellWidth: w }])),
      willDrawPage: (data: { pageNumber: number }) => {
        if (data.pageNumber > 1) {
          paint();
          header();
        }
      },
    });
    st.y = doc.lastAutoTable.finalY + 16;
  };
  /** Horizontal bars, one row each: label, bar, value, optional tag. */
  const bars = (items: { label: string; value: number; max: number; color: RGB; text: string; tag?: [string, RGB, RGB] }[], diverging = false) => {
    const rowH = 17;
    const h = items.length * rowH + 20;
    ensure(h);
    panel(M, st.y, CW, h);
    const lx = M + 14;
    const bx = M + 150;
    const bw = CW - 150 - (items.some((i) => i.tag) ? 170 : 90);
    let y = st.y + 16;
    items.forEach((it) => {
      font(8, C.bone);
      doc.text(ascii(it.label), lx, y + 3);
      doc.setFillColor(...C.line).roundedRect(bx, y - 2, bw, 4, 2, 2, "F");
      const frac = Math.min(1, Math.abs(it.value) / (it.max || 1));
      doc.setFillColor(...it.color);
      if (diverging) {
        const mid = bx + bw / 2;
        doc.setDrawColor(...C.mute).setLineWidth(0.4).line(mid, y - 5, mid, y + 5);
        const w = Math.max(1.5, (bw / 2) * frac);
        doc.roundedRect(it.value < 0 ? mid - w : mid, y - 2, w, 4, 2, 2, "F");
      } else {
        doc.roundedRect(bx, y - 2, Math.max(1.5, bw * frac), 4, 2, 2, "F");
      }
      font(8, it.color === C.gold ? C.bone : it.color, "normal", "courier");
      doc.text(ascii(it.text), bx + bw + 12, y + 3);
      if (it.tag) chip(it.tag[0], bx + bw + 80, y + 3, it.tag[1], it.tag[2]);
      y += rowH;
    });
    st.y += h + 14;
  };
  const ring = (cx: number, cy: number, r: number, value: number, color: RGB) => {
    doc.setDrawColor(...C.line).setLineWidth(4).circle(cx, cy, r, "S");
    const n = Math.max(2, Math.round(64 * (value / 10)));
    const pts: [number, number][] = [];
    for (let i = 0; i <= n; i++) {
      const a = -Math.PI / 2 + (2 * Math.PI * (value / 10) * i) / n;
      pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
    }
    const segs = pts.slice(1).map((p, i) => [p[0] - pts[i][0], p[1] - pts[i][1]]);
    doc.setDrawColor(...color).setLineWidth(4).setLineCap("round");
    doc.lines(segs, pts[0][0], pts[0][1], [1, 1], "S", false);
    doc.setLineCap("butt");
  };
  const check = (x: number, y: number, ok: boolean) => {
    doc.setFillColor(...(ok ? C.sageDim : C.emberDim)).circle(x, y, 6.5, "F");
    doc.setDrawColor(...(ok ? C.sage : C.emberBright)).setLineWidth(1.3);
    if (ok) doc.lines([[2, 2], [4, -5]], x - 3, y + 0.5, [1, 1], "S", false);
    else {
      doc.line(x - 2.5, y - 2.5, x + 2.5, y + 2.5);
      doc.line(x - 2.5, y + 2.5, x + 2.5, y - 2.5);
    }
  };
  const notStored = () => {
    const text = "Not stored. Tripwire computed this with its live models and kept nothing: this PDF is the only copy. " +
      "Stress figures use the synthetic demonstration book, not a real bank's portfolio.";
    const lines = wrap(text, CW - 40, 8.5);
    const h = lines.length * 12 + 16;
    ensure(h);
    panel(M, st.y, CW, h, C.emberDim, C.ember);
    doc.setFillColor(...C.emberBright).circle(M + 16, st.y + 15, 2.5, "F");
    font(8.5, C.bone);
    doc.text(lines, M + 28, st.y + 17);
    st.y += h + 16;
  };
  const finish = (filename: string, save = true): string | void => {
    // the oversized wordmark that closes every page of the site, when the last page has room for it
    if (st.y < H - 200) {
      font(118, C.wordmark, "bold");
      doc.text("tripwire", W / 2, H - 70, { align: "center", charSpace: -4 });
    }
    const pages = doc.getNumberOfPages();
    for (let i = 1; i <= pages; i++) {
      doc.setPage(i);
      doc.setDrawColor(...C.line).setLineWidth(0.6).line(M, H - 40, W - M, H - 40);
      eyebrow("Tripwire", M, H - 26, C.mute);
      eyebrow(`Page ${i} / ${pages}`, W - M, H - 26, C.mute, { align: "right" });
    }
    if (!save) return doc.output("datauristring");
    doc.save(filename);
  };

  paint();
  header();
  return { doc, W, H, M, CW, st, font, eyebrow, panel, chip, wrap, section, para, keyValues, table, bars, ring, check, notStored, finish, ensure };
}

export async function articlePdf(r: AnalyzeResult, save = true) {
  const k = await canvas("Document analysis", r.analysed_at);
  const { doc, M, CW, st, font, eyebrow, panel, chip, wrap } = k;
  const a = r.annotation;
  const s = r.signal;

  // ---- title card: what was analysed
  const headline = wrap(r.input.title, CW - 28, 19);
  const cardH = 54 + Math.min(4, headline.length) * 23;
  panel(M, st.y, CW, cardH);
  eyebrow(`Your upload  ·  ${r.input.source_type}`, M + 14, st.y + 20);
  font(19, C.bone, "normal", "times");
  doc.text(headline.slice(0, 4), M + 14, st.y + 44);
  let cx = M + 14;
  const cy = st.y + cardH - 14;
  const subject = s?.company ? `${s.company.ticker}  ${s.company.name}` : a.primary === "MACRO" ? "Market-wide" : "No tracked subject";
  cx += k.chip(subject.slice(0, 48), cx, cy, C.bone, C.ink3) + 6;
  cx += k.chip(a.event_type, cx, cy, C.gold, C.goldDim) + 6;
  if (s) cx += k.chip(`${s.alert_tier} tier`, cx, cy, s.alert_tier === "confirmed" ? C.sage : C.mute, s.alert_tier === "confirmed" ? C.sageDim : C.ink3) + 6;
  if (a.frame?.factuality) chip(a.frame.factuality, cx, cy, C.mute, C.ink3);
  st.y += cardH + 14;
  k.notStored();

  // ---- KPI row
  if (s) {
    const gap = 10;
    const w = (CW - 3 * gap) / 4;
    const h = 74;
    k.ensure(h + 14);
    const y = st.y;
    const risk = RISK[s.risk_level] ?? C.mute;
    const cards: [string, string, string][] = [
      ["Impact", s.impact_score.toFixed(1), `${Math.round(s.impact_breakdown.percentile)}th percentile`],
      ["Risk level", s.risk_level, s.direction ?? ""],
      ["P(large move)", pct(s.p_large_move, 0), "calibrated"],
      ["Confidence", pct(s.confidence, 0), "model + links"],
    ];
    cards.forEach(([label, value, sub], i) => {
      const x = M + i * (w + gap);
      panel(x, y, w, h);
      eyebrow(label, x + 12, y + 18, C.mute);
      if (i === 0) {
        k.ring(x + w - 30, y + 40, 17, s.impact_score, s.impact_score >= 7 ? C.emberBright : s.impact_score >= 5 ? C.gold : C.mute);
        font(24, C.bone, "normal", "times");
        doc.text(value, x + 12, y + 48);
      } else {
        font(22, i === 1 ? risk : C.bone, "normal", "times");
        doc.text(value, x + 12, y + 48);
      }
      font(7.5, C.mute);
      doc.text(ascii(sub), x + 12, y + 63);
    });
    st.y += h + 18;
  }

  // ---- 01 what happened
  k.section("01", "What happened");
  const evidence = a.event_evidence?.context ? `"${a.event_evidence.context.trim()}"  (matched: ${a.event_evidence.phrase})` : "-";
  k.keyValues([
    ["Event class", `${a.event_type}${a.event_subtype ? ` / ${a.event_subtype.replace(/_/g, " ")}` : ""}`],
    ["Decided by", `${a.event_method}${s ? `   (alert tier: ${s.alert_tier})` : ""}`],
    ["Evidence", evidence],
    ["Sentiment", `${a.sentiment >= 0 ? "+" : ""}${a.sentiment.toFixed(2)} (${a.sentiment_label})`],
    ["Factuality", a.frame?.factuality ?? "-"],
    ["Text read", `${r.input.title}${r.input.lead_used ? `. ${r.input.lead_used}` : ""}`],
    ...(r.input.url ? [["Source URL", `${r.input.url} (recorded, not fetched)`] as [string, string]] : []),
  ]);

  // ---- 02 who it is about
  k.section("02", "Who it is about");
  if (a.entities.length) {
    k.table(["Company", "Sector", "Relevance", "Link confidence", "Method", "In headline"],
      a.entities.map((e) => [e.ticker, e.sector, e.relevance.toFixed(2), e.link_confidence.toFixed(2), e.method, e.in_title ? "yes" : "no"]));
  }
  k.para(a.primary === "MACRO" ? "Subject: market-wide (no single company)." : a.primary === "NONE" ? (r.reason_no_signal ?? "No subject.") : `Subject: ${s?.company?.name ?? a.primary}.`);

  if (!s) return k.finish(`tripwire-analysis-${r.analysed_at.slice(0, 10)}.pdf`, save);

  // ---- 03 impact
  k.section("03", "How important: the Impact Score", Object.keys(s.impact_breakdown.factors).length * 17 + 30);
  const contributions = s.impact_breakdown.contributions;
  const maxC = Math.max(...Object.values(contributions), 0.0001);
  k.bars(Object.keys(s.impact_breakdown.factors)
    .sort((x, y) => (contributions[y] ?? 0) - (contributions[x] ?? 0))
    .map((f) => {
      const prov = s.provenance?.factors?.[f] ?? "";
      const tone: [RGB, RGB] = prov.startsWith("MEASURED") || prov.startsWith("OBSERVED") ? [C.sage, C.sageDim] : prov.startsWith("ASSUMPTION") ? [C.gold, C.goldDim] : [C.mute, C.ink3];
      return {
        label: FACTOR_LABEL[f] ?? f,
        value: contributions[f] ?? 0,
        max: maxC,
        color: C.gold,
        text: `${s.impact_breakdown.factors[f].toFixed(2)} -> ${(contributions[f] ?? 0).toFixed(3)}`,
        tag: [prov.replace("ASSUMPTION:", "ASSUMPTION ").slice(0, 20), tone[0], tone[1]] as [string, RGB, RGB],
      };
    }));
  k.para(s.explanation);

  // ---- 04 stress decision
  if (r.decision) {
    k.section("04", "Would it launch a stress test?", 160);
    const checks = Object.entries(r.decision.checks);
    const rows = checks.map(([, c]) => wrap(c.detail, CW - 200, 8).length);
    const h = rows.reduce((x, n) => x + Math.max(26, n * 11 + 14), 0) + 44;
    k.ensure(h);
    panel(M, st.y, CW, h);
    let y = st.y + 18;
    const label: Record<string, string> = { stress_mappable: "Class has a shock definition", factual: "A fact, not talk", adverse: "Adverse", severe_enough: "Impact clears the exposure bar" };
    checks.forEach(([key, c], i) => {
      k.check(M + 22, y + 1, c.ok);
      font(9, C.bone);
      doc.text(label[key] ?? key, M + 38, y + 4);
      font(8, C.mute, "normal", "courier");
      doc.text(wrap(c.detail, CW - 200, 8), M + 190, y + 4);
      y += Math.max(26, rows[i] * 11 + 14);
    });
    const verdict = r.decision.trigger ? "Would launch an automatic stress test" : "Would not launch an automatic stress test";
    doc.setFillColor(...(r.decision.trigger ? C.emberDim : C.ink3)).roundedRect(M + 12, y - 8, CW - 24, 22, 4, 4, "F");
    font(8.5, r.decision.trigger ? C.emberBright : C.mute, "bold");
    doc.text(verdict + (r.decision.trigger ? "" : " - the run below is shown on request"), M + 22, y + 6);
    st.y += h + 14;
  }

  // ---- 05 stress test
  const run = r.stress;
  if (run) {
    k.section("05", "What it does to the book", 90);
    const gap = 10;
    const w = (CW - 2 * gap) / 3;
    k.ensure(70);
    const y0 = st.y;
    ([
      ["Stress P&L", money(run.pnl_total), `${run.n_positions_affected} positions repriced`, run.pnl_total < 0 ? C.emberBright : C.sage],
      ["CET1 ratio", `${pct(run.capital.cet1_ratio_before)} -> ${pct(run.capital.cet1_ratio_after)}`, `${Math.round((run.capital.cet1_ratio_before - run.capital.cet1_ratio_after) * 10000)} bp`, C.bone],
      ["Severity", `k = ${run.scenario.k.toFixed(2)}`, `ECL change ${money(run.ecl_change)}`, C.bone],
    ] as [string, string, string, RGB][]).forEach(([label, value, sub, color], i) => {
      const x = M + i * (w + gap);
      panel(x, y0, w, 62);
      eyebrow(label, x + 12, y0 + 17, C.mute);
      font(15, color, "normal", "times");
      doc.text(ascii(value), x + 12, y0 + 39);
      font(7.5, C.mute);
      doc.text(ascii(sub), x + 12, y0 + 53);
    });
    st.y += 76;

    const assets = Object.entries(run.pnl_by_asset_class).filter(([, v]) => v !== 0).sort((x, y) => x[1] - y[1]);
    if (assets.length) {
      eyebrow("P&L by asset class", M, st.y);
      st.y += 8;
      const maxA = Math.max(...assets.map(([, v]) => Math.abs(v)));
      k.bars(assets.map(([key, v]) => ({ label: ASSET_LABEL[key] ?? key, value: v, max: maxA, color: v < 0 ? C.emberBright : C.sage, text: money(v) })), true);
    }

    // CET1 against the floors, as on the dashboard
    k.ensure(64);
    panel(M, st.y, CW, 56);
    eyebrow("CET1 against the floors", M + 14, st.y + 16, C.mute);
    const lo = 0.06;
    const hi = Math.max(0.13, run.capital.cet1_ratio_before + 0.01);
    const sx = (v: number) => M + 24 + ((v - lo) / (hi - lo)) * (CW - 48);
    const ly = st.y + 38;
    doc.setFillColor(...C.line).roundedRect(M + 24, ly - 2, CW - 48, 4, 2, 2, "F");
    Object.entries(run.capital.floors).forEach(([name, v]) => {
      doc.setDrawColor(...C.mute).setLineWidth(0.5).line(sx(v), ly - 8, sx(v), ly + 8);
      font(6.5, C.mute);
      doc.text(`${name.toUpperCase()} ${Math.round(v * 100)}%`, sx(v), ly - 11, { align: "center" });
    });
    doc.setDrawColor(...C.bone).setLineWidth(0.6).line(sx(run.capital.cet1_ratio_before), ly - 5, sx(run.capital.cet1_ratio_before), ly + 5);
    doc.setFillColor(...C.gold).circle(sx(run.capital.cet1_ratio_after), ly, 4.5, "F");
    st.y += 70;

    k.table(["Layer", "Risk factor", "Shock", "Source"],
      Object.entries(run.scenario.layers).flatMap(([layer, shocks]) =>
        Object.entries(shocks).map(([f, sh]) => [layer, f.replace(/_/g, " "), String(sh.value), sh.source]),
      ), { 0: 58, 1: 90, 2: 56 });
    if (run.top_contributors?.length) {
      k.table(["Largest contributors", "Type", "P&L", "Why"],
        run.top_contributors.slice(0, 6).map((c) => [c.name, c.type.replace(/_/g, " "), money(c.dv), c.paths.map((x) => x.reason).join("; ")]), { 0: 150, 1: 62, 2: 58 });
    }
    if (run.sensitivity) {
      k.table(["Scenario", "Severity k", "P&L", "CET1 after"],
        (["mild", "base", "severe"] as const).filter((x) => run.sensitivity?.[x]).map((x) => {
          const v = run.sensitivity![x];
          return [x, v.k.toFixed(2), money(v.pnl_total), pct(v.cet1_ratio_after)];
        }));
    }
    if (run.reverse_stress) k.para(Object.entries(run.reverse_stress).map(([key, v]) => `${key.toUpperCase()}: ${v.note}`).join("     "));
  }

  // ---- 06 models
  k.section("06", "Models and provenance");
  k.keyValues([
    ...Object.entries(a.model_versions ?? {}).map(([key, v]) => [key.replace(/_/g, " "), modelName(v)] as [string, string]),
    ["Impact config", s.config_hash ?? "-"],
  ]);
  return k.finish(`tripwire-analysis-${r.analysed_at.slice(0, 10)}.pdf`, save);
}

export async function batchPdf(rows: BatchRow[], analysedAt: string, save = true) {
  const k = await canvas(`Batch analysis  ·  ${rows.length} items`, analysedAt);
  const { doc, M, CW, st, font, eyebrow, panel } = k;
  const signals = rows.filter((r) => r.impact !== null).length;
  const triggers = rows.filter((r) => r.stress_trigger).length;
  const types: Record<string, number> = {};
  rows.forEach((r) => (types[r.event_type] = (types[r.event_type] ?? 0) + 1));
  const top = Object.entries(types).filter(([t]) => t !== "Other").sort((a, b) => b[1] - a[1])[0];

  font(22, C.bone, "normal", "times");
  doc.text("Batch analysis", M, st.y + 18);
  st.y += 34;
  k.notStored();
  const gap = 10;
  const w = (CW - 3 * gap) / 4;
  ([
    ["Items", String(rows.length)],
    ["With a subject", String(signals)],
    ["Would trigger stress", String(triggers)],
    ["Top risk class", top ? `${top[0]} (${top[1]})` : "-"],
  ] as [string, string][]).forEach(([label, value], i) => {
    const x = M + i * (w + gap);
    panel(x, st.y, w, 58);
    eyebrow(label, x + 12, st.y + 18, C.mute);
    font(i === 3 ? 11 : 22, C.bone, "normal", "times");
    doc.text(ascii(value).slice(0, 26), x + 12, st.y + 44);
  });
  st.y += 74;
  k.section("01", "Event classes");
  const maxT = Math.max(...Object.values(types));
  k.bars(Object.entries(types).sort((a, b) => b[1] - a[1]).map(([t, n]) => ({ label: t, value: n, max: maxT, color: t === "Other" ? C.mute : C.gold, text: String(n) })));
  k.section("02", "Every item");
  k.table(["#", "Headline", "Subject", "Event", "Tier", "Sent.", "Impact", "Risk", "Stress"],
    rows.map((r) => [r.row, r.title.slice(0, 110), r.subject === "NONE" ? "-" : r.subject, r.event_type, r.alert_tier, r.sentiment.toFixed(2),
      r.impact?.toFixed(1) ?? "-", r.risk_level ?? "-", r.stress_trigger ? "yes" : "no"]),
    { 0: 22, 1: 170, 2: 44 });
  return k.finish(`tripwire-batch-${analysedAt.slice(0, 10)}.pdf`, save);
}

export interface PortfolioRun {
  event_id: string;
  headline: string;
  event_type: string;
  subject: string;
  impact: number;
  first_seen_at: string;
  pnl_total: number;
  ecl_change: number;
  cet1_ratio_before: number;
  cet1_ratio_after: number;
  n_positions_affected: number;
  pnl_by_asset_class: Record<string, number>;
  top_contributors: { name: string; type: string; dv: number; paths: { reason: string }[] }[];
  reverse_stress?: Record<string, { note: string }>;
}

export interface PortfolioResult {
  analysed_at: string;
  stored: boolean;
  portfolio: {
    totals: { tranche1_ead: number; tranche2_exposure: number };
    capital: { rwa: number; cet1: number; cet1_ratio: number; floors: { basel: number; rbi: number } };
    n_positions: { tranche1: number; tranche2: number };
    exposure_by_type: Record<string, number>;
    exposure_by_sector: Record<string, number>;
  };
  watchlist: {
    counts: Record<string, number>;
    names: { name: string; status: string; score: number; exposure: number; sector: string | null; drivers: { headline: string }[] }[];
  };
  events: { checked: number; touching_your_book: number; would_trigger: number; runs: PortfolioRun[] };
}

export async function portfolioPdf(r: PortfolioResult, save = true) {
  const k = await canvas("Portfolio analysis", r.analysed_at);
  const { doc, M, CW, st, font, eyebrow, panel } = k;
  const pf = r.portfolio;
  const total = pf.totals.tranche1_ead + pf.totals.tranche2_exposure;
  font(22, C.bone, "normal", "times");
  doc.text("Your portfolio against this week's signals", M, st.y + 18);
  st.y += 34;
  k.notStored();
  const gap = 10;
  const w = (CW - 3 * gap) / 4;
  ([
    ["Positions", String(pf.n_positions.tranche1 + pf.n_positions.tranche2)],
    ["Exposure", money(total).replace("+", "")],
    ["RWA", money(pf.capital.rwa).replace("+", "")],
    ["CET1 (12% of RWA)", money(pf.capital.cet1).replace("+", "")],
  ] as [string, string][]).forEach(([label, value], i) => {
    const x = M + i * (w + gap);
    panel(x, st.y, w, 58);
    eyebrow(label, x + 12, st.y + 18, C.mute);
    font(20, C.bone, "normal", "times");
    doc.text(value, x + 12, st.y + 44);
  });
  st.y += 74;

  k.section("01", "Where the exposure is", 120);
  const sectors = Object.entries(pf.exposure_by_sector).filter(([key]) => key !== "n/a");
  const maxS = Math.max(...sectors.map(([, v]) => v), 1);
  k.bars(sectors.map(([key, v]) => ({ label: key, value: v, max: maxS, color: C.gold, text: money(v).replace("+", "") })));

  k.section("02", "This week's live signals on your book", 90);
  k.para(`${r.events.checked} stress-mappable signals from the last 7 days were checked against your positions: ${r.events.touching_your_book} reach your book directly, through its sectors or its states, and ${r.events.would_trigger} would launch a stress test on it.`, 9, C.bone);
  if (r.events.runs.length) {
    k.table(["Signal", "Impact", "P&L", "CET1 after", "Positions hit"],
      r.events.runs.map((x) => [`${x.headline.slice(0, 90)} (${x.event_type})`, x.impact.toFixed(1), money(x.pnl_total), `${pct(x.cet1_ratio_before)} -> ${pct(x.cet1_ratio_after)}`, x.n_positions_affected]),
      { 0: 230, 1: 44, 2: 58 });
    r.events.runs.forEach((x, i) => {
      if (!x.top_contributors.length) return;
      k.table([`Run ${i + 1}: largest contributors`, "Type", "P&L", "Why"],
        x.top_contributors.map((c) => [c.name, c.type.replace(/_/g, " "), money(c.dv), c.paths.map((p) => p.reason).join("; ")]),
        { 0: 140, 1: 62, 2: 58 });
    });
  }

  k.section("03", "Early warning on your names", 90);
  const names = r.watchlist.names.filter((n) => n.status !== "Green").slice(0, 30);
  k.para(`Red ${r.watchlist.counts.Red ?? 0}, Amber ${r.watchlist.counts.Amber ?? 0}, Green ${r.watchlist.counts.Green ?? 0} (last 30 days of signals).`, 9, C.bone);
  if (names.length) {
    k.table(["Name", "Status", "Score", "Exposure", "Strongest signal"],
      names.map((n) => [n.name, n.status, Math.round(n.score * 100), money(n.exposure).replace("+", ""), n.drivers[0]?.headline.slice(0, 80) ?? "-"]),
      { 0: 90, 1: 50, 2: 40, 3: 60 });
  }
  return k.finish(`tripwire-portfolio-${r.analysed_at.slice(0, 10)}.pdf`, save);
}

export function batchCsv(rows: BatchRow[]) {
  const cols: (keyof BatchRow)[] = ["row", "title", "subject", "company", "event_type", "event_subtype", "decided_by", "alert_tier",
    "evidence", "sentiment", "factuality", "impact", "p_large_move", "risk_level", "stress_trigger", "note"];
  const esc = (v: unknown) => {
    const t = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
  };
  const csv = [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = `tripwire-batch-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

export type { Decision };
