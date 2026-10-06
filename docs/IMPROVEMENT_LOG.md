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

## 2026-10-03 (evaluation on our own sources)

### Labels
- The 296 stratified candidates were labelled by an LLM (silver, `data/gold/silver_llm.jsonl`), blind to the
  pipeline's predictions and the strata. Not human gold; see `docs/ai_usage.md`.
- Human spot-check of a fixed random 50 (entity and event type only): entity agreement 72% (kappa 0.66), event
  type 50% (kappa 0.40; 0.37 without 2 primed items). About 7 of the 25 event disagreements are items where the
  labelling guide has an explicit rule that the LLM label follows; most others are genuinely ambiguous classes.

### First 11-class measurement on our sources (silver, test split, before any fix)
On-sample accuracy 0.585, macro-F1 0.585 over all 11 classes: far below the 0.879 of the 7-class tweet proxy.
Pipeline precision by predicted class: Cyber/Operational 0.88, Macroeconomic 0.73, Earnings 0.71, Product
Launch 0.71, Regulatory/Legal 0.58, Management Change 0.58, Natural Disaster 0.47, Geopolitical 0.36,
Credit Event 0.28, Merger/Acquisition 0.27 (`docs/results/silver_eval_prefix.json`).

### Error analysis and fixes (done on these labels, so post-fix numbers are optimistic)
| Change | Evidence | Before | After |
|---|---|---|---|
| Six text rules rewritten to need context, 26 regression cases tested | `downgrade` matched "ope-rating" and stock ratings; `default` matched "by default on"; `operations` matched "memory recall"; `disaster` matched "flood the Play Store", "Wildfire Video", "Hurricane Protection"; `launch` matched government budgets and buybacks; `legal` matched "investigation time" | | |
| Zero-shot verifier threshold 0.10 -> 0.20 | gold dev split: false-positive rate 0.57 -> 0.30, recall unchanged | | |
| Merger/Acquisition added to the verified classes | gold dev split: head M&A labels 0 of 6 correct (weak labels from the Twitter topic "M&A / Investments") | | |
| Gold population precision now follows current predictions (inverse-probability weights) | the first estimator measured precision inside the sampling strata, which are fixed by the old predictions | | |

Final state after all changes of 2026-10-03 (test split, silver labels, optimistic for the rule fixes): event
accuracy 0.637, macro-F1 0.659, weighted F1 0.638; entity 0.722; sentiment 0.604; factuality 0.618
(`docs/results/silver_eval.json`). Population precision (current predictions, approximate 95% CI): Cyber 1.00
(0.70-1.00), Natural Disaster 1.00 (0.61-1.00), Product Launch 0.85 (0.64-0.95), Merger/Acquisition 0.75
(0.44-0.97), Regulatory/Legal 0.75 (0.41-0.93), Macroeconomic 0.74 (0.49-0.88), Earnings 0.72 (0.48-0.89),
Other 0.71 (0.61-0.80), Management Change 0.59 (0.36-0.82), Credit Event 0.47 (0.25-0.70), Geopolitical 0.38
(0.16-0.61).

Post-fix, before the entity threshold change (test split, optimistic): on-sample accuracy 0.585 -> 0.637, macro-F1 0.585 -> 0.659, weighted F1
0.583 -> 0.638, entity accuracy 0.717 -> 0.736. Regression found and kept visible: Cyber/Operational F1 0.92 ->
0.56. Part of the old 0.92 was luck (the old `operations` rule matched "pilot recalls cockpit attack"); the rest
is the 0.20 verifier rejecting security incidents. Not re-tuned on the test split.

### Impact after re-annotation
Recalibrated on the re-annotated corpus (with the score daemon paused: a concurrent rebuild of the events table
had emptied the inner-check set and crashed calibration; `calibrate` now fails with a clear message instead).
Out-of-time test unchanged within noise: Spearman 0.327 (0.267-0.384), AUC 0.725, PR-AUC 0.392, Brier 0.139,
large move 58% at Impact >= 7 (n = 50); event-type-only baseline 0.318 / 0.701.

