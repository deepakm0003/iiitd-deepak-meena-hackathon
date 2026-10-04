"""Append human check labels given in chat batches to data/gold/human_check.jsonl.

Items are taken in the fixed human-check order (tripwire.gold.human_check_sample), skipping ones already
labelled, exactly as `gold check --quick` would present them. Once those 50 are done, the remaining candidates
follow in file order (already shuffled), so the whole evaluation set becomes human-labelled. Usage:
    python scripts/record_human_batch.py --show 50          print the next 50 items to label
    python scripts/record_human_batch.py "1 T 6" "2 QCOM 8" ... [--primed 1,2]
    add --set fresh2 (or --fresh for the first fresh set) to work on a fresh out-of-time test set instead
--primed marks items whose answer had been shown to the labeller beforehand (reported separately);
--revised marks items the labeller changed after being shown which answers contradicted a guide rule.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

from tripwire import gold
from tripwire.config import load_yaml
from tripwire.universe import load_universe

ROOT = Path(__file__).resolve().parents[1]
SPECIAL = {"o": "OTHER", "m": "MACRO", "n": "NONE"}


def main(argv: list[str]) -> int:
    # Windows consoles default to cp1252, which cannot print emoji or the rupee sign in headlines
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    flags: dict[str, set[int]] = {}
    for flag in ("--primed", "--revised"):
        if flag in argv:
            i = argv.index(flag)
            flags[flag] = {int(x) for x in argv[i + 1].split(",")}
            argv = argv[:i] + argv[i + 2:]
    primed, revised = flags.get("--primed", set()), flags.get("--revised", set())
    # A fresh out-of-time test set has its own candidates and labels files: --set fresh2 reads
    # fresh2_candidates.jsonl and writes fresh2_labels.jsonl (--fresh is the first set, "fresh").
    test_set = None
    if "--fresh" in argv:
        test_set, argv = "fresh", [x for x in argv if x != "--fresh"]
    if "--set" in argv:
        i = argv.index("--set")
        test_set, argv = argv[i + 1], argv[:i] + argv[i + 2:]
    check = ROOT / "data" / "gold" / (f"{test_set}_labels.jsonl" if test_set else "human_check.jsonl")
    classes = [c["name"] for c in load_yaml("taxonomy.yaml")["classes"]]
    tickers = {c.ticker for c in load_universe()}
    if test_set:
        order = gold.read_jsonl(ROOT / "data" / "gold" / f"{test_set}_candidates.jsonl")
    else:
        candidates = gold.read_jsonl(ROOT / "data" / "gold" / "candidates.jsonl")
        sample = gold.human_check_sample(candidates)
        first = {c["key"] for c in sample}
        order = sample + [c for c in candidates if c["key"] not in first]
    done = {r["key"] for r in gold.read_jsonl(check)}
    todo = [c for c in order if c["key"] not in done]
    if argv and argv[0] == "--show":
        for n, c in enumerate(todo[: int(argv[1])], 1):
            text = (c.get("lead") or "")[:300]
            print(f"{n}. [{c['source']}] {c['title'][:220]}")
            if text:
                print(f"   TEXT: {text}")
        print(f"({len(done)} labelled, {len(todo)} remaining)")
        return 0
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
            "note": "answer was shown as a format example before labelling" if n in primed
            else "revised by the labeller after a guideline-consistency check" if n in revised else "",
            "annotator": "deepak (human, quick check given in chat)", "test_set": item.get("test_set"),
            "labeled_at": datetime.now(UTC).isoformat(),
        })
    for row in rows:
        gold.append_jsonl(check, row)
    print(f"saved {len(rows)}; total {len(gold.read_jsonl(check))} of {len(order)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
