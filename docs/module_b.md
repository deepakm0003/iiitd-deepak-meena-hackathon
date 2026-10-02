# Module B: event-driven stress testing of a wholesale book

Tripwire turns a risk signal into a re-measured bank: **signal → exposure → shocks → position P&L → IFRS 9
ECL → CET1**, with every number tagged OBSERVED, DERIVED, MEASURED, MODEL, ASSUMPTION (A-xx) or SYNTHETIC.
Code: `src/tripwire/portfolio/`, `src/tripwire/stress/`. API: `/portfolio`, `/watchlist`,
`/signals/{id}/stress-decision`, `/signals/{id}/trace`, `POST /stress-test`, `/stress-test/{run_id}`,
`/stress-runs`.

## 1. The book (data card)

| | Tranche 1: SME loans | Tranche 2: large corporates |
|---|---|---|
| What | 300 merchants from the Kaggle card-transaction data (largest by FY2019 card volume) | 12 bonds, 8 loans, 6 equities, 2 swaps, 1 SPY put on real public names |
| Size | EAD $300.0M (SYNTHETIC: 0.15 x card volume, single-name cap 3%, A-02, A-11) | $151.0M exposure (SYNTHETIC, A-06) |
| Sector, state | DERIVED: main MCC mapped to GICS (A-20); most frequent merchant state ("ONLINE" if none) | OBSERVED: SEC SIC sector |
| Credit grade | rank of the behavioural risk score -> grade buckets A 10% / BBB 30% / BB 35% / B 20% / CCC 5% (A-04) | assumed rating per name (config/book.yaml) |
| PD, LGD | grade table (A-05), LGD 45% senior unsecured | grade table, LGD 45% |
| Prices | n/a (amortised cost) | OBSERVED 10y yield, SPY and VIX from the price cache; bond yields = 10y + grade spread (A-24) |
| Capital | RWA $363.2M (standardised weights by grade, equity 250%: A-22); CET1 $43.6M = 12% (A-21); tax 25% (A-12); floors 7% Basel, 8% RBI (A-10) | |

Data limits stated plainly: the transaction data is synthetic and has no loans or defaults; Tranche 2
exposures are invented on real names; market inputs are real.

## 2. The bridge from card transactions to loan PD (what is measured and what is assumed)

```
card transactions (OBSERVED, synthetic dataset)
  -> merchant features: volatility, customers, refunds, errors, online share, trend (DERIVED)
  -> P(card volume collapses next year)  (MODEL, logistic regression, calibrated; validated out of time)
  -> rank within the 300 obligors -> internal grade (ASSUMPTION A-04)
  -> 1-year PD per grade (ASSUMPTION A-05)
  -> IFRS 9 stage and ECL under stress (formula, below)
```

The model predicts a **proxy** event, not a default: next-year card volume below 50% of the mean of this and
last year. It is used for **rank ordering** (who gets the worse grades) and, as a calibrated probability, in
the early-warning list. It is not presented as a borrower PD. Validation (`docs/results/merchant_risk_validation.json`),
train FY2015-16, test FY2018 -> FY2019 (strictly later), n = 2,234, 45 events (2.0%):

| | AUC (95% CI) | notes |
|---|---|---|
| Full model | 0.849 (0.793-0.891) | Brier 0.0185; mean predicted 2.02% vs 2.01% realised |
| Volatility only | 0.849 | the model does **not** rank better than this one feature |
| Few customers only | 0.619 | |
| Equal-weight z-score | 0.602 | |
| Volume decline only | 0.342 | below chance: after a decline volume recovers (mean reversion) |

The first version scored AUC 0.911 against "next year < 50% of this year". That target rewards mean reversion
(a one-off spike "collapses" next year by construction); the two-year base removed the artefact. In this book
the 300 largest merchants are low-risk: mean predicted probability 0.27%, highest 3.7%.

## 3. Scenario: from signal to shocks

**Trigger** (`stress/trigger.py`, A-27). A signal launches a run when it is stress-mappable, factual
(confirmed/announced), adverse (by deterministic subtype, by sentiment, or by an 8-K hard flag) and
`Impact >= T(exposure)`: 5.5 if the book's direct exposure is >= 2%, 6.0 for any direct exposure, 6.5 if
sector/geography exposure >= 10%, 7.0 otherwise. Exposure counts only channels the event class has.
Every check is returned by `/signals/{id}/stress-decision`. Of 5,750 signals (2023-2026), 6 pass.