### Event-classifier retraining experiment (negative result; nothing shipped)
`scripts/event_head_experiment.py`, results in `docs/results/event_head_experiment*.json`. Protocol fixed before
running: no evaluation item or near-duplicate (same normalised title, or MiniLM cosine >= 0.85) in training;
whole pipeline evaluated (8-K items and rules first, then head, Earnings guard, verifier); candidates compared on
the dev split (84 items) only.

| Head (encoder, training data) | Dev accuracy | Dev macro-F1 | Non-Other precision | Non-Other recall |
|---|---|---|---|---|
| current: MiniLM, base (tweets + 8-K + seeds) | 0.667 | 0.609 | 0.714 | 0.577 |
| MiniLM, v2 (Twitter M&A and Politics mappings repaired + 1,251 in-domain rule-labelled items) | 0.607 | 0.605 | 0.660 | 0.635 |
| MiniLM, v3 (v2 with in-domain items given priority) | 0.619 | 0.605 | 0.681 | 0.615 |
| mpnet-base, base / v2 | 0.655 / 0.583 | 0.586 / 0.578 | 0.691 / 0.615 | 0.558 / 0.615 |
| bge-base, base / v2 / v3 | 0.631 / 0.607 / 0.643 | 0.573 / 0.633 / 0.635 | 0.718 / 0.654 / 0.711 | 0.539 / 0.654 / 0.615 |

Retraining the MiniLM head on the base data reproduces the production head exactly (a check on the harness).
No candidate is clearly better: the best macro-F1 (bge v3, +0.026) comes with lower accuracy (-0.024), about
two items either way out of 84. The production head is kept. Reading: the head's weakness on our sources comes
from its weak labels (tweets, rules), not from the encoder; more in-domain human labels are the fix.

### Entity linking and sentiment (dev split decisions)
- Primary-entity threshold 0.35 -> 0.60 (`nlp/engine.py`): dev entity accuracy 0.702 -> 0.750 (0.55: 0.738;
  0.65: 0.679). Passing mentions ("pasta sold at Walmart", "a lease at Google's center") sat at relevance
  0.49-0.57. A simulation from stored annotations reproduced all 14,983 stored decisions before the sweep.
  Counting a verified macro ML label as macro evidence made no difference on dev and was not adopted.
  Test split (read once after the change): entity accuracy 0.736 at 0.35 -> 0.722 at 0.60. The dev gain (+4 of
  84 items) did not replicate (-3 of 212); both moves are within noise, so the threshold has no measurable effect
  on entity accuracy. Kept as chosen on dev (changing it back on test evidence would be tuning on the test set);
  its practical effect is fewer company signals from passing mentions.
- Sentiment neutral band: dev agreement 0.57-0.61 for any band from 0.05 to 0.35, so 0.15 is kept. Most
  disagreements are the model scoring a clearly directional item near neutral (23 of 35): a model limitation.

### Human gold set (all 296 items labelled by the author)
Test split (212 items), human labels, pipeline as deployed (`docs/results/gold_eval.json`). This is the
11-class result to quote; the 0.879 figure is a 7-class tweet proxy.

| | Value |
|---|---|
| Event accuracy | 0.618 |
| Event macro-F1 (11 classes) | 0.585 |
| Event weighted F1 | 0.628 |
| Entity accuracy | 0.759 |

