import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Briefcase, Download, FileText, Loader2, RotateCcw, ScanSearch, Table2, Upload } from "lucide-react";
import { Link } from "react-router-dom";
import { api, useApi, type Trace } from "../api";
import { ASSET_LABEL, RISK_STYLE, SHORT_TYPE, TYPE_COLOR, money, pct, signedMoney } from "../format";
import { articlePdf, batchCsv, batchPdf, portfolioPdf, type AnalyzeResult, type BatchRow, type PortfolioResult } from "../report";
import { Bar, PageHeader, Panel, Tag, TypeChip } from "../ui";
import { TraceView } from "./SignalDetail";

interface Status {
  ready: boolean;
  max_batch: number;
  reads: string;
}

const SOURCE_TYPES = [
  ["news", "News article"],
  ["filing", "Company filing / press release"],
  ["regulator", "Regulator or central bank"],
  ["social", "Social post"],
] as const;

export default function Analyze() {
  const [tab, setTab] = useState<"article" | "batch" | "portfolio">("article");
  const [article, setArticle] = useState<AnalyzeResult>();
  const [batch, setBatch] = useState<{ rows: BatchRow[]; at: string }>();
  const [book, setBook] = useState<PortfolioResult>();
  const status = useApi<Status>("/analyze/status", article || batch ? undefined : 8000);
  const hasResults = Boolean(article || batch || book);

  // results live only in this page: warn before a refresh or tab close throws them away
  useEffect(() => {
    if (!hasResults) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [hasResults]);

  return (
    <>
      <PageHeader
        eyebrow="Analyse · processed in memory, nothing is stored"
        title="Analyse your own text"
        right={<ModelStatus status={status.data} error={status.error} />}
      />

      <div className="mb-6 flex items-start gap-3 rounded-xl border border-ember/40 bg-ember/10 px-5 py-4 text-sm">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-ember-bright" />
        <div className="text-bone/90">
          <strong className="text-bone">We do not save uploads or their results.</strong> They are computed by the live
          Tripwire models when you press Analyse and exist only on this page. Download the PDF before you leave, refresh
          or analyse something else: after that they are gone. Use public or synthetic text only, never confidential
          client data.
        </div>
      </div>

      <div className="mb-6 inline-flex rounded-lg border border-line bg-ink-2 p-1 text-sm">
        {(
          [
            ["article", "Article or filing", FileText],
            ["batch", "Batch of headlines", Table2],
            ["portfolio", "Your portfolio", Briefcase],
          ] as const
        ).map(([key, label, Icon]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`relative inline-flex items-center gap-2 rounded-md px-4 py-2 transition-colors ${tab === key ? "text-ink" : "text-mute hover:text-bone"}`}
          >
            {tab === key && <motion.span layoutId="analyze-tab" className="absolute inset-0 rounded-md bg-gold" transition={{ type: "spring", stiffness: 400, damping: 34 }} />}
            <Icon className="relative h-4 w-4" />
            <span className="relative">{label}</span>
          </button>
        ))}
      </div>

      {tab === "article" && (
        <ArticleTab result={article} setResult={setArticle} ready={status.data?.ready ?? false} reads={status.data?.reads} />
      )}
      {tab === "batch" && (
        <BatchTab result={batch} setResult={setBatch} max={status.data?.max_batch ?? 300} ready={status.data?.ready ?? false} />
      )}
      {tab === "portfolio" && <PortfolioTab result={book} setResult={setBook} />}
    </>
  );
}

function ModelStatus({ status, error }: { status?: Status; error?: string }) {
  const ready = status?.ready;
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-line bg-ink-2 px-3 py-1.5 text-xs">
      <span className={`h-2 w-2 rounded-full ${error ? "bg-ember-bright" : ready ? "bg-sage" : "animate-pulse bg-gold"}`} />
      {error ? "Engine unreachable" : ready ? "Models loaded" : "Loading models (about a minute after a restart)…"}
    </span>
  );
}

