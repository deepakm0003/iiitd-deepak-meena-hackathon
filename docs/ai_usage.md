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
- **Human labels for the whole set:** the author then labelled all 296 items (entity and event type), 50 in the
  `gold check --quick` tool and the rest in batches given in chat and recorded verbatim by
  `scripts/record_human_batch.py` (`data/gold/human_check.jsonl`). These human labels are the test labels for
  every reported classifier number (`docs/results/gold_eval.json`); the LLM silver labels are kept for
  comparison only.
- **Guideline-consistency check:** after each batch, the assistant listed answers that contradicted an explicit
  rule on the definitions card (for example a bankruptcy labelled as a merger); the author confirmed or
  changed each one. 29 items were revised this way or had an answer shown as a format example; they carry a
  note in the file.
- **Human vs LLM agreement** (`docs/results/silver_agreement.json`): all 296 items, event type 73% (Cohen's
  kappa 0.67), entity 75% (kappa 0.71); without the 29 revised or primed items, event kappa 0.63, entity 0.71.
  The first 50-item check, done before the definitions card was used, gave event kappa 0.40.

_Edit this page so it stays accurate as the project progresses._