| Class | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| Product Launch | 0.95 | 0.59 | 0.73 | 32 |
| Cyber/Operational | 0.89 | 0.62 | 0.73 | 13 |
| Earnings | 0.87 | 0.81 | 0.84 | 16 |
| Macroeconomic | 0.72 | 0.57 | 0.63 | 23 |
| Management Change | 0.69 | 0.64 | 0.67 | 14 |
| Merger/Acquisition | 0.67 | 0.50 | 0.57 | 8 |
| Natural Disaster/Supply Chain | 0.67 | 0.50 | 0.57 | 8 |
| Other | 0.56 | 0.70 | 0.62 | 70 |
| Regulatory/Legal | 0.50 | 0.24 | 0.32 | 17 |
| Credit Event | 0.40 | 0.75 | 0.52 | 8 |
| Geopolitical | 0.14 | 0.67 | 0.24 | 3 |

Reading: precision is high where the event has a clear form (launches, outages, results); Credit Event and
Geopolitical are over-predicted and Regulatory/Legal is under-detected. Small supports (3-17) make several
class numbers rough. Human vs LLM agreement on the same items: event kappa 0.67, entity kappa 0.71.

### Evaluation protocol from here on (test split locked)
From this point the 212-item human test split is used once, after all changes are frozen; every decision below
is made on the 84-item dev split. History, stated plainly: before the lock, the LLM silver labels covered both
splits, and rule bugs were found by error analysis that included test items (those post-fix numbers are
labelled optimistic above). The human test labels were looked at once, for the baseline in the table above,
and not used for any decision since.

### Weak classes (human gold dev split, `docs/results/weak_class_experiment.json`)
| Policy (dev, n = 84) | Accuracy | Macro-F1 | Credit FP | Geo FP | Reg/Legal TP / FN |
|---|---|---|---|---|---|
| before | 0.643 | 0.554 | 5 | 3 | 4 / 2 |
| Credit + Geopolitical verifier >= 0.40 | 0.679 | 0.591 | 2 | 1 | 4 / 2 |
| + `regulator_action` rule (shipped) | 0.690 | 0.601 | 2 | 1 | 5 / 1 |
Adopted: per-class verifier thresholds (Credit Event and Geopolitical 0.40; they trigger stress tests, so they
need stronger evidence) and a rule for regulators' own actions (guidance, rules, approvals, enforcement), with
tests. No true positive lost on dev. Small numbers: a few items each.

### DeBERTa-v3-large class-specific verification (negative result; not shipped)
`scripts/verifier_experiment.py`, `docs/results/verifier_experiment.json`, dev split only. MiniLM proposes the
class; DeBERTa-v3-large (MIT licence, runs locally) verifies it with a per-class definition hypothesis plus
exclusion hypotheses written from the definitions card (e.g. "a credit rating was upgraded" against Credit
Event), at sentence level.
| Variant | Dev accuracy | Dev macro-F1 |
|---|---|---|
| current (base, 11-way, per-class thresholds) | 0.690 | 0.601 |
| large, 11-way | 0.631 | 0.549 |
| large, class-specific, tau 0.5 / 0.7 / 0.9 | 0.667 / 0.643 / 0.643 | 0.569 / 0.530 / 0.530 |
| + second candidate from the head | same as above | same |
The larger verifier did not help: more Geopolitical false positives in 11-way mode; one fewer Credit false
positive but a lost Regulatory/Legal true positive in class-specific mode. Same conclusion as the encoder test:
the bottleneck is supervision, not model size.

### Evidence for every event label (shipped)
Each annotation now records `event_evidence`: for 8-K items and rules the exact phrase that fired and its
surrounding source text; for an ML label the source sentence the head scores highest for that class; for an
abstention, the reason. Carried into signals and `/signals/{id}/trace`. Never generated text (tests check this).

