# Gold-set labelling guide

The gold set is the **test data** for the NLP engine. It is labelled by hand, before any model output is shown
(no peeking), and is never used for training. Labels go to `data/gold/gold.jsonl` via `python -m tripwire gold label`.

Read the item (title + lead). Judge only what the text says, not what you know happened later.

## Fields

| Field | Values | Rule |
|---|---|---|
| **Primary entity** | a universe ticker (e.g. `JPM`), `MACRO`, `OTHER`, `NONE` | The company the item is mainly *about*. `MACRO` = economy, markets, central banks, governments, no single company. `OTHER` = mainly about a company outside our universe. `NONE` = not financial at all. |
| **Event type** | one of the 11 classes below | The type of the main event. One label only. |
| **Sentiment** | `-1` negative, `0` neutral, `+1` positive | For the **primary entity** (or for markets/the economy if `MACRO`), not the tone of the writing. |
| **Factuality** | `confirmed`, `announced`, `rumour`, `denied`, `opinion` | `confirmed` = it happened / was reported as fact. `announced` = an official plan or guidance. `rumour` = an unconfirmed report attributed to sources about a specific pending event ("reportedly", "people familiar", "in talks"). `denied` = the company denies it. `opinion` = commentary, forecasts and speculation ("could fall", "might be rangebound"), stock picks, "is X a buy?", explainers. |
| **Material** | `y` / `n` | Would a credit or risk analyst want to be alerted? Usually `n` for `opinion`, routine filings and minor product news. |

## Event classes

| Class | Includes | Typical cues | Not this class |
|---|---|---|---|
| **Credit Event** | bankruptcy, default, missed payment, covenant breach, accelerated obligation (8-K 2.04), rating downgrade, going-concern doubt, bank run / liquidity stress | "files for Chapter 11", "downgraded by", "unable to meet obligations" | An earnings miss (Earnings); routine debt issuance (Other) |
| **Geopolitical** | war, armed conflict, sanctions, tariffs, export controls, trade disputes, elections with market impact | "sanctions on", "tariffs", "invasion" | Central-bank decisions (Macroeconomic) |
| **Macroeconomic** | central-bank rates, inflation, jobs, GDP, recession, yields, currency moves, market-wide selloffs | "Fed holds rates", "CPI", "repo rate", "Treasury yields" | One company's results (Earnings) |
| **Merger/Acquisition** | acquisitions, mergers, takeovers, divestitures, spin-offs, buyout talks | "to acquire", "agreed to buy", "spin off" | Partnerships without ownership change (Other) |
| **Regulatory/Legal** | lawsuits, fines, settlements, investigations, regulatory approvals/rejections, antitrust | "sued", "SEC charges", "fined", "probe", "FDA approves" | Sanctions on countries (Geopolitical) |
| **Cyber/Operational** | hacks, data breaches, outages, recalls, strikes, accidents, plant shutdowns | "breach", "outage", "recall", "strike" | Disaster-caused disruption (Natural Disaster/Supply Chain) |
| **Natural Disaster/Supply Chain** | hurricanes, floods, wildfires, earthquakes, pandemics, supply shortages, port closures | "hurricane", "shortage", "supply chain" | |
| **Earnings** | quarterly/annual results, guidance changes, pre-announcements, 8-K 2.02 | "Q3 results", "beats estimates", "cuts guidance" | Analyst opinions on the stock (Other + opinion) |
| **Management Change** | CEO/CFO/board departures and appointments, 8-K 5.02 | "steps down", "appointed CEO" | Layoffs (Other) |
| **Product Launch** | new products, services, launches, unveilings | "launches", "unveils", "introduces" | Product recalls (Cyber/Operational) |
| **Other** | buybacks, dividends, debt issuance, layoffs/restructuring, partnerships, analyst ratings, listicles, anything else | | |

## Tie-breakers
1. If two classes fit, choose the one with the **larger potential market impact** (e.g. "bank downgraded after loan losses in Q3 results" is Credit Event, not Earnings).
2. A filing titled "Item 2.02 Results of Operations" is Earnings even if the title is all you see.
3. Headlines phrased as questions or rankings ("3 bank stocks to buy") are `opinion`, class `Other`, material `n`.
   Exception (2026-10-03, from the labeller's consistent practice): an earnings preview ("... Q3 Earnings:
   What to Expect") is class `Earnings`.
4. When unsure, pick the best label and type a short note; notes are reviewed later and never change the test set retroactively without a recorded reason.

## Quality check
After at least 3 days, about 40 random items are re-labelled blind (`gold relabel`). Agreement with your earlier labels (Cohen's kappa) is reported with the results.