// ---------------------------------------------------------------------------------------------- article
function ArticleTab({ result, setResult, ready, reads }: {
  result?: AnalyzeResult;
  setResult: (r?: AnalyzeResult) => void;
  ready: boolean;
  reads?: string;
}) {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [sourceType, setSourceType] = useState("news");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();
  const [fileNote, setFileNote] = useState<string>();
  const [pdfBusy, setPdfBusy] = useState(false);

  const onFile = async (f: File) => {
    setErr(undefined);
    setFileNote(undefined);
    try {
      const body = f.name.toLowerCase().endsWith(".pdf") ? await pdfText(f) : await f.text();
      const lines = body.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
      if (!lines.length) throw new Error("no readable text in the file");
      setTitle(lines[0].slice(0, 400));
      setText(lines.slice(1).join("\n"));
      setFileNote(`Read ${f.name} in your browser: ${body.length.toLocaleString()} characters. The first line is used as the headline; edit it if needed.`);
    } catch (e) {
      setErr(`Could not read ${f.name}: ${(e as Error).message}`);
    }
  };

  const run = async () => {
    setBusy(true);
    setErr(undefined);
    try {
      setResult(await api<AnalyzeResult>("/analyze/text", {
        method: "POST",
        body: JSON.stringify({ title, text, source_type: sourceType, url: url.trim() || null }),
      }));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const download = async () => {
    if (!result) return;
    setPdfBusy(true);
    try {
      await articlePdf(result);
    } finally {
      setPdfBusy(false);
    }
  };

  const field = "w-full rounded-md border border-line bg-ink-3 px-3 py-2 text-sm text-bone placeholder:text-mute/60 focus:border-gold/50 focus:outline-none";

  if (result) {
    return (
      <>
        <ResultBar
          onDownload={download}
          busy={pdfBusy}
          onReset={() => {
            if (window.confirm("Discard this result? It is not saved anywhere. Download the PDF first if you need it.")) setResult(undefined);
          }}
        />
        {result.signal ? (
          <TraceView
            trace={toTrace(result)}
            signal={result.signal}
            run={result.stress ?? undefined}
            aside={
              <div className="rounded-xl border border-gold/30 bg-gold/5 p-5 text-xs leading-relaxed text-mute">
                <p className="text-sm text-bone">Your upload</p>
                <p className="mt-2">Source type {result.input.source_type}. Novelty is measured against the last 7 days of collected items; corroboration is one source by definition. The stress run uses the synthetic demonstration book.</p>
              </div>
            }
          />
        ) : (
          <NoSignal result={result} />
        )}
      </>
    );
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
      <Panel title="Your text" sub={reads ? `The classifier reads the ${reads}.` : undefined}>
        <div className="space-y-4">
          <DropZone accept=".txt,.md,.pdf,.html,.htm" label="Drop a .txt, .md or .pdf file, or click to choose" onFile={onFile} />
          {fileNote && <p className="text-xs text-sage">{fileNote}</p>}
          <label className="block text-xs text-mute">
            Headline
            <input className={`${field} mt-1`} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Regional lender halts withdrawals after deposit run" />
          </label>
          <label className="block text-xs text-mute">
            Article or press-release text
            <textarea className={`${field} mt-1 h-48 resize-y`} value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste the article body here (optional)" />
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-xs text-mute">
              Source type (sets the credibility factor)
              <select className={`${field} mt-1`} value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
                {SOURCE_TYPES.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs text-mute">
              Source URL (optional, recorded only, never fetched)
              <input className={`${field} mt-1`} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" />
            </label>
          </div>
          <button
            onClick={run}
            disabled={busy || (!title.trim() && !text.trim())}
            className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-ember px-4 py-2.5 text-sm font-medium text-cream transition-colors hover:bg-ember-bright disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ScanSearch className="h-4 w-4" />}
            {busy ? (ready ? "Running the models…" : "Loading the models, then running…") : "Analyse with the live models"}
          </button>
          {err && <p className="font-mono text-xs text-ember-bright">{err}</p>}
        </div>
      </Panel>
      <Panel title="What you get">
        <ul className="space-y-2.5 text-sm text-mute">
          {[
            "The company it is about, or market-wide",
            "Event class, with the exact sentence that decided it",
            "Sentiment and whether it is fact, rumour or opinion",
            "Impact 1-10 with all seven factors",
            "Whether it would trigger a stress test, check by check",
            "For stress-mappable events: P&L, ECL, RWA and CET1 on the book",
            "A PDF report to keep (we keep nothing)",
          ].map((t) => (
            <li key={t} className="flex gap-2">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-gold" />
              {t}
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

function ResultBar({ onDownload, busy, onReset }: { onDownload: () => void; busy: boolean; onReset: () => void }) {
  return (
    <div className="sticky top-16 z-10 -mx-4 mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-line bg-[#0e0e0e]/90 px-4 py-3 backdrop-blur sm:-mx-8 sm:px-8">
      <span className="flex items-center gap-2 text-sm text-ember-bright">
        <AlertTriangle className="h-4 w-4" /> Not saved. Download it now if you want to keep it.
      </span>
      <div className="flex gap-2">
        <button onClick={onReset} className="inline-flex items-center gap-2 rounded-md border border-line px-3 py-2 text-sm text-mute hover:border-gold/50 hover:text-bone">
          <RotateCcw className="h-4 w-4" /> Analyse another
        </button>
        <button onClick={onDownload} disabled={busy} className="inline-flex items-center gap-2 rounded-md bg-gold px-4 py-2 text-sm font-medium text-ink hover:bg-bone disabled:opacity-60">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />} Download PDF
        </button>
      </div>
    </div>
  );
}

function NoSignal({ result }: { result: AnalyzeResult }) {
  const a = result.annotation;
  return (
    <Panel title="No signal from this text" sub={result.reason_no_signal ?? undefined}>
      <div className="grid gap-4 text-sm sm:grid-cols-3">
        <div>
          <div className="text-xs text-mute">Event class</div>
          <div className="mt-1 text-bone">{a.event_type}</div>
          <div className="font-mono text-[11px] text-mute">{a.event_method}</div>
        </div>
        <div>
          <div className="text-xs text-mute">Sentiment</div>
          <div className="mt-1 font-mono text-bone">{a.sentiment >= 0 ? "+" : ""}{a.sentiment.toFixed(2)}</div>
        </div>
        <div>
          <div className="text-xs text-mute">Companies found</div>
          <div className="mt-1 text-bone">{a.entities.length ? a.entities.map((e) => `${e.ticker} (relevance ${e.relevance.toFixed(2)})`).join(", ") : "none of the tracked companies"}</div>
        </div>
      </div>
      <p className="mt-4 text-xs text-mute">The text the classifier read: “{result.input.title}{result.input.lead_used ? `. ${result.input.lead_used}` : ""}”</p>
    </Panel>
  );
}

function toTrace(r: AnalyzeResult): Trace {
  const s = r.signal!;
  return {
    event_id: s.event_id,
    what_happened: {
      headline: s.headline,
      first_seen_at: s.first_seen_at,
      entity: s.primary_entity,
      company: s.company,
      event_type: s.event_type,
      event_subtype: s.event_subtype,
      event_method: s.event_method,
      factuality: s.factuality,
      sentiment_score: s.sentiment_score,
      direction: s.direction,
      corroboration: s.corroboration,
      documents: s.documents,
      evidence: s.evidence,
      event_evidence: s.event_evidence,
    },
    how_important: {
      impact_score: s.impact_score,
      p_large_move: s.p_large_move,
      confidence: s.confidence,
      risk_level: s.risk_level,
      percentile: s.impact_breakdown.percentile,
      factors: s.impact_breakdown.factors,
      contributions: s.impact_breakdown.contributions,
      explanation: s.explanation,
      provenance: s.provenance,
    },
    why_it_matters_to_this_book: r.decision,
    stress_available: Boolean(r.stress),
  };
}

// ---------------------------------------------------------------------------------------------- batch
function BatchTab({ result, setResult, max, ready }: {
  result?: { rows: BatchRow[]; at: string };
  setResult: (r?: { rows: BatchRow[]; at: string }) => void;
  max: number;
  ready: boolean;
}) {
  const [items, setItems] = useState<{ title: string; text: string }[]>([]);
  const [paste, setPaste] = useState("");
  const [sourceType, setSourceType] = useState("news");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();
  const [note, setNote] = useState<string>();
  const [pdfBusy, setPdfBusy] = useState(false);

  const fromPaste = (t: string) => t.split(/\r?\n/).map((l) => l.trim()).filter(Boolean).map((title) => ({ title, text: "" }));

  const onFile = async (f: File) => {
    setErr(undefined);
    try {
      const rows = parseCsv(await f.text());
      if (!rows.length) throw new Error("empty file");
      const header = rows[0].map((h) => h.trim().toLowerCase());
      const ti = header.findIndex((h) => ["headline", "title"].includes(h));
      const xi = header.findIndex((h) => ["text", "body", "content", "lead"].includes(h));
      const data = ti >= 0 || xi >= 0 ? rows.slice(1) : rows; // no header: first column is the headline
      const parsed = data
        .map((r) => ({ title: (ti >= 0 ? r[ti] : r[0]) ?? "", text: (xi >= 0 ? r[xi] : "") ?? "" }))
        .filter((r) => r.title.trim() || r.text.trim());
      if (parsed.length > max) throw new Error(`${parsed.length} rows; the limit is ${max} per batch`);
      setItems(parsed);
      setPaste("");
      setNote(`Read ${parsed.length} rows from ${f.name} in your browser${ti < 0 && xi < 0 ? " (no header row found: first column used as the headline)" : ""}.`);
    } catch (e) {
      setErr(`Could not read ${f.name}: ${(e as Error).message}`);
    }
  };

  const toSend = items.length ? items : fromPaste(paste);

  const run = async () => {
    setBusy(true);
    setErr(undefined);
    try {
      const r = await api<{ rows: BatchRow[] }>("/analyze/batch", { method: "POST", body: JSON.stringify({ items: toSend, source_type: sourceType }) });
      setResult({ rows: r.rows, at: new Date().toISOString() });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    const signals = result.rows.filter((r) => r.impact !== null).length;
    const triggers = result.rows.filter((r) => r.stress_trigger).length;
    return (
      <>
        <div className="sticky top-16 z-10 -mx-4 mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-line bg-[#0e0e0e]/90 px-4 py-3 backdrop-blur sm:-mx-8 sm:px-8">
          <span className="flex items-center gap-2 text-sm text-ember-bright">
            <AlertTriangle className="h-4 w-4" /> Not saved. Download it now if you want to keep it.
          </span>
          <div className="flex gap-2">
            <button onClick={() => window.confirm("Discard these results? They are not saved anywhere.") && setResult(undefined)} className="inline-flex items-center gap-2 rounded-md border border-line px-3 py-2 text-sm text-mute hover:border-gold/50 hover:text-bone">
              <RotateCcw className="h-4 w-4" /> New batch
            </button>
            <button onClick={() => batchCsv(result.rows)} className="inline-flex items-center gap-2 rounded-md border border-gold/50 px-3 py-2 text-sm text-gold hover:bg-gold/10">
              <Download className="h-4 w-4" /> CSV
            </button>
            <button
              onClick={async () => {
                setPdfBusy(true);
                try {
                  await batchPdf(result.rows, result.at);
                } finally {
                  setPdfBusy(false);
                }
              }}
              className="inline-flex items-center gap-2 rounded-md bg-gold px-4 py-2 text-sm font-medium text-ink hover:bg-bone"
            >
              {pdfBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />} Download PDF
            </button>
          </div>
        </div>
        <div className="mb-4 flex flex-wrap gap-6 text-sm text-mute">
          <span><span className="font-serif text-2xl text-bone">{result.rows.length}</span> items</span>
          <span><span className="font-serif text-2xl text-bone">{signals}</span> with a subject (signals)</span>
          <span><span className="font-serif text-2xl text-bone">{triggers}</span> would launch a stress test</span>
        </div>
        <div className="overflow-x-auto rounded-xl border border-line bg-ink-2">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-xs text-mute">
              <tr>
                {["#", "Headline", "Subject", "Event", "Evidence", "Sentiment", "Impact", "Risk", "Stress"].map((h) => (
                  <th key={h} className="px-3 py-2.5 font-normal">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {result.rows.map((r) => (
                <motion.tr key={r.row} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: Math.min(r.row, 30) * 0.015 }} className="align-top">
                  <td className="px-3 py-2.5 font-mono text-xs text-mute">{r.row}</td>
                  <td className="max-w-[380px] px-3 py-2.5 text-bone">{r.title}</td>
                  <td className="px-3 py-2.5"><Tag>{r.subject === "NONE" ? "none" : r.subject}</Tag></td>
                  <td className="px-3 py-2.5 whitespace-nowrap">
                    <TypeChip type={r.event_type} />
                    {r.alert_tier === "confirmed" && <span className="ml-1"><Tag tone="sage">confirmed</Tag></span>}
                  </td>
                  <td className="max-w-[200px] px-3 py-2.5 text-xs text-mute">{r.evidence}</td>
                  <td className={`px-3 py-2.5 font-mono text-xs ${r.sentiment > 0.15 ? "text-sage" : r.sentiment < -0.15 ? "text-ember-bright" : "text-bone"}`}>{r.sentiment >= 0 ? "+" : ""}{r.sentiment.toFixed(2)}</td>
                  <td className="px-3 py-2.5 font-mono text-bone">{r.impact?.toFixed(1) ?? "—"}</td>
                  <td className="px-3 py-2.5">
                    {r.risk_level ? <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase ${RISK_STYLE[r.risk_level]?.chip}`}>{r.risk_level}</span> : <span className="text-xs text-mute">—</span>}
                  </td>
                  <td className="px-3 py-2.5 text-xs">{r.stress_trigger ? <span className="text-ember-bright">yes</span> : <span className="text-mute">no</span>}</td>
                </motion.tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-mute">Batch rows are classified and scored; open a single item in the Article tab to see its full stress run.</p>
      </>
    );
  }

  const types = Object.keys(TYPE_COLOR).filter((t) => t !== "Other").slice(0, 6);
  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
      <Panel title="Your headlines" sub={`Up to ${max} per batch. A CSV with a "headline" (or "title") column and an optional "text" column, or one headline per line.`}>
        <div className="space-y-4">
          <DropZone accept=".csv,.txt" label="Drop a .csv file, or click to choose" onFile={onFile} />
          {note && (
            <p className="flex items-center justify-between text-xs text-sage">
              {note}
              <button className="text-mute hover:text-bone" onClick={() => { setItems([]); setNote(undefined); }}>clear</button>
            </p>
          )}
          {!items.length && (
            <label className="block text-xs text-mute">
              Or paste headlines, one per line
              <textarea
                className="mt-1 h-48 w-full resize-y rounded-md border border-line bg-ink-3 px-3 py-2 text-sm text-bone placeholder:text-mute/60 focus:border-gold/50 focus:outline-none"
                value={paste}
                onChange={(e) => setPaste(e.target.value)}
                placeholder={"Fed holds rates steady, signals two cuts this year\nCrowdStrike outage grounds airlines worldwide"}
              />
            </label>
          )}
          <label className="block text-xs text-mute">
            Source type for all rows
            <select className="mt-1 w-full rounded-md border border-line bg-ink-3 px-3 py-2 text-sm text-bone focus:border-gold/50 focus:outline-none" value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
              {SOURCE_TYPES.map(([v, l]) => (
                <option key={v} value={v}>{l}</option>
              ))}
            </select>
          </label>
          <button
            onClick={run}
            disabled={busy || !toSend.length || toSend.length > max}
            className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-ember px-4 py-2.5 text-sm font-medium text-cream transition-colors hover:bg-ember-bright disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ScanSearch className="h-4 w-4" />}
            {busy ? (ready ? `Scoring ${toSend.length} items…` : "Loading the models, then scoring…") : `Analyse ${toSend.length || ""} item${toSend.length === 1 ? "" : "s"}`}
          </button>
          {toSend.length > max && <p className="text-xs text-ember-bright">{toSend.length} items: the limit is {max}.</p>}
          {err && <p className="font-mono text-xs text-ember-bright">{err}</p>}
        </div>
      </Panel>
      <Panel title="Each row gets">
        <ul className="space-y-2.5 text-sm text-mute">
          {["Subject: company ticker, market-wide or none", "Event class and alert tier", "The evidence phrase", "Sentiment and factuality", "Impact and risk level", "Whether it would launch a stress test"].map((t) => (
            <li key={t} className="flex gap-2"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-gold" />{t}</li>
          ))}
        </ul>
        <div className="mt-5 flex flex-wrap gap-1.5">
          {types.map((t) => (
            <span key={t} className="inline-flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-[10px] text-mute">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: TYPE_COLOR[t] }} /> {SHORT_TYPE[t] ?? t}
            </span>
          ))}
        </div>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------- portfolio
// A synthetic example: public tickers from the tracked universe and made-up small businesses. Never real client data.
const TEMPLATE = [
  "type,issuer,exposure,grade,sector,state,maturity_years,coupon",
  "loan,JPM,5000000,A,,,4,",
  "loan,WAL,3000000,BB,,,3,",
  "loan,TSLA,4000000,BB,,,5,",
  "bond,BAC,4000000,BBB,,,7,",
  "bond,XOM,2500000,AA,,,6,0.045",
  "equity,NVDA,1500000,,,,,",
  "equity,AAPL,1000000,,,,,",
  "sme_loan,Harbor Diner LLC,250000,BB,Consumer Discretionary,CA,3,",
  "sme_loan,Gulf Coast Supply Co,400000,B,Industrials,TX,4,",
].join("\n");

function PortfolioTab({ result, setResult }: { result?: PortfolioResult; setResult: (r?: PortfolioResult) => void }) {
  const [rows, setRows] = useState<Record<string, string>[]>([]);
  const [note, setNote] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();
  const [pdfBusy, setPdfBusy] = useState(false);

  const load = (text: string, name: string) => {
    const table = parseCsv(text);
    if (table.length < 2) throw new Error("need a header row and at least one position");
    const header = table[0].map((h) => h.trim().toLowerCase());
    if (!header.includes("type") || !header.includes("issuer") || !header.includes("exposure")) {
      throw new Error("the header must include type, issuer and exposure (download the template)");
    }
    const parsed = table.slice(1).map((r) => Object.fromEntries(header.map((h, i) => [h, (r[i] ?? "").trim()])));
    setRows(parsed);
    setNote(`Read ${parsed.length} positions from ${name} in your browser.`);
  };

  const onFile = async (f: File) => {
    setErr(undefined);
    try {
      load(await f.text(), f.name);
    } catch (e) {
      setErr(`Could not read ${f.name}: ${(e as Error).message}`);
    }
  };

  const template = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([TEMPLATE], { type: "text/csv" }));
    a.download = "tripwire-portfolio-template.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const run = async () => {
    setBusy(true);
    setErr(undefined);
    try {
      setResult(await api<PortfolioResult>("/analyze/portfolio", { method: "POST", body: JSON.stringify({ rows }) }));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    const pf = result.portfolio;
    const total = pf.totals.tranche1_ead + pf.totals.tranche2_exposure;
    const sectors = Object.entries(pf.exposure_by_sector).filter(([k]) => k !== "n/a");
    const names = result.watchlist.names.filter((n) => n.status !== "Green");
    return (
      <>
        <ResultBar
          busy={pdfBusy}
          onDownload={async () => {
            setPdfBusy(true);
            try {
              await portfolioPdf(result);
            } finally {
              setPdfBusy(false);
            }
          }}
          onReset={() => {
            if (window.confirm("Discard this result? It is not saved anywhere.")) setResult(undefined);
          }}
        />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[
            ["Positions", String(pf.n_positions.tranche1 + pf.n_positions.tranche2)],
            ["Exposure", money(total)],
            ["Risk-weighted assets", money(pf.capital.rwa)],
            ["CET1 (12% of RWA, A-21)", money(pf.capital.cet1)],
          ].map(([l, v]) => (
            <div key={l} className="rounded-xl border border-line bg-ink-2 p-5">
              <div className="text-sm text-mute">{l}</div>
              <div className="mt-2 font-serif text-3xl text-bone">{v}</div>
            </div>
          ))}
        </div>
        <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_1.4fr]">
          <Panel title="Where the exposure is" sub="By sector">
            <ul className="space-y-3">
              {sectors.map(([k, v], i) => (
                <li key={k} className="grid grid-cols-[150px_1fr_64px] items-center gap-3 text-xs">
                  <span className="truncate text-bone/80">{k}</span>
                  <Bar value={v} max={sectors[0][1]} delay={i * 0.04} />
                  <span className="text-right font-mono text-mute">{money(v, 1)}</span>
                </li>
              ))}
            </ul>
          </Panel>
          <Panel
            title="This week's live signals on your book"
            sub={`${result.events.checked} stress-mappable signals checked · ${result.events.touching_your_book} reach your book · ${result.events.would_trigger} would trigger a stress test`}
          >
            {result.events.runs.length === 0 ? (
              <p className="text-sm text-mute">None of this week's signals would launch a stress test on these positions.</p>
            ) : (
              <ul className="space-y-3">
                {result.events.runs.map((x) => (
                  <li key={x.event_id} className="rounded-lg border border-line bg-ink-3/60 p-4">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-mute">
                      <TypeChip type={x.event_type} />
                      <span>Impact {x.impact.toFixed(1)}</span>
                      <Link to={`/app/signals/${x.event_id}`} className="text-gold hover:underline">
                        open signal
                      </Link>
                    </div>
                    <p className="mt-2 text-sm text-bone">{x.headline}</p>
                    <div className="mt-3 grid grid-cols-3 gap-3 text-xs">
                      <div>
                        <div className="text-mute">P&amp;L</div>
                        <div className={`font-mono ${x.pnl_total < 0 ? "text-ember-bright" : "text-sage"}`}>{signedMoney(x.pnl_total)}</div>
                      </div>
                      <div>
                        <div className="text-mute">CET1</div>
                        <div className="font-mono text-bone">
                          {pct(x.cet1_ratio_before)} → {pct(x.cet1_ratio_after)}
                        </div>
                      </div>
                      <div>
                        <div className="text-mute">Positions hit</div>
                        <div className="font-mono text-bone">{x.n_positions_affected}</div>
                      </div>
                    </div>
                    {x.top_contributors[0] && (
                      <p className="mt-2 text-xs text-mute">
                        Largest: <span className="text-bone">{x.top_contributors[0].name}</span> {signedMoney(x.top_contributors[0].dv)} ·{" "}
                        {Object.entries(x.pnl_by_asset_class)
                          .filter(([, v]) => v !== 0)
                          .map(([k, v]) => `${ASSET_LABEL[k] ?? k} ${signedMoney(v)}`)
                          .join(", ")}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
        <Panel
          className="mt-6"
          title="Early warning on your names"
          sub={`Red ${result.watchlist.counts.Red ?? 0} · Amber ${result.watchlist.counts.Amber ?? 0} · Green ${result.watchlist.counts.Green ?? 0} (last 30 days of signals)`}
        >
          {names.length === 0 ? (
            <p className="text-sm text-mute">All your names are Green.</p>
          ) : (
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-mute">
                <tr>
                  {["Name", "Status", "Score", "Exposure", "Strongest signal"].map((h) => (
                    <th key={h} className="pb-2 font-normal">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {names.map((n) => (
                  <tr key={n.name}>
                    <td className="py-2 text-bone">{n.name}</td>
                    <td className="py-2">
                      <Tag tone={n.status === "Red" ? "ember" : "gold"}>{n.status}</Tag>
                    </td>
                    <td className="py-2 font-mono text-bone">{Math.round(n.score * 100)}</td>
                    <td className="py-2 font-mono text-mute">{money(n.exposure)}</td>
                    <td className="py-2 text-xs text-mute">{n.drivers[0]?.headline ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </>
    );
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
      <Panel
        title="Your positions"
        sub="CSV with type, issuer, exposure and optional grade, sector, state, maturity_years, coupon. Up to 500 positions."
        right={
          <button onClick={template} className="inline-flex items-center gap-1.5 rounded-md border border-gold/40 px-3 py-1.5 text-xs text-gold hover:bg-gold/10">
            <Download className="h-3.5 w-3.5" /> Template
          </button>
        }
      >
        <div className="space-y-4">
          <DropZone accept=".csv,.txt" label="Drop your portfolio .csv, or click to choose" onFile={onFile} />
          {note && <p className="text-xs text-sage">{note}</p>}
          {!rows.length && (
            <button onClick={() => load(TEMPLATE, "the synthetic example")} className="text-xs text-gold hover:underline">
              Or try the synthetic example portfolio
            </button>
          )}
          {rows.length > 0 && (
            <div className="max-h-56 overflow-auto rounded-lg border border-line">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 bg-ink-3 text-mute">
                  <tr>
                    {["type", "issuer", "exposure", "grade", "sector", "state"].map((h) => (
                      <th key={h} className="px-3 py-1.5 font-normal">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {rows.slice(0, 50).map((r, i) => (
                    <tr key={i}>
                      {["type", "issuer", "exposure", "grade", "sector", "state"].map((h) => (
                        <td key={h} className="px-3 py-1.5 text-bone/80">
                          {r[h]}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <button
            onClick={run}
            disabled={busy || !rows.length}
            className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-ember px-4 py-2.5 text-sm font-medium text-cream transition-colors hover:bg-ember-bright disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ScanSearch className="h-4 w-4" />}
            {busy ? "Running this week's signals against your book…" : `Analyse ${rows.length || ""} position${rows.length === 1 ? "" : "s"}`}
          </button>
          {err && <p className="font-mono text-xs text-ember-bright">{err}</p>}
        </div>
      </Panel>
      <Panel title="What you get">
        <ul className="space-y-2.5 text-sm text-mute">
          {[
            "Your exposure by sector, RWA and starting CET1",
            "Which of this week's live signals reach your positions",
            "Which would launch a stress test on your book",
            "P&L, ECL and CET1 for the most important of them",
            "A Red / Amber / Green early-warning list of your names",
            "A PDF report to keep (we keep nothing)",
          ].map((t) => (
            <li key={t} className="flex gap-2">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-gold" />
              {t}
            </li>
          ))}
        </ul>
        <p className="mt-5 text-xs text-mute">
          PD and risk weight come from the grade; bonds are priced off today's 10-year yield plus the grade spread, as for the
          demonstration book.
        </p>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------- helpers
function DropZone({ accept, label, onFile }: { accept: string; label: string; onFile: (f: File) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div
      onClick={() => input.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const f = e.dataTransfer.files[0];
        if (f) onFile(f);
      }}
      className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-4 py-7 text-center text-sm transition-colors ${over ? "border-gold bg-gold/5 text-gold" : "border-line text-mute hover:border-gold/50 hover:text-bone"}`}
    >
      <AnimatePresence mode="wait">
        <motion.span key={String(over)} initial={{ y: 4, opacity: 0 }} animate={{ y: 0, opacity: 1 }}>
          <Upload className="h-5 w-5" />
        </motion.span>
      </AnimatePresence>
      {label}
      <span className="text-[11px] text-mute/70">Read in your browser. Only the text is sent to the engine.</span>
      <input
        ref={input}
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
    </div>
  );
}

async function pdfText(f: File): Promise<string> {
  const pdfjs = await import("pdfjs-dist");
  const worker = await import("pdfjs-dist/build/pdf.worker.min.mjs?url");
  pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
  const doc = await pdfjs.getDocument({ data: await f.arrayBuffer() }).promise;
  const pages: string[] = [];
  for (let i = 1; i <= Math.min(doc.numPages, 20); i++) {
    const page = await doc.getPage(i);
    const content = await page.getTextContent();
    let line = "";
    const lines: string[] = [];
    for (const item of content.items as { str: string; hasEOL?: boolean }[]) {
      line += item.str;
      if (item.hasEOL) {
        lines.push(line);
        line = "";
      }
    }
    if (line) lines.push(line);
    pages.push(lines.join("\n"));
  }
  return pages.join("\n");
}

/** Minimal RFC 4180 CSV parser (quoted fields, escaped quotes, CRLF). */
function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (c === '"') quoted = false;
      else cell += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") {
      row.push(cell);
      cell = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(cell);
      if (row.some((x) => x.trim())) rows.push(row);
      row = [];
      cell = "";
    } else cell += c;
  }
  row.push(cell);
  if (row.some((x) => x.trim())) rows.push(row);
  return rows;
}