### New event head (shipped): bge-base encoder, recipe v3
Re-run of the head experiment against the human dev labels (the earlier runs used silver labels and pre-fix
rules); `docs/results/event_head_experiment_human.json`.
| Head (human gold DEV, n = 84) | Accuracy | Macro-F1 | Precision | Recall |
|---|---|---|---|---|
| previous: MiniLM, base data | 0.690 | 0.601 | 0.711 | 0.574 |
| MiniLM, v2 / v3 | 0.655 / 0.643 | 0.593 / 0.577 | 0.625 / 0.617 | 0.638 / 0.617 |
| bge-base, base / v2 | 0.667 / 0.667 | 0.582 / 0.627 | 0.703 / 0.635 | 0.553 / 0.702 |
| bge-base, v3 (experiment) | 0.714 | 0.629 | 0.689 | 0.660 |
| bge-base, v3 as shipped (`train-head`) | 0.702 | 0.615 | | |
Recipe v3 (`nlp/training_data.py`): repaired Twitter mappings (M&A needs deal words, Geopolitical needs
geopolitical words), 8-K examples, seeds, and 1,428 in-domain rule-labelled items plus 400 opinion / listicle
headlines as Other, all given priority; every gold-set item and near-duplicate excluded. It is the first head
trained with Product Launch examples (142). The shipped run differs from the experiment by four articles that
arrived in between (one dev item). The gain is small (one to three dev items) but in the same direction on the
silver labels earlier (+0.026 macro-F1); the locked test run below decides whether it holds.
Cost: the head now embeds with bge-base (110M parameters) instead of MiniLM (22M); MiniLM is still used for
clustering.

### Final locked TEST evaluation (run once, after all changes above were frozen)
Human gold test split, n = 212, 11 classes; baseline = the human gold result before this round
(`docs/results/gold_eval_baseline.json`), final = `docs/results/gold_eval.json`.

| | Baseline | Final |
|---|---|---|
| Event accuracy | 0.618 | **0.660** |
| Event macro-F1 | 0.585 | **0.636** |
| Event weighted F1 | 0.628 | **0.655** |
| Entity accuracy | 0.759 | 0.759 |

| Class (support) | Precision | Recall | F1 |
|---|---|---|---|
| Regulatory/Legal (17) | 0.50 -> 0.57 | 0.24 -> **0.47** | 0.32 -> **0.52** |
| Geopolitical (3) | 0.14 -> **0.40** | 0.67 -> 0.67 | 0.24 -> 0.50 |
| Management Change (14) | 0.69 -> 0.80 | 0.64 -> 0.86 | 0.67 -> **0.83** |
| Merger/Acquisition (8) | 0.67 -> 0.71 | 0.50 -> 0.63 | 0.57 -> 0.67 |
| Natural Disaster/Supply Chain (8) | 0.67 -> 1.00 | 0.50 -> 0.50 | 0.57 -> 0.67 |
| Product Launch (32) | 0.95 -> 0.70 | 0.59 -> 0.81 | 0.73 -> 0.75 |
| Earnings (16) | 0.87 -> 0.82 | 0.81 -> 0.88 | 0.84 -> 0.85 |
| Other (70) | 0.56 -> 0.58 | 0.70 -> 0.71 | 0.62 -> 0.64 |
| Cyber/Operational (13) | 0.89 -> 0.88 | 0.62 -> 0.54 | 0.73 -> 0.67 |
| Macroeconomic (23) | 0.72 -> 0.82 | 0.57 -> **0.39** | 0.63 -> 0.53 |
| Credit Event (8) | 0.40 -> 0.38 | 0.75 -> **0.38** | 0.52 -> **0.38** |

Reading: the targeted problems improved (Regulatory/Legal recall doubled, Geopolitical precision nearly
tripled, M&A and Management Change better), and overall accuracy and macro-F1 rose by 4 and 5 points. Three
regressions are real and kept visible: Credit Event recall fell from 6 to 3 of 8 (the stricter 0.40 verifier
and the new head), Macroeconomic recall fell, and Product Launch precision fell as the head started predicting
that class. Small supports make several per-class moves 1-3 items. Impact model after recalibration on the new
labels: out-of-time Spearman 0.332, AUC 0.728, PR-AUC 0.396, Brier 0.138, 59% large moves at Impact >= 7.

## 2026-10-03 (round 2: recall, alert tiers)

