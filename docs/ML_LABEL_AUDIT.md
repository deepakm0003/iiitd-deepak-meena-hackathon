# Event classifier: training-label audit

What the event classifier learned from, and where that supervision is weak or contaminated. Source:
`src/tripwire/nlp/training_data.py`, `docs/results/event_classifier_training.json`,
`docs/results/event_head_experiment*.json`.

## How an event label is produced (deployed pipeline)

1. **8-K item map** (`config/event_rules.yaml` `item_map`): the filer's own item number, for SEC filings.
2. **Text rules** (same file, `rules`): high-precision regex with context; a specific 8-K item beats a mention
   rule; only bankruptcy/default rules may override an item.
3. **ML head** (MiniLM sentence embedding + logistic regression, `models/event_head.pkl`) for items 1-2 leave
   undecided; Earnings guard; abstain below head probability 0.30.
4. **Verifier** (DeBERTa-v3 NLI zero-shot) for the stress-mappable classes and M&A: abstain if it does not
   support the head's class (0.20; 0.40 for Credit Event and Geopolitical).

Only step 3 is trained. Its training data:

## Training data of the previous head (n = 486, balanced to at most 64 per class; replaced 2026-10-03)

| Class | Examples | Source | Quality |
|---|---|---|---|
| Earnings | 64 | Twitter topic "Earnings" + 8-K item 2.02 | good: clear form |
| Merger/Acquisition | 64 | Twitter topic "M&A / Investments" + 8-K 2.01 | **contaminated**: the topic mixes investments, fundraises and partnerships with M&A. On the gold dev split the head's M&A labels were 0 of 6 correct |
| Macroeconomic | 64 | Twitter topics "Fed", "Currencies", "Macro" | good |
| Regulatory/Legal | 64 | Twitter topic "Legal / Regulation" + 8-K 3.01/4.02 | mixed: tweets are about regulation in general, not specific actions |
| Management Change | 64 | Twitter topic "Personnel Change" + 8-K 5.02 | good |
| Geopolitical | 64 | Twitter topic "Politics" | **contaminated**: mostly US domestic politics, which the definitions card excludes |
| Other | 64 | Twitter topics "Analyst Update", "Dividend", "IPO", "Stock Commentary", "Stock Movement" | narrow: no in-domain web noise (local news, entertainment, crime), which is most of our real "Other" |
| Cyber/Operational | 16 | hand-written seed examples | **too few** |
| Credit Event | 12 | hand-written seed examples | **too few** |
| Natural Disaster/Supply Chain | 10 | hand-written seed examples | **too few** |
| Product Launch | **0** | none | **absent**: the head cannot predict this class; every Product Launch label comes from the `launch` rule |

Origins: Twitter 385, 8-K 59, seed 42. Validation split (878): Twitter 757 + 8-K 121, covering only 7 of the 11
classes; that is why its 0.879 macro-F1 did not carry over to our sources (human gold: 0.585 over 11 classes).

## Known false-positive patterns (human gold dev split and error analysis)

| Class | Pattern | Cause |
|---|---|---|
| Credit Event | generic credit vocabulary ("medical debt", "bailout package", "home loan", rating *upgrades*) | 12 seed examples; the head learned "credit/debt words" rather than distress |
| Geopolitical | international human-interest stories (FlyDubai cockpit attack), domestic politics | Twitter "Politics" mapping |
| Merger/Acquisition | partnerships, fundraises, product integrations | Twitter "M&A / Investments" mapping |
| Regulatory/Legal (rule) | any lawsuit mention ("contentious lawsuit" in a racing podcast) | rule fires on the word, not on a company action |
| Natural Disaster, Cyber, Product Launch, Credit (rules) | metaphors and names ("flood the Play Store", "Wildfire Video", "pilot recalls", "by default on") | keyword rules; fixed 2026-10-03 with context requirements and 26 regression tests |

## Known false-negative patterns

| Class | Pattern |
|---|---|
| Regulatory/Legal | regulators' own actions (guidance, rules, approvals) phrased without "lawsuit/fine" words; addressed by the `regulator_action` rule |
| Credit Event | distress described indirectly ("16 trucking companies collapsed") |
| Cyber/Operational | specific incidents the stricter verifier rejects (software glitch, insider data leak) |

## In-domain rule-labelled data (experiment only, not shipped)

1,255 items from our own feeds labelled by the rules, after excluding every evaluation item and any
near-duplicate (same normalised title or MiniLM cosine >= 0.85). Adding them (with the repaired Twitter
mappings) did not beat the shipped head on the dev split (`docs/results/event_head_experiment*.json`). The rules
that labelled them had the keyword bugs listed above at the time, which is one reason.

## Current head (2026-10-03): recipe v3, bge-base encoder
n = 1,273 (at most 150 per class): Other, Macroeconomic, Regulatory/Legal, Earnings, Management Change,
Geopolitical and M&A 150 each, Product Launch 142, Cyber/Operational 55, Credit Event 15, Natural Disaster 11.
Origins: 1,056 in-domain (rule-labelled items and opinion headlines, given priority), 127 Twitter (repaired
mappings), 90 8-K. Remaining weakness: Credit Event and Natural Disaster still rely on few examples; their
precision comes from rules and the verifier. `docs/results/event_head_training.json`.

## Consequences for the next steps

- Do not expect a better encoder to fix this (8 variants tested): the label sources are the bottleneck.
- Precision for the high-impact classes comes from verification and deterministic evidence (8-K items, rules),
  not from the head; the head's role is to propose candidates.
- Clean, in-domain positives and hard negatives per class are the real fix for the head; the human gold set is
  the test set and is not used for training.
