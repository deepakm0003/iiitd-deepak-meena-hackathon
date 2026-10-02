# Improvement log

What changed, why, and what it did to the measured numbers. Test periods, targets and splits are unchanged
unless a row says otherwise.

## 2026-10-02

| Change | Reason (found on live data) | Before | After |
|---|---|---|---|
| Classifier report: macro-F1 over the classes present in validation | the report averaged 4 classes with no validation examples as F1 = 0 | 0.559 (head) | 0.879 (same predictions; 0.559 = 0.879 x 7/11) |
| Selective classification: head p >= 0.30; stress classes also need zero-shot NLI p >= 0.10 (`eval-events`, `docs/results/event_selective.json`) | every head guess became a label ("celebrity feud" -> Geopolitical at p = 0.43) | non-Other precision 0.891, recall 0.893 | 0.932, 0.748 (validation proxy) ; 2,591 live labels -> Other |
| 8-K filings classified on the press release only | training stripped headings, inference used the title ("Regulation FD" -> Regulatory/Legal) | | |
| Rule `routine_financing` -> Other | charge-off statistics, note issues, credit agreements labelled Credit Event by both models | 51 false Credit Events | 0 |
| A specific 8-K item beats a mention-level text rule (except bankruptcy/default) | bank earnings releases mentioning hurricanes became Natural Disaster (Impact 9.66) | 17 wrong | fixed |
| Item 3.01 "transfer of listing" -> Other; "pandemic" removed from the disaster rule; conditional warnings ("warns of X if Y") -> opinion; "weighed a" -> rumour | Linde listing move scored as delisting; retrospective pandemic mentions; Slok's conditional bank-run warning would have triggered a stress test | | |
| Impact: H measured on 8-K item / rule labels only; severity weight learnable only if the sample covers the severe tail (>= 30 events with S >= 0.8; observed 8) | H learned from noisy ML labels; S fitted to 0, so a real bankruptcy scored ~3.3 while every earnings release scored ~10 | OOT Spearman 0.299, AUC 0.700 | 0.332 (0.273-0.390), 0.726; severity-only baseline 0.156 -> 0.300 |
| Risk level is a downside alert: favourable items capped at Medium; `direction` field added | Microsoft earnings releases were "Critical" | | 11 High/Critical of 5,750 |
| Impact: add-one-factor ablation, PR-AUC, Brier, ECE | which factors add information? | | see table below |
| Merchant target: next-year volume vs mean of this and last year; unweighted (calibrated) logistic regression | the old target rewarded mean reversion; class weighting made scores non-probabilities | AUC 0.911 (inflated), uncalibrated | AUC 0.849, Brier 0.0185, mean 2.02% vs 2.01%; volatility-only also 0.849 |
| Stress: systemic layer only for systemic events; sector contagion to SMEs only for sector-wide regulation; exposure counts only the class's channels; Geopolitical entity/sector layers | J&J litigation bankruptcy got the SVB banking shock (P&L +$0.07M); NVIDIA export controls shocked all 300 SMEs; a macro story naming California lowered the trigger bar | | J&J -$0.42M (Pfizer bond only); NVIDIA 2 positions |
| Trigger: adverse by nature (deterministic subtype) | Western Alliance's run statement reads +0.86 | missed | triggered |
| Capital reconciliation, why-not reasons, shock source types, mild/base/severe range, `/signals/{id}/trace` | auditability | | invariants tested at k = 0, 0.3, 1, 3 |
| Watchlist: top-3 evidence, neutral weight 0.15, source credibility, geography needs scale | coverage volume looked like risk (146 Red); one local flood story put 92 CA SMEs on Red | 146 Red | 2 Red, 8 Amber |

### Impact, add-one-factor ablation (out-of-time test from 2025-07-01, n = 1,003, large-move base rate 19.2%)

| Factors | Spearman | AUC | PR-AUC | Brier | P(large) at Impact >= 7 (n) |
|---|---|---|---|---|---|
| event-type reaction H | 0.321 | 0.702 | 0.313 | 0.141 | 0.34 (401) |
| + severity prior S | 0.338 | 0.714 | 0.320 | 0.141 | 0.35 (402) |
| + sentiment magnitude M | 0.339 | 0.729 | 0.390 | 0.138 | 0.51 (45) |
| + novelty N | 0.341 | 0.726 | 0.390 | 0.139 | 0.50 (50) |
| + corroboration V | 0.342 | 0.728 | 0.395 | 0.139 | 0.50 (50) |
| + entity size E | 0.332 | 0.726 | 0.393 | 0.139 | 0.58 (50) |
| + source credibility Q (full) | 0.332 | 0.726 | 0.393 | 0.139 | 0.58 (50) |

Reading: event type carries most of the ranking; sentiment magnitude is what makes the high-Impact alerts
selective. N, V, E and Q show no measurable gain here, and this test cannot measure Q or V well: every 8-K
has the same source and is rarely corroborated. Brier 0.139 vs 0.155 for the base rate; ECE 0.033.

### Still open

- Human gold set (stratified, ~300 items weighted to Credit Event, Cyber, Natural Disaster, Product Launch).
- Large models (entity sentiment 419 MB) are not in git: publish as a release asset with a download command.