Protocol: the 212-item test split was evaluated once (above) and is retired; all 296 human-labelled items are now
development data. The next result will be validated on a fresh out-of-time test set (articles collected after the
model freeze), labelled the same way.

| Change | Evidence (development data) | Result |
|---|---|---|
| Zero-shot rescue for abstentions (tau 0.4-0.7) | dev: each recovered Credit/Macro item cost 2-4 false positives, accuracy never above current | **rejected** (`docs/results/rescue_experiment.json`) |
| Rules `distress` (companies collapsed, creditor protection, into liquidation / administration, insolvencies rise) and `macro_markets` (borrowing costs, sovereign yields, fiscal / bailout packages, currency moves) | written from domain knowledge (only 2 credit events in dev); dev accuracy 0.702 -> 0.714, Macro recall 6/9 -> 7/9, no new false positive | shipped, with positive and negative tests ("failed to agree", "Trump administration") |
| `bank_run` needs an actual run | 0 of 3 correct before: warnings and history pieces ("warns of a bank run if ...") | shipped |
| Question / ranking headlines -> Other (labelling guide tie-breaker 3, title only) | fires on 13 of 296; 10 agree with the labeller; earnings previews excluded because the labeller labels them Earnings (guide updated) | shipped |
| Alert tier `confirmed` / `standard` on every signal | per-source precision on 296 items (`docs/results/tier_experiment.json`): 8-K items 0.95, `launch` 0.96, `macro_data`, `central_bank`, `disaster`, `regulator_action` 1.00; ML head 0.52 | confirmed tier 59/61 = **96.7%** (95% CI 88.8-99.1%), 35% of alerts; standard tier 56.8% |

Accuracy on the 296 development items: 0.676 -> 0.679 after these changes (optimistic: same data). Correction
recorded: an earlier "top alerts 100% / 90.5%" reading ignored ties at confidence 0.90 and was withdrawn.

### Fresh out-of-time TEST (run once, 2026-10-03, after the round-2 freeze)

182 articles collected after the model freeze (10:43 IST), sampled the same stratified way and labelled by the
author (3 labels revised after a guideline-consistency check, flagged `revised`; the model's predictions were not
shown). Evaluated once with the frozen pipeline (`docs/results/gold_eval_fresh.json`,
`docs/results/fresh_tier_precision.json`).

| Metric | Old locked test (212) | Fresh test (182) |
|---|---|---|
| Event accuracy | 0.660 | **0.632** |
| Event macro-F1 | 0.636 | **0.612** |
| Weighted F1 | 0.655 | 0.649 |
| Entity accuracy | 0.759 | **0.665** |
| Confirmed-tier precision | 96.7% on dev (59/61) | **54.5% (6/11, 95% CI 28-79%)** |
| Standard-tier precision | 56.8% on dev | 58.7% (71/121) |

Reading: overall accuracy held roughly (0.63 vs 0.66) on new data from a different week. The confirmed tier did
**not** hold: the dev estimate was optimistic, because the rules were chosen and checked on the same 296 items.
On fresh data `rule:disaster` fired on court cases about climate damage (1/4 correct) and `rule:macro_data` on
round-ups that merely mention inflation (4/6). The fresh set has no 8-K filings (EDGAR added 2 documents in the
window), so the 8-K part of the tier, 0.95 on dev, is untested here. Weakest classes on fresh data: Product Launch
precision 0.25 (20 predicted, 5 true), M&A 0.27, Credit Event 0.33 (6 predicted, 2 true), and Other recall 0.49
(noise is pushed into risk classes). This fresh set is now spent; further changes need another fresh set.

## 2026-10-04 (round 3: fixes for the fresh-test errors)

Protocol: the fresh set is spent, so all 478 human labels (296 earlier + 182 fresh) are development data. Heads
trained with human labels are compared by 5-fold cross-validation (a fold's items are never in its training
data); everything else is deterministic and scored on all 478 (`docs/results/round3_experiment.json`). These
numbers are development estimates, not results: the shipped version is validated on a NEW fresh test set.