**Layers** (`config/shocks.yaml`, A-15), most specific wins so nothing is counted twice:

| Channel | Who | Example shocks (severe end) | Source type |
|---|---|---|---|
| direct | the event's company | Credit Event: equity -40%, spread +500 bp, PD x5 | ASSUMPTION |
| sector | same-sector large-corporate peers (SMEs only for sector-wide regulation, A-25) | bank sector equity = KRE move | HISTORICAL where measured, else ASSUMPTION |
| geography | SMEs in states named by the event | PD x1.8 | ASSUMPTION |
| market | everyone, **only for systemic events** (a bank's credit event, a market-wide war or tariff round) | SVB window 2023-03-08..13: 10y -43 bp, IG +26 bp, VIX +7.4 | HISTORICAL |

Severity scales every shock: `k = clip(0.4 + 0.6 (Impact - 7) / 3, 0.1, 1)`; PD multipliers scale as
`1 + k (m - 1)` so k = 0 is exactly "no change". Each run also reports **mild (k/2), base (k), severe (k = 1)**:
a range for shock-size uncertainty, not a confidence interval.

## 4. Valuation, ECL and capital

- Equities: beta x move (2-year OLS betas, MEASURED). Bonds: -duration x (rate + spread) + 1/2 convexity.
  Swaps: DV01 x rate move. SPY put: Black-Scholes repricing at the shocked spot and volatility.
- Loans, IFRS 9: stressed PD = PD x multiplier; Stage 2 if PD >= 3x origination or >= 20% (A-09); Stage 3 on
  an 8-K bankruptcy flag for the borrower. ECL = PD x LGD x EAD (Stage 1, 12-month), lifetime PD with a
  constant hazard (Stage 2, A-23), LGD x EAD (Stage 3). Loan P&L = -(ECL after - ECL before).
- Capital: CET1 after = CET1 before + P&L x (1 - tax). RWA is re-computed position by position with the same
  function before and after; it changes through **rating migration** (loans) and **market values** (bonds,
  equities, option). Reverse stress bisects the severity multiple at which CET1 / RWA reaches each floor.
- Invariants enforced by tests at k = 0, 0.3, 1 and 3: P&L = sum of path contributions; CET1 ratio = CET1 / RWA
  before and after; RWA = sum over positions; delta RWA = migration part + market-value part; delta CET1 =
  P&L x (1 - tax); ECL change = -(loan P&L). Every unaffected position carries the reason it was not hit.

## 5. Worked example: Western Alliance, 13 March 2023 (SVB crisis)

Signal: 8-K 7.01 statement on liquidity, rule `bank_run` (subtype liquidity_stress, adverse by nature even
though the statement's tone is +0.86), Impact 7.48, k = 0.50. Direct exposure: the WAL loan (threshold 6.0).

| | Before | After (base) | Change |
|---|---|---|---|
| CET1 | $43.59M | $41.94M | -$1.64M (P&L -$2.19M x 0.75) |
| RWA | $363.23M | $362.22M | -$1.01M = +$2.00M WAL loan BB -> B, -$3.01M lower market values |
| CET1 ratio | 12.00% | 11.58% | -0.42 pp |

P&L by asset class: bonds -$1.59M, equities -$0.90M, WAL loan ECL -$0.03M, SPY put +$0.29M, swaps +$0.04M.
25 positions hit; 19 Financials SMEs explicitly not reached (A-25); 285 not linked. Range: mild 11.83%,
base 11.58%, severe 11.17% (one Stage 2 migration). Reverse stress: RBI 8% floor at 6.1x the severe
scenario, Basel 7% at 8.3x.

## 6. Early-warning watchlist

Large-corporate names: the 3 strongest recent items about the issuer combined by noisy-OR, each weighted
`P(large move) x adverse x factuality x source credibility x 0.5^(age/14d)`. SMEs: the calibrated behavioural
probability, plus disasters in the home state if the disaster shows scale (3+ publishers or Impact >= 7).
8-K 1.03 / 2.04 / 4.02 on a borrower: Red regardless. Weights and thresholds: A-28.

## 7. Limitations

- Shock sizes outside the measured analog windows are registered assumptions (A-15).
- The SVB window measures regional banks (KRE); applying it to money-center banks overstates their move.
- The merchant model predicts a revenue-collapse proxy on synthetic data; grade and PD tables are assumptions.
- Single-period, instantaneous shocks; no second-round effects, hedging behaviour or funding stress.
