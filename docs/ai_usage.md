# AI usage

The case-study guidelines allow AI assistance when it is used with integrity and full honesty. This page records how AI was used in this project.

- **Tool:** Anthropic Claude (via Claude Code).
- **Used for:** background research on existing products and data sources, planning, drafting code and tests, reviewing documentation, and **annotating the event-classification evaluation set** (see below).
- **Done by the author:** choosing the scope and design, reviewing and running all code, checking results, and making the final decisions on every model, parameter and assumption.
- **Verification:** all numbers reported as MEASURED come from scripts in this repository and can be reproduced from the README.

## Evaluation labels for the event classifier (silver, LLM-annotated)

The 296 stratified evaluation items (`data/gold/candidates.jsonl`) were labelled by an LLM (Claude), not by a
human. The labels are in `data/gold/silver_llm.jsonl`, written by `scripts/silver_labels.py`, and every result
computed from them is reported as a **silver** result (`docs/results/silver_eval.json`), never as human gold.

- The LLM saw only what a human labeller sees in `gold label`: source, title and text. It was not shown the
  pipeline's predictions or the sampling strata, and followed `docs/labeling_guide.md`.
- Seven ambiguous items carry a note explaining the choice.
- The same LLM helped write the pipeline, so its labels may share the pipeline's view of the taxonomy.
- **Human spot-check:** the author labelled a fixed random 50 of the items blind, entity and event type only
  (`gold check --quick`; 30 in the tool, 20 given in batches in chat and recorded by
  `scripts/record_human_batch.py`). Agreement with the LLM labels (`docs/results/silver_agreement.json`):
  entity 72%, Cohen's kappa 0.66; event type 50%, kappa 0.40 (0.37 without 2 items whose answers had been
  shown as a format example). About 7 of the 25 event disagreements are items where the labelling guide has an
  explicit rule that the LLM label follows (sanctions, recalls, bankruptcy, debt issuance); most of the rest
  are genuinely ambiguous between classes. The silver labels are therefore only partly confirmed by a human,
  and every classifier number computed from them is presented with this caveat.
- Error analysis was done on these labels, and generic rule bugs found there were fixed. Results after the fix
  are therefore labelled optimistic; the pre-fix results are kept alongside them
  (`docs/results/silver_eval_prefix.json`).

_Edit this page so it stays accurate as the project progresses._
