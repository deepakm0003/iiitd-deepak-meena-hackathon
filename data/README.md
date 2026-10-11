# data/

Every file the prototype runs on is in this folder (all small, public-source or synthetic). Nothing here is
proprietary or confidential client data. Third-party raw downloads stay out of git (`raw/`, git-ignored) and can
be fetched with the commands below.

## Files in the repository

| File | What it is | Source | Nature |
|---|---|---|---|
| `demo/tripwire_demo.db.gz` | SQLite snapshot of the live system's last 14 days: 4,661 signals, 20 stress runs, 111,165 daily prices. `python -m tripwire demo` runs on it | Collected by Tripwire from the public sources listed below | Public (derived) |
| `demo/snapshot.json`, `demo/collector_status.json` | When the snapshot was taken and the collectors' health at that time | Tripwire | Metadata |
| `book.json` | The bank book that Module B stress-tests: 300 SME loans (Tranche 1) and 29 large-corporate positions on public names (Tranche 2), with the capital position | Built by Tripwire; SME loans derived from the Kaggle merchants | **Synthetic** (every parameter is in `config/assumptions_register.yaml`) |
| `merchant_features.csv` | Per-merchant aggregates (sector, volume, trend, refund and error rates) behind the SME loans | Derived from the Kaggle transactions dataset | Aggregates only, no card or customer fields |
| `mcc_sector_map.csv` | Merchant category code -> sector | Hand-built from the public MCC list | Public |
| `market_inputs.json` | Measured shock analogs (e.g. the 2023 regional-bank stress) and equity betas used by the scenarios | Yahoo Finance prices and FRED series | Public (derived) |
| `gold/human_check.jsonl` | 296 hand-labelled items (event class, company, sentiment) | Labelled by the author on items collected by Tripwire | Human labels |
| `gold/fresh_labels.jsonl`, `gold/fresh2_labels.jsonl` | 182 + 202 hand-labelled items from two out-of-time test sets (articles published after a model freeze) | Same | Human labels |
| `gold/*candidates*.jsonl` | The items sampled for labelling, with the sampling reports | Tripwire | Public text + metadata |
| `gold/silver_llm.jsonl` | LLM-assisted (silver) labels, used only for training and agreement checks, never to report accuracy | See `docs/ai_usage.md` | Machine labels |

## Sources used (not redistributed)

| Source | Used for | How to get it |
|---|---|---|
| Kaggle "Financial Transactions Dataset: Analytics" (computingvictor/transactions-fraud-datasets, Apache 2.0) | Aggregate merchant features for the synthetic SME book | `kaggle datasets download computingvictor/transactions-fraud-datasets -p data/raw/kaggle_transactions --unzip` |
| SEntFiN 1.0 (entity-level financial headline sentiment) | Training and testing the entity-sentiment model | `kaggle datasets download ankurzing/aspect-based-sentiment-analysis-for-financial-news -p data/raw/sentfin --unzip` |
| Twitter financial news topics (zeroshot/twitter-financial-news-topic, Hugging Face) | Weak labels for the event classifier | Downloaded automatically by `train-head` |
| Live public text: GDELT 2.0, Finnhub news, SEC EDGAR 8-K, Federal Reserve and RBI RSS, Bluesky | The signals | Collected by `python -m tripwire collect --live` (Finnhub needs a free API key in `.env`) |
| Yahoo Finance (yfinance), FRED | Event studies, Impact calibration, market snapshot | Fetched by the research commands |

The raw Kaggle files are not committed: they are large and include card-like fields (synthetic, but kept out on
principle). Only the aggregates in `merchant_features.csv` are used. The demo, the website and the tests run on the
committed files alone.
