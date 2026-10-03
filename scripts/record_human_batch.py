"""Append human check labels given in chat batches to data/gold/human_check.jsonl.

Items are taken in the fixed human-check order (tripwire.gold.human_check_sample), skipping ones already
labelled, exactly as `gold check --quick` would present them. Usage:
    python scripts/record_human_batch.py "1 T 6" "2 QCOM 8" ... [--primed 1,2]
--primed marks items whose answer had been shown to the labeller beforehand (reported separately).
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

from tripwire import gold
from tripwire.config import load_yaml
from tripwire.universe import load_universe

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "data" / "gold" / "human_check.jsonl"
SPECIAL = {"o": "OTHER", "m": "MACRO", "n": "NONE"}


def main(argv: list[str]) -> int:
    primed = set()
    if "--primed" in argv:
        i = argv.index("--primed")
        primed = {int(x) for x in argv[i + 1].split(",")}
        argv = argv[:i] + argv[i + 2:]
    classes = [c["name"] for c in load_yaml("taxonomy.yaml")["classes"]]
    tickers = {c.ticker for c in load_universe()}
    sample = gold.human_check_sample(gold.read_jsonl(ROOT / "data" / "gold" / "candidates.jsonl"))
    done = {r["key"] for r in gold.read_jsonl(CHECK)}
    todo = [c for c in sample if c["key"] not in done]
    rows = []
    for line in argv:
        parts = line.split()
        n = int(parts[0])
        item = todo[n - 1]
        if parts[1].lower() == "skip":
            continue
        entity = SPECIAL.get(parts[1].lower(), parts[1].upper())
        if entity not in tickers and entity not in SPECIAL.values():
            raise SystemExit(f"item {n}: unknown company code {parts[1]!r}")
        event = int(parts[2])
        if not 1 <= event <= len(classes):
            raise SystemExit(f"item {n}: event number must be 1-{len(classes)}")
        rows.append({
            "key": item["key"], "document_id": item.get("document_id"), "published_at": item.get("published_at"),
            "split": item["split"], "stratum": item["stratum"], "source": item["source"], "title": item["title"],
            "entity": entity, "event_type": classes[event - 1], "sentiment": None, "factuality": None,
            "material": None,
            "note": "answer was shown as a format example before labelling" if n in primed else "",
            "annotator": "deepak (human, quick check given in chat)", "labeled_at": datetime.now(UTC).isoformat(),
        })
    for row in rows:
        gold.append_jsonl(CHECK, row)
    print(f"saved {len(rows)}; total {len(gold.read_jsonl(CHECK))} of {len(sample)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
