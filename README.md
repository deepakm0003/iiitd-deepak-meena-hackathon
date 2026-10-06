# Tripwire - S&P Global & Crisil Campus Hackathon

**Candidate Name:** Deepak Meena
**College Email ID:** deepak23188@iiitd.ac.in
**College / Campus:** Indraprastha Institute of Information Technology Delhi (IIIT Delhi)
**Demo Video Link:** _to be added (YouTube, unlisted)_
**Slide Deck Link (if hosted externally):** not hosted externally; see [docs/presentation.pdf](docs/presentation.pdf) _(added before submission)_

**Run it in two commands** (no GPU, no API keys, no Node.js; Python 3.11):

```bash
pip install -r requirements.txt
python -m tripwire demo
```

This opens http://127.0.0.1:8000: the website and the risk dashboard on a snapshot of real data collected by the live
system. Details are in [section 4](#4-quickstart--installation).

## 1. Project Overview / Problem Statement & Approach

Credit and risk teams have to react to events described in unstructured text (news, regulatory filings, central-bank
releases, social posts) long before those events reach structured data.

**Tripwire is an AI/NLP risk engine (Module A)** that turns that text into structured, explainable risk signals:
- which company the item is about, or whether it is market-wide;
- an event class (11 classes, from Credit Event to Product Launch), with the exact sentence that decided it;
- entity-level sentiment;
- factuality (confirmed, rumour or opinion);
- an **Impact score from 1 to 10** built from seven named factors, with a calibrated probability of a large price move.

**Module B, credit early warning and stress testing:**
- decides which signals deserve a stress test, check by check;
- applies sourced shocks to a synthetic wholesale banking book;
- shows exactly what moves P&L, ECL, RWA and CET1, against the Basel and RBI floors, with reverse stress and mild /
  base / severe ranges;
- keeps a Red / Amber / Green watchlist per name.

The approach is "evidence first":
- **8-K items and precise rules decide first.** The ML classifier only handles what they leave, and its labels must
  pass an independent zero-shot verifier.
- **Every number carries its provenance:** OBSERVED, MEASURED, MODEL, DERIVED, SYNTHETIC or ASSUMPTION. The 28
  assumptions are listed in [config/assumptions_register.yaml](config/assumptions_register.yaml).
- **Accuracy is reported only on human-labelled data and locked test sets,** including the experiments that failed:
  [docs/IMPROVEMENT_LOG.md](docs/IMPROVEMENT_LOG.md).

**Users can test it on their own input.** The **Analyse** page runs the production models on a pasted article or PDF,
a batch of headlines or an uploaded portfolio. Nothing is stored, and the user downloads a PDF report.

## 2. Architecture & Tech Stack

```
 collectors (GDELT, Finnhub, SEC EDGAR 8-K, Fed + RBI RSS, Bluesky)
        │  every 10-30 min, deduplicated
        ▼
 NLP engine  ──  entity linking (alias table + GLiNER NER) → event: 8-K item map → context rules
        │        → ML head (e5-large embeddings + logistic regression) checked by a DeBERTa zero-shot verifier
        │        → entity-level FinBERT sentiment → factuality → evidence span
        ▼
 events  ──  clustering of duplicate stories, novelty, corroboration, source credibility
        ▼
 Impact score  ──  7 factors (severity, sentiment magnitude, entity importance, novelty, corroboration,
        │          credibility, historical reaction), relevance gate, isotonic calibration
        ▼
 Module B  ──  trigger checks → scenario (entity / sector / systemic shocks, measured analogues + assumptions)
        │       → repricing of every position → ECL (IFRS 9 stages) → RWA → CET1 vs floors, reverse stress
        ▼
 FastAPI (/signals, /signals/{id}/trace, /portfolio, /watchlist, /stress-test, /analyze/*, /model/metrics)
        ▼
 React website + dashboard (Vite, TypeScript, Tailwind, Framer Motion)
```

- **Python 3.11:** FastAPI, Pydantic, SQLAlchemy (SQLite; PostgreSQL-ready through the `Store` port),
  sentence-transformers, transformers, scikit-learn, GLiNER.
- **Frontend:** React 19, Vite, TypeScript, Tailwind CSS v4, Framer Motion; PDF reports with jsPDF in the browser.
- **Ports and adapters** for the store, queue and sources: see [docs/adr](docs/adr).
- **Models:**
  - `intfloat/e5-large-v2` encoder with our trained event head ([models/event_head.pkl](models/event_head.pkl));
  - `MoritzLaurer/deberta-v3-base-zeroshot-v2.0` verifier;
  - FinBERT fine-tuned on (sentence, entity) pairs from SEntFiN for entity-level sentiment (falls back to
    `ProsusAI/finbert`);
  - `urchade/gliner_multi-v2.1` NER.
  - All are open source; none generates text.
- **Module B method:** [docs/module_b.md](docs/module_b.md).

## 3. Dataset Used

- **Kaggle "Financial Transactions Dataset: Analytics"** (computingvictor/transactions-fraud-datasets, Apache 2.0):
  - consumer card transactions, used only to derive aggregate merchant features for the synthetic SME loan book
    (300 obligors);
  - raw files are not redistributed; card numbers, CVVs and addresses are never committed;
  - profile: [docs/data_profile.md](docs/data_profile.md).
- **Salad Money Open Banking data** (listed in the case study) was not used: access is restricted to a UK Trusted
  Research Environment.
- **Live public text sources**, collected continuously by the running system:

  | Source | Type | What we keep |
  |---|---|---|
  | GDELT 2.0 GKG (15-minute files) | Global news | Records naming a tracked company, a macro body or strong finance themes |
  | Finnhub company and general news | News | Headline, summary, publisher, time |
  | SEC EDGAR 8-K filings | Regulatory filings | Exact acceptance time, 8-K items, press-release text, for 73 companies |
  | Federal Reserve and RBI press releases (RSS) | Regulators | Title, summary, time |
  | Bluesky (Jetstream) | Social | Posts with a tracked cashtag or company plus finance keyword; authors hashed |

- **Market data** (Yahoo Finance via yfinance, FRED) for event studies, calibration and the book's market snapshot.
- **Synthetic wholesale book:** 300 SME loans derived from the Kaggle merchants, plus 29 large-corporate positions on
  public names (bonds, loans, equity, swaps, an index put). Exposures are synthetic; every parameter is an assumption
  in the register.
- **Evaluation data:**
  - 680 human-labelled items (296 earlier + 182 and 202 from two fresh out-of-time sets, [data/gold](data/gold)),
    labelled with [docs/labeling_guide.md](docs/labeling_guide.md);
  - LLM-assisted (silver) labels are used only for training and agreement checks, never to report accuracy:
    [docs/ai_usage.md](docs/ai_usage.md).

## 4. Quickstart & Installation

Runtime: Python 3.11 on Windows 11 or Linux. A virtual environment is recommended:
`python -m venv .venv`, then `.venv\Scripts\activate` on Windows or `source .venv/bin/activate` on Linux/macOS.

```bash
git clone https://github.com/deepakm0003/iiitd-deepak-meena-hackathon.git
cd iiitd-deepak-meena-hackathon
pip install -r requirements.txt
python -m tripwire demo
```

### What the demo shows
- **Data:** a snapshot of the live system's last 14 days ([data/demo](data/demo)): about 4,700 real signals, their
  stress runs and price history. Dates are shown as of the snapshot time.
- **Website:** http://127.0.0.1:8000. **Dashboard:** http://127.0.0.1:8000/app, with:
  - live signals;
  - the full reasoning trace per signal;
  - portfolio and what-if stress tests;
  - the early-warning watchlist;
  - model trust and data sources.
- **Analyse page** (your own article, headlines or portfolio, analysed by the real models):
  - needs the ML stack: `pip install -r requirements-research.txt`;
  - the first run downloads the open-source models (about 2.5 GB) and loads them in a few minutes on CPU;
  - without the ML stack, the rest of the product works and the page says what to install.
- **Options:** `--port 8001`, `--reset` (start again from the snapshot), `--no-analyze`, `--no-browser`.

### Running the live system (what the deployed server runs)

| Command | What it does |
|---|---|
| `python -m tripwire collect --live --daemon` | All collectors continuously (needs `.env`, see `.env.example`) |
| `python -m tripwire nlp --daemon` | Annotate new documents (entities, event, sentiment, factuality, evidence) |
| `python -m tripwire score --daemon` | Cluster into events, score Impact, run automatic stress tests |
| `python -m tripwire api` | The API (OpenAPI docs at /docs) |
| `python -m tripwire calibrate` | Re-fit the Impact calibration and validate it out of time |
| `python -m tripwire train-head --encoder intfloat/e5-large-v2` | Retrain the event head |
| `python -m tripwire eval-gold --labels <file> --candidates <file>` | Evaluate on a human-labelled set |
| `python -m tripwire status` | Store counts and collector health |

Frontend development: `cd frontend && npm install && npm run dev` (proxies `/api` to port 8000).
Tests: `pip install -r requirements-dev.txt && pytest`.

## 5. Key Results & Domain Impact

All figures are measured on held-out human-labelled data or out-of-time market data, with sample sizes. The full
history, including negative results, is in [docs/IMPROVEMENT_LOG.md](docs/IMPROVEMENT_LOG.md); the raw outputs are in
[docs/results](docs/results).

### Event classifier
| Evaluation | n | Accuracy | Macro-F1 | Company resolution |
|---|---|---|---|---|
| Locked human test, evaluated once (before -> after round 2) | 212 | 61.8% -> **66.0%** | 0.59 -> **0.64** | 75.9% |
| Fresh out-of-time test 1 (articles after the round-2 freeze, evaluated once) | 182 | 63.2% | 0.61 | 66.5% |
| **Fresh out-of-time test 2 (articles after the e5 freeze, evaluated once)** | 202 | **70.3%** | **0.69** | **70.3%** |

On fresh test 2, alerts outside the confirmed tier were 74.4% precise (96/129). The current model adds two rule fixes
found on that test and is retrained on all 680 human labels: 5-fold cross-validation over the 680 labels gives 75.6%
(75.2% before the fixes). Cross-validation is a development estimate; the honest out-of-time number is the 70.3% above.

### Impact score
On 1,003 SEC 8-K filings published after the calibration window:
- **AUC 0.72** for large abnormal price moves (base rate 19%);
- Spearman 0.32;
- Brier score 0.139 against 0.155 for a no-skill forecast.

### Sentiment
Entity-level FinBERT, on the SEntFiN held-out test set:
- macro-F1 **0.89**, against 0.66 for plain FinBERT;
- **0.87 vs 0.44** on headlines where two companies get opposite sentiment.

### Domain impact
- **One trace from source to capital.** Example: a Western Alliance 8-K during the 2023 regional-bank stress:
  - classified as a Credit Event (liquidity stress) from the evidence sentence;
  - Impact 7.4;
  - stress-tested on the book: −$2.15M P&L, CET1 12.00% -> 11.59%.

  This example is kept as an end-to-end regression test: [tests/golden](tests/golden).
- **Nature beats tone:** the bank's own reassuring statement (+0.86 sentiment) still triggers, because the event is
  adverse by nature.
- **Honest limits** (published in the dashboard's Model trust page):
  - the weakest classes on fresh test 2 are Cyber/Operational (recall 0.53) and Product Launch (precision 0.55);
  - the "confirmed" alert tier was 6/11 precise on fresh data, below its development estimate;
  - Impact is validated only on firm-specific filings.

---

AI usage: see [docs/ai_usage.md](docs/ai_usage.md). Licence: MIT ([LICENSE](LICENSE)); third-party credits in [NOTICE](NOTICE).
