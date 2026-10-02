# Data profile: Kaggle "Financial Transactions Dataset: Analytics"

Source: https://www.kaggle.com/datasets/computingvictor/transactions-fraud-datasets (Apache 2.0, Caixabank Tech, 2024 AI Hackathon).
Profiled on 2026-10-02 from the full download (365 MB zip, 1.42 GB unzipped). Provenance of all figures below: MEASURED (full scan, n = all rows).

| File | Rows x cols | Notes |
|---|---|---|
| transactions_data.csv | 13,305,915 x 12 | 2010-01-01 to 2019-10-31. Columns: id, date, client_id, card_id, amount, use_chip, merchant_id, merchant_city, merchant_state, zip, mcc, errors |
| users_data.csv | 2,000 x 14 | Includes yearly_income, total_debt, credit_score, num_credit_cards. Contains `address`: never committed |
| cards_data.csv | 6,146 x 13 | Includes acct_open_date, year_pin_last_changed, card_on_dark_web (single value). Contains `card_number`, `cvv`: never committed |
| mcc_codes.json | 109 codes | All 109 MCCs seen in transactions are covered |
| train_fraud_labels.json | 8,914,963 labels | 13,332 fraud (0.15%); labels cover a subset of transactions |

Transactions:
- Missing values: merchant_state 1,563,700; zip 1,652,706; errors 13,094,522 (i.e. no error).
- use_chip: Swipe 6,967,185; Chip 4,780,818; Online 1,557,912. Online transactions have no state.
- Negative amounts (refunds/reversals): 660,049 (4.96%). Positive spend total: $639,354,565.
- Error rows: 211,393. Top: Insufficient Balance 130,902; Bad PIN 32,119; Technical Glitch 26,271.
- merchant_state: 200 distinct values (US states and foreign countries). Top: CA, TX, NY, FL, OH, IL, NC.
- Last 24 months (2017-11-01 onward): 2,789,095 rows, 38,946 merchants with spend.
- The top 300 merchants hold 73.5% of 24-month spend; #1 merchant $10,981,964, #300 $26,109 (highly skewed, hence the single-obligor cap A-11).

Implications for the synthetic SME book (Part 5):
- `errors` such as Insufficient Balance describe the merchant's customers, not the merchant; used only as a "customer-base stress" feature.
- Fraud incidence can only be computed on the labelled subset.
- Online-only merchants are tagged national and excluded from the geography channel.
- Hints that the data is synthetic (e.g. a constant card_on_dark_web) mean it is described as synthetic-like.
