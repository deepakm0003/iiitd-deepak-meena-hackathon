"""Draw a fresh out-of-time test set: articles published after the model freeze, sampled the same stratified way
as before, never seen by any experiment.

The freeze time defaults to when the shipped event head was last written (models/event_head.pkl), so nothing the
current models were trained or tuned on can be in the set. Items already in any earlier candidate file are
excluded. Writes data/gold/<name>_candidates.jsonl and <name>_candidates_report.json; label them with
    python scripts/record_human_batch.py --set <name> --show 50
Run on the server (it reads the live store): python scripts/make_fresh_set.py --name fresh2
"""

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from tripwire import gold
from tripwire.factory import build_store
from tripwire.nlp.classifier import HEAD_PATH
from tripwire.settings import get_settings

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "data" / "gold"
# Same strata sizes as the first fresh set (data/gold/fresh_candidates_report.json).
PLAN = {"Other": 30, "Geopolitical": 20, "Regulatory/Legal": 20, "Macroeconomic": 20, "Product Launch": 20,
        "Merger/Acquisition": 15, "Earnings": 10, "Management Change": 8, "Cyber/Operational": 7, "Credit Event": 6,
        "Natural Disaster/Supply Chain": 6}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="set name, e.g. fresh2")
    ap.add_argument("--after", help="ISO time; default: when models/event_head.pkl was last written")
    ap.add_argument("--seed", type=int, default=23)
    args = ap.parse_args()
    out = GOLD / f"{args.name}_candidates.jsonl"
    if out.exists():
        print(f"{out} exists; refusing to replace a test set", file=sys.stderr)
        return 1
    freeze = (datetime.fromisoformat(args.after) if args.after
              else datetime.fromtimestamp(HEAD_PATH.stat().st_mtime, tz=UTC))
    if freeze.tzinfo is None:
        freeze = freeze.replace(tzinfo=UTC)
    seen = set()
    for path in GOLD.glob("*candidates.jsonl"):
        seen |= {r["key"] for r in gold.read_jsonl(path)}
    store = build_store(get_settings())
    predicted = {a["dedup_key"]: a["event_type"] for a in store.get_annotations()}
    docs = [d for d in store.iter_documents(since=freeze) if d.published_at >= freeze and d.dedup_key not in seen]
    rows = gold.sample_stratified(docs, predicted, plan=PLAN, seed=args.seed)
    for r in rows:
        r.update({"split": "test", "test_set": f"{args.name}_{datetime.now(UTC).date().isoformat()}",
                  "frozen_at": freeze.isoformat()})
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    report = {"n": len(rows), "frozen_at": freeze.isoformat(), "documents_after_freeze": len(docs),
              "by_stratum": dict(Counter(r["stratum"] for r in rows)),
              "by_source": dict(Counter(r["source"] for r in rows))}
    (GOLD / f"{args.name}_candidates_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
