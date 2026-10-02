# Tripwire - S&P Global & Crisil Campus Hackathon

**Candidate Name:** Deepak Meena
**College Email ID:** deepak23188@iiitd.ac.in
**College / Campus:** Indraprastha Institute of Information Technology Delhi (IIIT Delhi)
**Demo Video Link:** _to be added (YouTube, unlisted)_
**Slide Deck Link (if hosted externally):** not hosted externally; see [docs/presentation.pdf](docs/presentation.pdf) _(added before submission)_

> Status: in development. Part 0 (foundation) is complete; sections below are filled in as each part lands.

## 1. Project Overview / Problem Statement & Approach

Credit and risk teams must react to events described in unstructured text (news, regulatory filings, social posts) long before those events show up in structured data. Tripwire is an AI/NLP Risk Engine that turns such text into structured, explainable risk signals (sentiment score, event classification, impact score), and a downstream module (Module B) that shows what a high-impact event would do to a synthetic wholesale-banking book.

Approach, in brief:
- Ingest text from several independent sources and process it through an NLP pipeline (entity linking, entity-level sentiment, event classification and extraction, event clustering, novelty and corroboration).
- Score impact with a transparent, versioned formula whose parameters are calibrated and then validated out-of-time against market reactions.
- When an event crosses the trigger threshold, match it to the exposures it actually touches and run a stress test whose every loss line traces back to the triggering sentence.

## 2. Architecture & Tech Stack

_Architecture diagram: docs/architecture.png (added in Part 7)._

- Ports and adapters: `Store` (SQLite in lite mode, PostgreSQL in full mode), `Queue` (in-memory in lite mode, Redis Streams in full mode), `Source` (replay files or live collectors). See [docs/adr](docs/adr).
- Python 3.11, Pydantic, SQLAlchemy; NLP and dashboard stack added in later parts.
- Every stored or displayed number carries a provenance tag: OBSERVED, DERIVED, MODEL, SYNTHETIC, ASSUMPTION or MEASURED. Assumptions are listed in [config/assumptions_register.yaml](config/assumptions_register.yaml).

## 3. Dataset Used

- **Kaggle "Financial Transactions Dataset: Analytics"** (computingvictor/transactions-fraud-datasets, Apache 2.0, created by Caixabank Tech): consumer card transactions used only to derive aggregate merchant features for the synthetic SME loan book. Profile: [docs/data_profile.md](docs/data_profile.md). Raw files are not redistributed; card numbers, CVVs and addresses are never committed.
- **Salad Money Open Banking Transaction Data** (listed in the case study) was not used: transaction-level access is restricted to a Trusted Research Environment for UK researchers.
- News, filings and social sources are documented here as they are added (Part 1).

## 4. Quickstart & Installation

Runtime: Python 3.11 on Windows 11 (also tested on Ubuntu in CI)

```bash
git clone https://github.com/deepakm0003/iiitd-deepak-meena-hackathon.git
cd iiitd-deepak-meena-hackathon
pip install -r requirements.txt
python -m tripwire health
```

A virtual environment is recommended (`python -m venv .venv`, then `.venv\Scripts\activate` on Windows or `source .venv/bin/activate` on Linux/macOS) before `pip install`. Lite mode needs no API keys, Docker or GPU.

## 5. Key Results & Domain Impact

_Filled in with measured results (each with its sample size) as the evaluation parts complete._

---

AI usage: see [docs/ai_usage.md](docs/ai_usage.md). Licence: MIT ([LICENSE](LICENSE)); third-party credits in [NOTICE](NOTICE).
