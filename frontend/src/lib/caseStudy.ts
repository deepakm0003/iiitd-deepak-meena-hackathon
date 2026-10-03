// Recorded pipeline output for the Western Alliance 8-K of 13 Mar 2023
// (source: tests/golden/western_alliance.json in this repo). The landing page replays it; nothing here is invented.
export const WAL = {
  eventId: "evt_600c4206f3fa",
  ticker: "WAL",
  company: "Western Alliance Bancorporation",
  date: "13 Mar 2023",
  filing: "SEC 8-K · Item 7.01",
  method: "rule: bank_run",
  eventType: "Credit Event",
  subtype: "liquidity stress",
  evidence: "deposit outflows have been moderate",
  factuality: "confirmed",
  impact: 7.48,
  percentile: 95.8,
  factors: [
    { key: "S", label: "Severity", value: 0.85 },
    { key: "M", label: "Sentiment magnitude", value: 0.86 },
    { key: "Q", label: "Source credibility", value: 1.0 },
    { key: "H", label: "Historical reaction", value: 0.86 },
  ],
  contributions: [
    { label: "Severity", value: 0.2125 },
    { label: "Sentiment magnitude", value: 0.1296 },
    { label: "Historical reaction", value: 0.1295 },
    { label: "Novelty", value: 0.1 },
    { label: "Source credibility", value: 0.1 },
    { label: "Corroboration", value: 0.0214 },
    { label: "Entity importance", value: 0.0021 },
  ],
  pLargeMove: 0.4239,
  pnlByAsset: [
    { label: "Bonds", value: -1_594_467 },
    { label: "Equity", value: -903_545 },
    { label: "Corporate loans", value: -25_891 },
    { label: "Swaps", value: 39_424 },
    { label: "Index puts (hedge)", value: 294_347 },
  ],
  positions: 25,
  pnl: -2_190_132,
  ecl: 25_891,
  cet1Before: 0.12,
  cet1After: 0.1158,
} as const;

export const fmtMoney = (v: number) =>
  `${v < 0 ? "−" : "+"}$${(Math.abs(v) / 1e6).toFixed(2)}M`;

export const fmtPct = (v: number) => `${(v * 100).toFixed(2)}%`;