Event classifier (whole pipeline, 478 items):

| Variant | Accuracy | Macro-F1 | Alert precision | 296 subset | 182 subset | Confirmed tier |
|---|---|---|---|---|---|---|
| Shipped before round 3 | 0.684 | 0.685 | 0.674 | 0.716 | 0.632 | 65/72 (90.3%) |
| + head bar 0.5 for Product Launch and M&A | 0.726 | 0.710 | 0.759 | 0.733 | 0.714 | 65/69 |
| **+ v3 refit with human labels (weight 3) + `disaster` excludes court stories** | **0.741** | **0.739** | **0.779** | 0.757 | 0.714 | **65/69 (94.2%, CI 86-98%)** |

- The head over-predicted Product Launch (70 predicted / 46 true) and M&A (22 / 13). A per-class bar of 0.5
  (`min_confidence_by_class` in `config/models.yaml`) fixed most of it. It was designed after seeing the fresh
  errors, so its gain on the 182 subset is optimistic; it also helps on the 296 items it was not designed on.
- Human labels as training examples (weight 1 or 3 equal within noise; 3 kept) add about 1.5 points on both
  subsets. Credit Event: 12 of 14 found (shipped: 9), 3 false alarms.
- `disaster` now has an `exclude` pattern for legal stories (4/7 -> 4/4). `macro_data` on the headline only made no
  difference and was dropped. Rule options `exclude` and `scope: title` added to the rule engine, with tests.
- Rejected: Product Launch through the zero-shot verifier. Alone it helps less than the bar (shipped head: accuracy
  0.703 vs 0.726); added to the bar it lowers accuracy slightly (0.736 vs 0.741).

Entity resolution (deterministic, all 478): 0.726 -> **0.766** (296 subset 0.764 -> 0.767, 182 subset 0.665 ->
0.764). Three changes: primary-entity bar 0.60 -> 0.55 (in-title companies past the first third of the headline
fell just under it); a broker in a rating headline ("Wells Fargo Downgrades Liquidia") is not the subject; a
Macroeconomic or Geopolitical label with no company is market-wide at the minimum strength (0.6), so 46 macro
items no longer end with no subject. Also fixed: the `macro_markets` rule was missing from the market-wide rules.

Weak rules found, not changed (counts too small to act on without overfitting): `supply` 0/3, `tariffs` 1/4,
`legal` 8/14.

### Encoder switch: e5-large-v2 (shipped 2026-10-04)

Same protocol as round 3 (5-fold CV over the 478 human labels, rules R1, policy P2, head v3 + human labels x3;
`docs/results/round3_experiment_*.json`). Rows marked "shipped" in those files are in-sample (the shipped head is
trained on all human labels) and are not comparable.

| Encoder | Accuracy | Macro-F1 | 296 subset | 182 subset |
|---|---|---|---|---|
| bge-base-en-v1.5 (previous) | 0.741 | 0.739 | 0.757 | 0.714 |
| all-mpnet-base-v2 | 0.741 | 0.748 | 0.757 | 0.714 |
| bge-large-en-v1.5 | 0.741 | 0.740 | 0.774 | 0.687 |
| **e5-large-v2 (shipped)** | **0.770** | **0.769** | **0.774** | **0.764** |

Rule applied: a model is shipped only if it beats the current one on this comparison on accuracy and macro-F1.
After the switch and a full re-annotation, recalibration and golden-test regeneration (WAL: Impact 7.48 -> 7.43, P&L
-2.19M -> -2.15M, test passes), the Impact model on the 1,003 out-of-time filings reads AUC 0.724, Spearman 0.330,
Brier 0.138. For the record: round 3 with bge-base had moved it from 0.728 to 0.720; e5 recovers most of that.
Previous head kept on the server as `models/event_head_bge_base.pkl`. Next: a new fresh test set validates this.

