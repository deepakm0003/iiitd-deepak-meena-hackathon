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

### Impact, add-one-factor ablation (out-of-time test from 2025-07-01)

Test set: n = 1,003 8-K events, 193 large moves (|SCAR| > 1.96), base rate 19.2%. Each row adds one factor to
the row above (expert weights, renormalised); each model gets its own percentile scale and isotonic
P(large move), fitted on the calibration period only. Source: `docs/results/impact_validation.json`.

| Factors | Spearman | AUC | PR-AUC | Brier | Large moves at Impact >= 7 | Rate (Wilson 95% CI) |
|---|---|---|---|---|---|---|
| no-skill baseline | 0 | 0.500 | 0.192 | 0.155 | n/a | 19.2% (base rate) |
| event-type reaction H | 0.321 | 0.702 | 0.313 | 0.141 | 138 / 401 | 34.4% (29.9-39.2) |
| + severity prior S | 0.338 | 0.714 | 0.320 | 0.141 | 139 / 402 | 34.6% (30.1-39.4) |
| + sentiment magnitude M | 0.339 | 0.729 | 0.390 | 0.138 | 23 / 45 | 51.1% (37.0-65.0) |
| + novelty N | 0.341 | 0.726 | 0.390 | 0.139 | 25 / 50 | 50.0% (36.6-63.4) |
| + corroboration V | 0.342 | 0.728 | 0.395 | 0.139 | 25 / 50 | 50.0% (36.6-63.4) |
| + entity size E | 0.332 | 0.726 | 0.393 | 0.139 | 29 / 50 | 58.0% (44.2-70.6) |
| + source credibility Q (full model) | 0.332 | 0.726 | 0.393 | 0.139 | 29 / 50 | 58.0% (44.2-70.6) |

Reading, without dressing it up:
- Event type carries most of the ranking (Spearman 0.321 of the full model's 0.332; AUC 0.702 of 0.726).
- Sentiment magnitude is the one added factor with a clear effect: it makes Impact >= 7 selective. Before it,
  401 of 1,003 events (40%) score >= 7 and 34% of them move; after it, 45 events score >= 7 and 51% move.
  The intervals (29.9-39.2% vs 37.0-65.0%) do not overlap, and PR-AUC rises 0.320 -> 0.390.
- Novelty, corroboration, entity size and source credibility show no measurable gain; all their changes sit
  inside the confidence intervals. This test cannot measure Q or V well: every 8-K has the same source (SEC)
  and is rarely corroborated, so the factors are nearly constant here. They stay in the model with expert
  weights (not learnable from this data, see identifiability), and are not claimed to add accuracy.
- Probability calibration of P(large move): Brier 0.139 vs 0.155 no-skill (10% skill), ECE 0.033.

## 2026-10-02 (validation round)

| Change | Reason | Before | After |
|---|---|---|---|
| Stratified gold candidates (`gold stratify`): 256 items in prediction strata (rare classes over-sampled; Credit Event and Natural Disaster taken in full) + 40 recall items (cue words, pipeline said another class); shuffled; filings shown as press-release text | 120 random candidates would give ~0 examples of rare classes; precision needs prediction strata, recall needs items the pipeline missed | 120 candidates, unlabelled | 296 candidates, unlabelled (dev 84 / test 212) |
| `eval-gold`: population precision (Wilson CI) per class from its stratum, inverse-probability-weighted recall, on-sample P/R/F1, macro/weighted F1, confusion matrix, entity / sentiment / factuality accuracy, threshold sweep on the dev split | the 7-class validation proxy has no Credit / Cyber / Disaster / Product examples | no gold metrics | ready; refuses to run until human labels exist |
| Threshold sweep (0.10-0.50 x verifier 0.05-0.30) with coverage, F1, false-positive rate; head calibration check | thresholds should be justified, not assumed | | see below |
| Golden replay test `tests/golden/test_western_alliance.py` (real 8-K, fixture from `scripts/make_golden.py`) | an NLP or scoring change must not silently break the chain to capital | none | 11 checks: entity, event, factuality, sentiment (server), Impact, trigger, shocks, PD/grade/RWA, CET1, SME reasons, recorded outputs |
| Assumption A-09 text matched to the code (staging uses PD tests and 8-K flags; the watchlist does not change stages) | register said "or EWS Red", code never did | inconsistent | consistent |
| SME score described everywhere as a proxy-event probability used for ranking, not a PD (`book.json` provenance, `/portfolio` `pd_basis`, watchlist text) | avoid presenting a transaction signal as an observed default probability | | |
| Commit guard: card-number pattern no longer matches digit runs inside hex hashes | a SHA-256 dedup key in the candidates file passed the Luhn check | false positive | real numbers still blocked (tested) |
| Impact H table written in sorted order | set iteration order made identical calibrations produce different files | noisy diffs | two runs, identical MD5 |

### Event thresholds on the validation proxy (7 classes, n = 878; `docs/results/event_selective.json`)

| Policy | Coverage | Precision | Recall | F1 | False-positive rate |
|---|---|---|---|---|---|
| no threshold | 0.857 | 0.891 | 0.893 | 0.892 | 0.211 |
| head p >= 0.30 | 0.775 | 0.922 | 0.836 | 0.877 | 0.125 |
| head p >= 0.30 + zero-shot p >= 0.10 (current) | 0.686 | 0.932 | 0.748 | 0.830 | 0.125 |
| head p >= 0.40 | 0.653 | 0.958 | 0.732 | 0.830 | 0.063 |

Findings:
- The head's probabilities are poorly calibrated: ECE 0.32; a fitted temperature of 0.4 (the head is
  under-confident) brings ECE to 0.036. A raw 0.30 therefore means a higher chance of being right than 30%.
- The 0.30 head threshold is kept as an operating point: it cuts false positives by 41% for a 6-point recall cost.
- The zero-shot verifier is not supported by this data: it removes no false positives here and costs 9 points of
  recall for 1 point of precision. Its value on noisy live web pages was observed qualitatively, not measured.
- Nothing is changed on this proxy (tweets, out of domain). Both the verifier and temperature scaling are decided
  on the gold dev split, in domain; `eval-gold` sweeps both.

### Still open

- Human labels for the 296 gold candidates (then `eval-gold`).
- Verifier keep/drop and probability calibration, on the gold dev split.
- Some filing texts lost curly quotes when decoded (shown as U+FFFD); fixing needs a re-fetch of those filings.
- Large models (entity sentiment 418 MB, SetFit 87 MB) are not in git: publish as release assets with a download
  command.