### Second fresh out-of-time TEST (run once, 2026-10-05, e5-large model)

202 articles published after the e5 freeze (2026-10-04 03:08 UTC), sampled with `scripts/make_fresh_set.py --name fresh2`,
labelled by the author (8 government appointments revised from Management Change to Other after a guideline check; a
block of 29 answers pasted from an earlier batch was caught by comparing answers with titles and relabelled). Evaluated
once (`docs/results/gold_eval_fresh2.json`, `fresh2_tier_precision.json`).

| Metric | Fresh test 1 (bge-base, round 2) | **Fresh test 2 (e5-large, round 3)** |
|---|---|---|
| Event accuracy | 0.632 | **0.703** |
| Macro-F1 | 0.612 | **0.693** |
| Weighted F1 | 0.649 | **0.712** |
| Entity accuracy | 0.665 | **0.703** |
| Standard-tier precision | 58.7% (71/121) | **74.4% (96/129)** |
| Confirmed-tier precision | 54.5% (6/11) | 50.0% (3/6, CI 19-81%) |

Reading: the round-3 changes and the e5 encoder held on new data (+7 points accuracy, +8 macro-F1). Weakest classes:
Management Change precision 0.13 (the model calls government appointments management changes; the guide says Other),
Cyber/Operational recall 0.53, Product Launch precision 0.55. The confirmed tier is still the weak spot: `rule:launch`
fired on "launches 8.6% yield monthly dividend" and "auto show debuts", `rule:disaster` on "buyers flood in". These are
fixable rule bugs, but a fix can only be claimed after another fresh set. This fresh set is now spent (development data).

## Round 4 (2026-10-05): rule fixes, all 680 labels, end-to-end fine-tune tried

5-fold CV over all 680 human labels (both fresh sets are now development data), whole pipeline scored, e5-large
encoder, recipe v3 + human labels x3, PL/M&A bar 0.5 (`scripts/round3_experiment.py`,
`docs/results/round3_experiment_e5-large-v2_n680.json`; `scripts/finetune_experiment.py`,
`docs/results/finetune_experiment_e5-large-v2_R4.json`).

| Variant | Accuracy | Macro-F1 | Confirmed tier |
|---|---|---|---|
| R1 rules (shipped in round 3), frozen encoder + head | 0.752 | 0.755 | 68/75 |
| **R4 rules, frozen encoder + head (shipped)** | **0.756** | **0.758** | **68/72** |
| R4 rules, e5-large fine-tuned end to end (3 epochs, lr 2e-5) | 0.750 | 0.759 | 68/72 |

- R4 = two excludes: `rule:disaster` ignores market slang ("buyers/money/orders flood in"; 4/5 -> 4/4) and
  `rule:launch` ignores funds, dividends, ETFs, note offerings and trade/auto-show debuts (24/27 -> 24/25).
- Fine-tuning the whole encoder did not beat the frozen encoder on accuracy (and needs a GPU at inference), so it
  was not shipped (rule: a switch must win on both accuracy and macro-F1).
- The head was retrained on all 680 human labels. The gain must still be confirmed on a third fresh set.

### Still open
- Consistency review of the first 50 human labels (made before the definitions card; 15 conflict with an explicit
  card rule), to be decided by the labeller.
- Credit Event recall: dev has only 2 credit events; the fresh test set is the only fair measure.
- Training labels are the bottleneck (`docs/ML_LABEL_AUDIT.md`): no Product Launch examples, 10-16 seed
  examples for Credit / Natural Disaster / Cyber, contaminated Twitter mappings for M&A and Geopolitical.
- Verifier keep/drop and probability calibration, on the gold dev split.
- Some filing texts lost curly quotes when decoded (shown as U+FFFD); fixing needs a re-fetch of those filings.
- Large models (entity sentiment 418 MB, SetFit 87 MB) are not in git: publish as release assets with a download
  command.
